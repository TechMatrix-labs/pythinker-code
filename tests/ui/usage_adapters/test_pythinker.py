from __future__ import annotations

import json
from pathlib import Path

from pythinker_code.ui.shell.usage_adapters.pythinker import (
    PythinkerAdapter,
    parse_pythinker_payload,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_pythinker_payload_returns_summary_and_two_limits() -> None:
    payload = json.loads((FIXTURES / "pythinker_basic.json").read_text())

    report = parse_pythinker_payload(payload)

    assert report.provider_label == "Pythinker"
    assert report.summary is not None
    assert report.summary.label == "Weekly limit"
    assert report.summary.used == 30
    assert report.summary.limit == 100
    assert report.summary.unit is None

    assert len(report.limits) == 2
    assert report.limits[0].label == "5h limit"
    assert report.limits[0].used == 60
    assert report.limits[0].limit == 200
    assert "resets in" in (report.limits[0].reset_hint or "")
    assert report.limits[1].label == "1d limit"


def test_parse_pythinker_payload_empty_returns_empty_report() -> None:
    report = parse_pythinker_payload({})
    assert report.is_empty


def test_pythinker_adapter_metadata() -> None:
    assert PythinkerAdapter.platform_id == "pythinker-code"
    assert PythinkerAdapter.requires_admin_key is False
