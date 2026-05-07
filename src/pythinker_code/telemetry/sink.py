"""EventSink: opt-out check, context enrichment, buffer management, timed flush.

Forwards every accepted event to OpenTelemetry as a structured log record.
The earlier custom-HTTP transport that posted to ``telemetry-logs.pythinker.com``
was retired in the SigNoz migration — the OTel exporter inside ``otel.py`` now
handles batching, retries, and disk-spool semantics on its own.
"""

from __future__ import annotations

import asyncio
import locale
import os
import platform
import threading
from typing import Any, cast

from pythinker_code.utils.logging import logger


def _assert_primitive(scope: str, key: str, value: Any) -> None:
    """Telemetry attribute values must be primitives. Catches accidental
    nested dicts/lists before they reach the OTel SDK serializer."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    raise TypeError(f"telemetry {scope}.{key} must be primitive, got {type(value).__name__}")


def _flatten_event(event: dict[str, Any]) -> dict[str, Any]:
    """Expand ``properties``/``context`` sub-dicts into flat ``property.*`` /
    ``context.*`` keys for OTel attributes. Top-level fields pass through.

    Raises ``TypeError`` on nested values inside properties/context.
    """
    out: dict[str, Any] = {}
    for key, value in event.items():
        if key == "properties":
            properties = cast(dict[str, Any], value) if isinstance(value, dict) else {}
            for pk, pv in properties.items():
                _assert_primitive("property", pk, pv)
                out[f"property.{pk}"] = pv
        elif key == "context":
            context = cast(dict[str, Any], value) if isinstance(value, dict) else {}
            for ck, cv in context.items():
                _assert_primitive("context", ck, cv)
                out[f"context.{ck}"] = cv
        else:
            out[key] = value
    return out


class EventSink:
    """Buffers telemetry events and flushes them in batches to OTel logs."""

    FLUSH_INTERVAL_S = 30.0
    FLUSH_THRESHOLD = 50

    def __init__(
        self,
        *,
        version: str = "",
        model: str = "",
        ui_mode: str = "shell",
    ) -> None:
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        # Static context enrichment
        self._context: dict[str, Any] = {
            "version": version,
            "runtime": "python",
            "platform": platform.system().lower(),
            "arch": platform.machine(),
            "python_version": platform.python_version(),
            "os_version": platform.release(),
            "ci": bool(os.environ.get("CI")),
            "locale": locale.getlocale()[0] or "",
            "terminal": os.environ.get("TERM_PROGRAM", ""),
        }
        self._model = model
        self._ui_mode = ui_mode

    def accept(self, event: dict[str, Any]) -> None:
        """Accept an event into the buffer. Non-blocking, thread-safe."""
        # Enrich with static context (copy to avoid mutating the caller's dict)
        ctx = {**self._context, "ui_mode": self._ui_mode}
        if self._model:
            ctx["model"] = self._model
        enriched = {**event, "context": ctx}

        with self._lock:
            self._buffer.append(enriched)
            should_flush = len(self._buffer) >= self.FLUSH_THRESHOLD

        if should_flush:
            self._schedule_async_flush()

    def start_periodic_flush(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Start a background task that flushes every FLUSH_INTERVAL_S seconds."""
        if self._flush_task is not None:
            return

        async def _periodic() -> None:
            try:
                while True:
                    await asyncio.sleep(self.FLUSH_INTERVAL_S)
                    await self._flush_async()
            except asyncio.CancelledError:
                pass

        if loop is None:
            loop = asyncio.get_running_loop()
        self._flush_task = loop.create_task(_periodic())

    async def retry_disk_events(self) -> None:
        """Compatibility shim — disk retries now happen inside the OTel
        exporter. No-op kept so existing callers don't break."""

    def clear_buffer(self) -> None:
        """Discard all buffered events without sending them."""
        with self._lock:
            self._buffer.clear()

    def stop_periodic_flush(self) -> None:
        """Cancel the periodic flush task."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            self._flush_task = None

    async def flush(self) -> None:
        """Async flush: send all buffered events."""
        await self._flush_async()

    def flush_sync(self) -> None:
        """Synchronous flush for atexit / signal handlers.

        Drops the in-process buffer into the OTel pipeline. Network I/O is
        scheduled by the BatchLogRecordProcessor; the OTel SDK's own shutdown
        (called from ``otel.shutdown``) waits for that batch to drain.
        """
        with self._lock:
            if not self._buffer:
                return
            events = list(self._buffer)
            self._buffer.clear()
        self._emit_to_otel(events)

    async def _flush_async(self) -> None:
        """Take all buffered events and forward them to OTel logs."""
        with self._lock:
            if not self._buffer:
                return
            events = list(self._buffer)
            self._buffer.clear()
        self._emit_to_otel(events)

    def _emit_to_otel(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        try:
            from pythinker_code.telemetry import otel as _otel

            for event in events:
                ts = event.get("timestamp")
                ts_ns = int(ts * 1_000_000_000) if isinstance(ts, (int, float)) else None
                try:
                    attrs = _flatten_event(event)
                except TypeError as exc:
                    # Schema violation — drop, never retry.
                    logger.debug("Telemetry event dropped (non-primitive attr): {err}", err=exc)
                    continue
                attrs.pop("event", None)
                attrs.pop("timestamp", None)
                _otel.emit_log(
                    name=str(event.get("event") or "event"),
                    attributes=attrs,
                    timestamp_ns=ts_ns,
                )
        except Exception:
            logger.debug("OTel flush failed; events dropped")

    def _schedule_async_flush(self) -> None:
        """Schedule an async flush from any thread."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._flush_async())
        except RuntimeError:
            # No running event loop — will be flushed by periodic task or on exit
            pass
