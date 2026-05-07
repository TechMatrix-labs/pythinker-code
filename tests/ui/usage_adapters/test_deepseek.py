from __future__ import annotations

import json
from pathlib import Path

from pythinker_code.ui.shell.usage_adapters.deepseek import (
    DeepSeekAdapter,
    parse_deepseek_payload,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_deepseek_payload_two_currencies() -> None:
    payload = json.loads((FIXTURES / "deepseek_balance.json").read_text())

    report = parse_deepseek_payload(payload)

    assert report.provider_label == "DeepSeek"
    assert report.summary is not None
    assert report.summary.label == "Total balance (CNY)"
    assert report.summary.unit == "CNY"
    assert report.summary.used == 11000
    assert report.summary.limit == 0

    labels = [r.label for r in report.limits]
    assert "Granted (CNY)" in labels
    assert "Topped up (CNY)" in labels
    assert "Total balance (USD)" in labels


def test_parse_deepseek_payload_unavailable_emits_note() -> None:
    report = parse_deepseek_payload({"is_available": False, "balance_infos": []})
    assert report.summary is None
    assert any("balance" in n.lower() for n in report.notes)


def test_parse_deepseek_payload_rejects_string_balance_infos() -> None:
    report = parse_deepseek_payload({"balance_infos": "not-a-list"})
    assert report.summary is None
    assert report.limits == []
    assert any(
        "Unexpected response shape" in note or "balance_infos" in note for note in report.notes
    )


def test_deepseek_adapter_metadata() -> None:
    assert DeepSeekAdapter.platform_id == "deepseek"
    assert DeepSeekAdapter.requires_admin_key is False
