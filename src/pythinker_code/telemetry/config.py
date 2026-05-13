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
import sys

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


_TRUTHY = {"1", "true", "yes", "on"}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def is_test_environment() -> bool:
    """Return True when running under pytest unless explicitly overridden.

    Unit tests deliberately raise synthetic exceptions (``boom``, ``disk full``,
    cancelled subagents, and so on). Those are useful for local assertions but
    must never be exported to the production Bugsink/SigNoz projects.
    """
    if _env_truthy("PYTHINKER_FORCE_TELEMETRY_IN_TESTS"):
        return False
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def is_disabled() -> bool:
    """Master kill switch for external Sentry/OTel emission.

    ``PYTHINKER_DISABLE_TELEMETRY=1`` disables telemetry explicitly. Pytest is
    treated as disabled by default so test suites cannot leak deliberate test
    failures to production telemetry backends.
    """
    return _env_truthy("PYTHINKER_DISABLE_TELEMETRY") or is_test_environment()


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

DEFAULT_OTEL_TRACE_SAMPLE_RATE = 1.0
"""Default fraction of root-trace spans to record. 1.0 = always-on; 0.0 = none."""


def otel_trace_sample_rate() -> float:
    """Resolve the OTel trace sampling rate.

    Honors ``PYTHINKER_OTEL_TRACE_SAMPLE_RATE``. Clamped to ``[0.0, 1.0]``.
    Malformed input falls back to the default rather than disabling tracing
    or raising — telemetry config must never break the host program.
    """
    raw = os.environ.get("PYTHINKER_OTEL_TRACE_SAMPLE_RATE", "").strip()
    if not raw:
        return DEFAULT_OTEL_TRACE_SAMPLE_RATE
    try:
        rate = float(raw)
    except ValueError:
        return DEFAULT_OTEL_TRACE_SAMPLE_RATE
    if rate < 0.0:
        return 0.0
    if rate > 1.0:
        return 1.0
    return rate
