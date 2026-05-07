from __future__ import annotations

from pythinker_code.usage_ratelimit_cache import (
    RateLimitCache,
    _iso_to_seconds,
    _parse_anthropic_shape,
    _parse_openai_shape,
    _to_seconds,
)


def test_parse_openai_shape_full() -> None:
    snap = _parse_openai_shape(
        {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "950",
            "x-ratelimit-reset-requests": "5s",
            "x-ratelimit-limit-tokens": "200000",
            "x-ratelimit-remaining-tokens": "182000",
            "x-ratelimit-reset-tokens": "1m30s",
        }
    )
    assert snap is not None
    assert snap.requests_limit == 1000
    assert snap.requests_remaining == 950
    assert snap.requests_reset_seconds == 5.0
    assert snap.tokens_limit == 200000
    assert snap.tokens_remaining == 182000
    assert snap.tokens_reset_seconds == 90.0


def test_parse_openai_shape_partial_only_tokens() -> None:
    snap = _parse_openai_shape(
        {
            "x-ratelimit-limit-tokens": "5000",
            "x-ratelimit-remaining-tokens": "4500",
        }
    )
    assert snap is not None
    assert snap.requests_limit is None
    assert snap.tokens_limit == 5000


def test_parse_openai_shape_no_data_returns_none() -> None:
    assert _parse_openai_shape({"content-type": "application/json"}) is None


def test_parse_anthropic_shape() -> None:
    snap = _parse_anthropic_shape(
        {
            "anthropic-ratelimit-requests-limit": "50",
            "anthropic-ratelimit-requests-remaining": "47",
            "anthropic-ratelimit-requests-reset": "2099-01-01T00:00:00Z",
            "anthropic-ratelimit-tokens-limit": "100000",
            "anthropic-ratelimit-tokens-remaining": "82000",
            "anthropic-ratelimit-tokens-reset": "2099-01-01T00:00:00Z",
        }
    )
    assert snap is not None
    assert snap.requests_limit == 50
    assert snap.requests_remaining == 47
    # Far-future timestamp → positive seconds
    assert (snap.requests_reset_seconds or 0) > 0
    assert snap.tokens_limit == 100000


def test_to_seconds_handles_compound_durations() -> None:
    assert _to_seconds("5s") == 5.0
    assert _to_seconds("1m30s") == 90.0
    assert _to_seconds("500ms") == 0.5
    assert _to_seconds("1h2m3s") == 3723.0
    assert _to_seconds("12.5") == 12.5
    assert _to_seconds("") is None
    assert _to_seconds(None) is None


def test_iso_to_seconds_past_clamps_to_zero() -> None:
    assert _iso_to_seconds("1970-01-01T00:00:00Z") == 0.0
    assert _iso_to_seconds(None) is None
    assert _iso_to_seconds("not-a-date") is None


def test_cache_records_and_returns_latest() -> None:
    cache = RateLimitCache()
    cache.record(
        "managed:openai",
        {"x-ratelimit-limit-requests": "100", "x-ratelimit-remaining-requests": "99"},
    )
    snap = cache.snapshot("managed:openai")
    assert snap is not None
    assert snap.requests_remaining == 99

    # Second record overwrites.
    cache.record(
        "managed:openai",
        {"x-ratelimit-limit-requests": "100", "x-ratelimit-remaining-requests": "50"},
    )
    snap = cache.snapshot("managed:openai")
    assert snap is not None
    assert snap.requests_remaining == 50


def test_cache_skips_headers_without_data() -> None:
    cache = RateLimitCache()
    cache.record("managed:openai", {"content-type": "application/json"})
    assert cache.snapshot("managed:openai") is None


def test_cache_isolates_providers() -> None:
    cache = RateLimitCache()
    cache.record(
        "managed:openai",
        {"x-ratelimit-limit-requests": "100", "x-ratelimit-remaining-requests": "10"},
    )
    cache.record(
        "managed:anthropic",
        {"anthropic-ratelimit-requests-limit": "50", "anthropic-ratelimit-requests-remaining": "5"},
    )
    openai_snap = cache.snapshot("managed:openai")
    anthropic_snap = cache.snapshot("managed:anthropic")
    assert openai_snap is not None and openai_snap.requests_limit == 100
    assert anthropic_snap is not None and anthropic_snap.requests_limit == 50
