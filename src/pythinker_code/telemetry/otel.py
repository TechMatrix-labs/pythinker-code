"""OpenTelemetry (OTLP HTTP) integration.

Sends traces, metrics, and logs to the pythinker edge OTel collector at
``otel.pythinker.com``. The collector forwards to SigNoz internally; clients
authenticate with a bearer token (embedded as a default, env-overridable).

Public API:
  - ``init(version, ui_mode, ...)`` — wire up Tracer/Meter/LoggerProvider.
  - ``get_tracer()`` — get a tracer for span creation.
  - ``get_meter()`` — get the meter for instrument creation.
  - ``emit_log(name, attributes, severity)`` — push a structured log event.
  - ``shutdown()`` — flush exporters at process exit.

Uninitialized state is safe: ``get_tracer`` / ``get_meter`` return no-op
instances and ``emit_log`` becomes a no-op when init wasn't called or the kill
switch is on.
"""

from __future__ import annotations

import logging
import platform
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry._logs import SeverityNumber, set_logger_provider
from opentelemetry._logs._internal import LogRecord
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Meter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from pythinker_code.telemetry.config import is_disabled, otel_endpoint, otel_ingest_token

_TRACER_NAME = "pythinker-code"
_initialized: bool = False
_tracer: Tracer | None = None
_meter: Meter | None = None
_meter_provider: MeterProvider | None = None
_logger_provider: LoggerProvider | None = None
_log = logging.getLogger(__name__)


def _bearer_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {otel_ingest_token()}"}


def _resource(*, version: str, ui_mode: str, device_id: str | None) -> Resource:
    """Build the static resource attributes for every emitted span/log."""
    attrs: dict[str, Any] = {
        "service.name": "pythinker-code",
        "service.version": version or "unknown",
        "deployment.environment": "production",
        "ui.mode": ui_mode or "shell",
        "host.arch": platform.machine(),
        "os.type": platform.system().lower(),
        "process.runtime.name": "python",
        "process.runtime.version": platform.python_version(),
    }
    if device_id:
        # Treat device_id as a stable user-pseudonym (same role as Sentry user.id).
        attrs["user.id"] = device_id
    return Resource.create(attrs)


def init(
    *,
    version: str,
    ui_mode: str,
    device_id: str | None = None,
) -> bool:
    """Idempotently install the OTel SDK with OTLP HTTP exporters."""
    global _initialized, _tracer, _meter, _meter_provider, _logger_provider
    if _initialized:
        return True
    if is_disabled():
        return False

    endpoint = otel_endpoint()
    if not endpoint:
        return False

    resource = _resource(version=version, ui_mode=ui_mode, device_id=device_id)
    headers = _bearer_headers()

    # --- Traces ---
    span_exporter = OTLPSpanExporter(
        endpoint=f"{endpoint}/v1/traces",
        headers=headers,
        timeout=10,
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)
    _tracer = tracer_provider.get_tracer(_TRACER_NAME, version)

    # --- Metrics ---
    metric_exporter = OTLPMetricExporter(
        endpoint=f"{endpoint}/v1/metrics",
        headers=headers,
        timeout=10,
    )
    # 30s export interval keeps backend volume low for a CLI that's typically
    # invoked for short bursts; final flush at process exit catches the tail.
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=30_000)
    _meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(_meter_provider)
    _meter = _meter_provider.get_meter(_TRACER_NAME, version)

    # --- Logs ---
    log_exporter = OTLPLogExporter(
        endpoint=f"{endpoint}/v1/logs",
        headers=headers,
        timeout=10,
    )
    _logger_provider = LoggerProvider(resource=resource)
    _logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(_logger_provider)

    # Pre-create the metric instruments so call sites pay nothing on the hot
    # path. Imported here to avoid a circular dependency at module load time.
    from pythinker_code.telemetry import metrics as _m

    _m.bind(_meter)

    _initialized = True
    _log.debug("OTel SDK initialized at %s", endpoint)
    return True


def get_tracer() -> Tracer:
    """Return the active tracer, or the global no-op tracer when uninitialized."""
    if _tracer is not None:
        return _tracer
    return trace.get_tracer(_TRACER_NAME)


def get_meter() -> Meter:
    """Return the active meter, or the global no-op meter when uninitialized."""
    if _meter is not None:
        return _meter
    return metrics.get_meter(_TRACER_NAME)


def start_span(name: str, attributes: dict[str, Any] | None = None) -> Any:
    """Convenience: ``with start_span("pythinker.turn", {...}) as span:``.

    When OTel is uninitialized this returns a no-op span (the global tracer's
    no-op behaviour) — call sites stay clean and pay nothing in the disabled
    case. The span is the *current* span inside the with block, so child spans
    automatically nest.
    """
    return get_tracer().start_as_current_span(name, attributes=attributes or {})


# ---------------------------------------------------------------------------
# Log emission
# ---------------------------------------------------------------------------

_SEVERITY_BY_NAME = {
    "debug": (SeverityNumber.DEBUG, "DEBUG"),
    "info": (SeverityNumber.INFO, "INFO"),
    "warn": (SeverityNumber.WARN, "WARN"),
    "warning": (SeverityNumber.WARN, "WARN"),
    "error": (SeverityNumber.ERROR, "ERROR"),
}


def emit_log(
    *,
    name: str,
    attributes: dict[str, Any] | None = None,
    severity: str = "info",
    timestamp_ns: int | None = None,
) -> None:
    """Emit a structured OTel LogRecord. Used as the OTLP backend for ``track()``.

    The ``name`` becomes the log body; properties + context become attributes.
    Safe to call before or after init: pre-init calls are dropped silently.
    """
    if not _initialized or _logger_provider is None:
        return
    try:
        sev_number, sev_text = _SEVERITY_BY_NAME.get(
            severity.lower(), (SeverityNumber.INFO, "INFO")
        )
        record = LogRecord(
            timestamp=timestamp_ns,
            observed_timestamp=timestamp_ns,
            severity_number=sev_number,
            severity_text=sev_text,
            body=name,
            attributes=dict(attributes or {}),
        )
        # Use the SDK's logger directly so we don't need to bridge through the
        # stdlib logging module (which has its own handlers we don't want to
        # collide with).
        otel_logger = _logger_provider.get_logger(_TRACER_NAME)
        otel_logger.emit(record)
    except Exception:
        # Never propagate.
        pass


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


def shutdown(timeout_millis: int = 2000) -> None:
    """Flush all three providers. Called at process exit."""
    if not _initialized:
        return
    try:
        tp = trace.get_tracer_provider()
        # The global provider may be the no-op when init failed; guard with
        # hasattr instead of an isinstance check that pulls in private SDK
        # types.
        if hasattr(tp, "shutdown"):
            tp.shutdown()  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        if _meter_provider is not None:
            _meter_provider.shutdown()
    except Exception:
        pass
    try:
        if _logger_provider is not None:
            _logger_provider.shutdown()
    except Exception:
        pass
