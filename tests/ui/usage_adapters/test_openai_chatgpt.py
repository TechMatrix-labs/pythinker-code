from __future__ import annotations

import json
from pathlib import Path

from pythinker_code.ui.shell.usage_adapters.openai_chatgpt import (
    OpenAIChatGPTAdapter,
    parse_codex_usage_payload,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_codex_usage_two_windows() -> None:
    payload = json.loads((FIXTURES / "codex_wham_usage.json").read_text())

    report = parse_codex_usage_payload(payload)

    assert report.provider_label == "ChatGPT Codex"
    assert report.summary is not None
    assert report.summary.label == "5h window"
    assert report.summary.unit == "%"
    assert report.summary.used == 73
    assert "resets in" in (report.summary.reset_hint or "")

    assert len(report.limits) == 1
    assert report.limits[0].label == "Weekly window"
    assert report.limits[0].used == 41
    assert report.limits[0].unit == "%"


def test_parse_codex_usage_handles_alternative_keys() -> None:
    payload = {
        "rate_limits": {
            "five_hour": {"percent_left": 100, "limit_window_seconds": 18000},
            "weekly": {"percent_left": 100, "limit_window_seconds": 604800},
        }
    }
    report = parse_codex_usage_payload(payload)
    assert report.summary is not None
    assert report.summary.used == 100


def test_parse_codex_usage_missing_rate_limits_emits_note() -> None:
    report = parse_codex_usage_payload({})
    assert report.summary is None
    assert any("rate" in n.lower() for n in report.notes)


def test_parse_codex_usage_non_mapping_emits_note() -> None:
    report = parse_codex_usage_payload([])
    assert report.summary is None
    assert any("response" in n.lower() for n in report.notes)


def test_codex_adapter_metadata() -> None:
    assert OpenAIChatGPTAdapter.platform_id == "openai-chatgpt"
    assert OpenAIChatGPTAdapter.requires_admin_key is False
