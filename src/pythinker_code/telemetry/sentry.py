"""Sentry / Bugsink integration.

Initializes ``sentry_sdk`` so unhandled exceptions, asyncio task failures, and
explicit ``capture_exception`` calls flow to Bugsink at ``errors.pythinker.com``.
The integration is additive: the existing ``crash.py`` excepthook still emits a
privacy-respecting ``crash`` event for in-process counting.

Privacy posture:
  - ``send_default_pii=False`` — Sentry will not auto-capture user info from
    request frames or local variables it considers personal.
  - ``before_send`` strips file paths to package-relative form so site-packages
    layouts don't reveal the user's home directory.
  - Loop integrations are explicitly enabled; everything else inherits Sentry's
    safe defaults.

Opt out: ``PYTHINKER_DISABLE_TELEMETRY=1``.
"""

from __future__ import annotations

import contextlib
import os
import re
from typing import Any, cast

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.excepthook import ExcepthookIntegration
from sentry_sdk.types import Event, Hint

from pythinker_code.telemetry.config import is_disabled, sentry_dsn

_initialized: bool = False

# File-path scrubbing: collapse anything before "site-packages/" or
# "pythinker_code/" to "<env>" so Sentry stack frames don't expose home dirs.
_PATH_SCRUB = re.compile(
    r"^(.*?)(site-packages|pythinker_code|src/pythinker_code)/",
)


def _scrub_path(path: str) -> str:
    return _PATH_SCRUB.sub(r"<env>/\2/", path)


def _before_send(event: Event, hint: Hint) -> Event | None:
    """Sentry hook applied to every outgoing event.

    Drops absolute file paths (replaces the prefix above ``site-packages/`` or
    ``pythinker_code/`` with ``<env>``) and removes a couple of fields known to
    leak local context.
    """
    # Strip server name (usually the user's hostname).
    event.pop("server_name", None)

    exception_data = event.get("exception")
    if exception_data is None:
        return event
    values = exception_data.get("values")
    if not isinstance(values, list):
        return event

    for exception_raw in cast(list[Any], values):
        if not isinstance(exception_raw, dict):
            continue
        exception = cast(dict[str, Any], exception_raw)
        stacktrace_raw = exception.get("stacktrace")
        if not isinstance(stacktrace_raw, dict):
            continue
        stacktrace = cast(dict[str, Any], stacktrace_raw)
        frames = stacktrace.get("frames")
        if not isinstance(frames, list):
            continue
        for frame_raw in cast(list[Any], frames):
            if not isinstance(frame_raw, dict):
                continue
            frame = cast(dict[str, Any], frame_raw)
            abs_path = frame.get("abs_path")
            if isinstance(abs_path, str):
                frame["abs_path"] = _scrub_path(abs_path)
            filename = frame.get("filename")
            if isinstance(filename, str):
                frame["filename"] = _scrub_path(filename)
    return event


def init(
    *,
    version: str,
    environment: str | None = None,
    device_id: str | None = None,
    extra_tags: dict[str, str] | None = None,
) -> bool:
    """Initialize ``sentry_sdk`` once per process. Returns True if active."""
    global _initialized
    if _initialized:
        return True
    if is_disabled():
        return False

    dsn = sentry_dsn()
    if not dsn:
        return False

    env = environment or os.environ.get("PYTHINKER_ENV") or "production"

    sentry_sdk.init(
        dsn=dsn,
        release=f"pythinker-code@{version}" if version else None,
        environment=env,
        # Dev-mode defaults: capture every error, no traces (OTel handles
        # those). Tune later when distributing to users.
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        send_default_pii=False,
        attach_stacktrace=True,
        max_breadcrumbs=50,
        # Only the integrations that catch unhandled errors. Skip stdlib
        # integrations (logging, atexit) so we don't double-emit alongside
        # OTel logs.
        default_integrations=False,
        integrations=[
            ExcepthookIntegration(always_run=False),
            AsyncioIntegration(),
            DedupeIntegration(),
        ],
        before_send=_before_send,
    )

    if device_id:
        sentry_sdk.set_user({"id": device_id})
    if extra_tags:
        for k, v in extra_tags.items():
            sentry_sdk.set_tag(k, v)

    _initialized = True
    return True


def capture_exception(exc: BaseException) -> None:
    """Forward an exception to Sentry/Bugsink. Safe to call when uninitialized
    (becomes a no-op). Telemetry must never raise into the host program."""
    if not _initialized:
        return
    with contextlib.suppress(Exception):
        sentry_sdk.capture_exception(exc)


def add_breadcrumb(
    *, category: str, message: str, level: str = "info", data: dict[str, Any] | None = None
) -> None:
    """Append a breadcrumb to the Sentry scope (visible in the next captured event)."""
    if not _initialized:
        return
    with contextlib.suppress(Exception):
        sentry_sdk.add_breadcrumb(category=category, message=message, level=level, data=data or {})


def flush(timeout_seconds: float = 2.0) -> None:
    """Block until pending events are sent or the timeout expires."""
    if not _initialized:
        return
    with contextlib.suppress(Exception):
        client = sentry_sdk.get_client()
        if client:
            client.flush(timeout=timeout_seconds)
