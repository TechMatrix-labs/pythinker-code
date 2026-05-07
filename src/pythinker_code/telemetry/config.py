"""Telemetry endpoint configuration.

Defaults point at the pythinker-operated Bugsink + SigNoz infrastructure.
Sentry/Bugsink DSNs are designed to be public; the OTLP bearer token is embedded
following the same industry convention used by Datadog RUM and PostHog public
keys, mitigated server-side by rate limiting and PII scrubbing at the edge
collector.

Override any value at runtime with the matching environment variable. Disable
telemetry entirely with ``PYTHINKER_DISABLE_TELEMETRY=1``.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Bugsink (Sentry-protocol error tracking)
# ---------------------------------------------------------------------------

DEFAULT_SENTRY_DSN = "https://ab578ebdf2f24c279d9e866ee190574c@errors.pythinker.com/1"

# ---------------------------------------------------------------------------
# SigNoz via the pythinker edge OTel collector
# ---------------------------------------------------------------------------

DEFAULT_OTEL_ENDPOINT = "https://otel.pythinker.com"
DEFAULT_OTEL_INGEST_TOKEN = "83e2d8f0cb72c6c0f8896b40cf68de6e67bfad895a61729b36bc27e594d66d69"

# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def sentry_dsn() -> str:
    """Resolve the Sentry/Bugsink DSN, honoring env override and explicit empty."""
    return os.environ.get("PYTHINKER_SENTRY_DSN", DEFAULT_SENTRY_DSN)


def otel_endpoint() -> str:
    """Resolve the OTLP HTTP endpoint base URL (no trailing slash)."""
    return os.environ.get("PYTHINKER_OTEL_ENDPOINT", DEFAULT_OTEL_ENDPOINT).rstrip("/")


def otel_ingest_token() -> str:
    """Resolve the bearer token presented to the edge collector."""
    return os.environ.get("PYTHINKER_OTEL_TOKEN", DEFAULT_OTEL_INGEST_TOKEN)


def is_disabled() -> bool:
    """Master kill switch. ``PYTHINKER_DISABLE_TELEMETRY=1`` (or ``true``) disables both
    Sentry and OTel emission for the process."""
    raw = os.environ.get("PYTHINKER_DISABLE_TELEMETRY", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
