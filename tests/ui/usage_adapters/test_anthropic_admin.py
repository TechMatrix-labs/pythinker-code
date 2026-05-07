from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from pythinker_code.config import LLMProvider
from pythinker_code.ui.shell.usage_adapters import anthropic_admin
from pythinker_code.ui.shell.usage_adapters.anthropic_admin import (
    ANTHROPIC_BASE,
    AnthropicAdminAdapter,
    parse_anthropic_cost,
    parse_anthropic_usage,
    select_anthropic_admin_key,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_anthropic_cost_sums_buckets() -> None:
    payload = json.loads((FIXTURES / "anthropic_cost.json").read_text())
    summary = parse_anthropic_cost(payload)
    assert summary is not None
    assert summary.label == "Cost (last 24h)"
    assert summary.unit == "USD"
    assert summary.used == 842


def test_parse_anthropic_usage_groups_by_model() -> None:
    payload = json.loads((FIXTURES / "anthropic_usage.json").read_text())
    rows = parse_anthropic_usage(payload)
    labels = [r.label for r in rows]
    assert "claude-opus-4-7" in labels
    assert "claude-sonnet-4-6" in labels
    opus = next(r for r in rows if r.label == "claude-opus-4-7")
    assert opus.used == 4650
    assert opus.unit == "tokens"


def test_select_anthropic_admin_key(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_ADMIN_KEY", "sk-ant-admin-env")
    assert select_anthropic_admin_key("sk-ant-other") == "sk-ant-admin-env"
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
    assert select_anthropic_admin_key("sk-ant-admin-abc") == "sk-ant-admin-abc"
    assert select_anthropic_admin_key("sk-ant-api03-xyz") is None


def test_anthropic_admin_adapter_metadata() -> None:
    assert AnthropicAdminAdapter.platform_id == "anthropic"
    assert AnthropicAdminAdapter.requires_admin_key is True


async def test_anthropic_admin_fetch_requests_usage_grouped_by_model(monkeypatch) -> None:
    usage_params: dict[str, str | int] | None = None

    async def fake_safe_get(
        url: str,
        params: dict[str, str | int],
        api_key: str,
    ) -> dict[str, Any]:
        nonlocal usage_params
        assert api_key == "sk-ant-admin-test"
        if url == f"{ANTHROPIC_BASE}/usage_report/messages":
            usage_params = params
        return {"data": []}

    monkeypatch.setattr(anthropic_admin, "_safe_get", fake_safe_get)
    provider = LLMProvider(
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key=SecretStr("sk-ant-admin-test"),
    )

    await AnthropicAdminAdapter().fetch(provider, oauth_mgr=None)  # type: ignore[arg-type]

    assert usage_params is not None
    assert usage_params["group_by[]"] == "model"


async def test_anthropic_admin_fetch_notes_malformed_successful_payloads(monkeypatch) -> None:
    async def fake_safe_get(
        url: str,
        params: dict[str, str | int],
        api_key: str,
    ) -> dict[str, Any]:
        del url, params
        assert api_key == "sk-ant-admin-test"
        return {"data": {"unexpected": "shape"}}

    monkeypatch.setattr(anthropic_admin, "_safe_get", fake_safe_get)
    provider = LLMProvider(
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key=SecretStr("sk-ant-admin-test"),
    )

    report = await AnthropicAdminAdapter().fetch(provider, oauth_mgr=None)  # type: ignore[arg-type]

    assert report.summary is None
    assert report.limits == []
    assert "Anthropic cost response had unexpected shape." in report.notes
    assert "Anthropic messages usage response had unexpected shape." in report.notes


async def test_anthropic_admin_fetch_notes_malformed_cost_entries(monkeypatch) -> None:
    async def fake_safe_get(
        url: str,
        params: dict[str, str | int],
        api_key: str,
    ) -> dict[str, Any]:
        del params
        assert api_key == "sk-ant-admin-test"
        if url == f"{ANTHROPIC_BASE}/cost_report":
            return {"data": [{"results": [{"amount": "bad"}]}]}
        return {"data": []}

    monkeypatch.setattr(anthropic_admin, "_safe_get", fake_safe_get)
    provider = LLMProvider(
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key=SecretStr("sk-ant-admin-test"),
    )

    report = await AnthropicAdminAdapter().fetch(provider, oauth_mgr=None)  # type: ignore[arg-type]

    assert report.summary is None
    assert "Anthropic cost response had unexpected shape." in report.notes
    assert "Anthropic messages usage response had unexpected shape." not in report.notes
