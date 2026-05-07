from __future__ import annotations

import json
from pathlib import Path

from pythinker_code.ui.shell.usage_adapters.openrouter import (
    OpenRouterAdapter,
    parse_openrouter_payload,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_openrouter_payload_paid_tier() -> None:
    payload = json.loads((FIXTURES / "openrouter_key.json").read_text())

    report = parse_openrouter_payload(payload)

    assert report.provider_label == "OpenRouter"
    assert report.unit_hint == "USD"
    assert report.summary is not None
    assert report.summary.label == "Credit balance"
    assert report.summary.unit == "USD"
    assert report.summary.used == 2550
    assert report.summary.limit == 10000
    assert report.summary.reset_hint == "resets monthly"

    labels = [r.label for r in report.limits]
    assert labels == ["Today", "This week", "This month"]
    assert report.limits[0].used == 125
    assert report.limits[0].limit == 0


def test_parse_openrouter_payload_free_tier_unlimited() -> None:
    payload = {
        "data": {
            "label": "Free key",
            "limit": None,
            "limit_remaining": None,
            "limit_reset": None,
            "include_byok_in_limit": False,
            "usage": 0.42,
            "usage_daily": 0.42,
            "usage_weekly": 0.42,
            "usage_monthly": 0.42,
            "byok_usage": 0,
            "byok_usage_daily": 0,
            "byok_usage_weekly": 0,
            "byok_usage_monthly": 0,
            "is_free_tier": True,
        }
    }

    report = parse_openrouter_payload(payload)

    assert report.summary is not None
    assert report.summary.limit == 0
    assert report.summary.used == 42
    assert "Free tier" in (report.notes or [""])[0]


def test_openrouter_adapter_metadata() -> None:
    assert OpenRouterAdapter.platform_id == "openrouter"
    assert OpenRouterAdapter.requires_admin_key is False
