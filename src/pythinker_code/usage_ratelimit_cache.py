"""Process-wide cache of rate-limit headers captured from chat completions.

This is the universal fallback the `/usage` slash command renders for
providers that don't have a dedicated usage adapter (e.g. MiniMax,
OpenCode Go) or whose adapter returned no data. It's populated by an
httpx event hook installed on the chat-completion HTTP client (see
`pythinker_code.llm.create_llm`).

The cache is intentionally process-wide and ephemeral — we only need the
most recent snapshot per provider key and don't want disk persistence in
v1.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True, frozen=True)
class RateLimitSnapshot:
    """Most recent rate-limit state captured for one provider."""

    requests_limit: int | None
    requests_remaining: int | None
    requests_reset_seconds: float | None  # seconds-from-now until reset
    tokens_limit: int | None
    tokens_remaining: int | None
    tokens_reset_seconds: float | None
    captured_at: float  # monotonic seconds when captured

    @property
    def has_any_data(self) -> bool:
        return any(
            v is not None
            for v in (
                self.requests_limit,
                self.requests_remaining,
                self.tokens_limit,
                self.tokens_remaining,
            )
        )


class RateLimitCache:
    """In-memory map of `provider_key → most recent RateLimitSnapshot`."""

    def __init__(self) -> None:
        self._snapshots: dict[str, RateLimitSnapshot] = {}

    def record(self, provider_key: str, headers: Mapping[str, str]) -> None:
        snapshot = _parse_headers(headers)
        if snapshot is not None and snapshot.has_any_data:
            self._snapshots[provider_key] = snapshot

    def snapshot(self, provider_key: str) -> RateLimitSnapshot | None:
        return self._snapshots.get(provider_key)

    def clear(self) -> None:
        self._snapshots.clear()


_CACHE = RateLimitCache()


def get_cache() -> RateLimitCache:
    """Return the process-wide rate-limit cache singleton."""
    return _CACHE


def _parse_headers(headers: Mapping[str, str]) -> RateLimitSnapshot | None:
    """Try the known header schemas and return the first one that yields data."""
    norm = {k.lower(): v for k, v in headers.items()}
    return _parse_openai_shape(norm) or _parse_anthropic_shape(norm)


def _parse_openai_shape(h: Mapping[str, str]) -> RateLimitSnapshot | None:
    """OpenAI / OpenRouter / DeepSeek / Pythinker / OpenCode Go (openai-shape).

    Headers: `x-ratelimit-{limit,remaining,reset}-{requests,tokens}`. Reset
    values use the OpenAI duration format (e.g. `5s`, `1m30s`, `500ms`).
    """
    req_limit = _to_int(h.get("x-ratelimit-limit-requests"))
    req_remaining = _to_int(h.get("x-ratelimit-remaining-requests"))
    req_reset = _to_seconds(h.get("x-ratelimit-reset-requests"))
    tok_limit = _to_int(h.get("x-ratelimit-limit-tokens"))
    tok_remaining = _to_int(h.get("x-ratelimit-remaining-tokens"))
    tok_reset = _to_seconds(h.get("x-ratelimit-reset-tokens"))
    if req_limit is None and tok_limit is None:
        return None
    return RateLimitSnapshot(
        requests_limit=req_limit,
        requests_remaining=req_remaining,
        requests_reset_seconds=req_reset,
        tokens_limit=tok_limit,
        tokens_remaining=tok_remaining,
        tokens_reset_seconds=tok_reset,
        captured_at=time.monotonic(),
    )


def _parse_anthropic_shape(h: Mapping[str, str]) -> RateLimitSnapshot | None:
    """Anthropic uses `anthropic-ratelimit-{requests,tokens}-{limit,remaining,reset}`.

    Reset values are ISO-8601 timestamps, not durations.
    """
    req_limit = _to_int(h.get("anthropic-ratelimit-requests-limit"))
    req_remaining = _to_int(h.get("anthropic-ratelimit-requests-remaining"))
    req_reset_iso = h.get("anthropic-ratelimit-requests-reset")
    tok_limit = _to_int(h.get("anthropic-ratelimit-tokens-limit"))
    tok_remaining = _to_int(h.get("anthropic-ratelimit-tokens-remaining"))
    tok_reset_iso = h.get("anthropic-ratelimit-tokens-reset")
    if req_limit is None and tok_limit is None:
        return None
    return RateLimitSnapshot(
        requests_limit=req_limit,
        requests_remaining=req_remaining,
        requests_reset_seconds=_iso_to_seconds(req_reset_iso),
        tokens_limit=tok_limit,
        tokens_remaining=tok_remaining,
        tokens_reset_seconds=_iso_to_seconds(tok_reset_iso),
        captured_at=time.monotonic(),
    )


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)")


def _to_seconds(value: str | None) -> float | None:
    """Parse OpenAI's reset-duration format. Examples: `5s`, `1m30s`, `500ms`."""
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    total = 0.0
    for amount, unit in _DURATION_RE.findall(text):
        n = float(amount)
        if unit == "ms":
            total += n / 1000
        elif unit == "s":
            total += n
        elif unit == "m":
            total += n * 60
        elif unit == "h":
            total += n * 3600
    return total if total > 0 else None


def _iso_to_seconds(value: str | None) -> float | None:
    """Convert an ISO-8601 timestamp into seconds-from-now (clamped at 0)."""
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    delta = (dt - datetime.now(UTC)).total_seconds()
    return delta if delta > 0 else 0.0
