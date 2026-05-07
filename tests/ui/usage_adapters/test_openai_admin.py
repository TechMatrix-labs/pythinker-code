from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from pythinker_code.config import LLMProvider
from pythinker_code.ui.shell.usage_adapters import openai_admin
from pythinker_code.ui.shell.usage_adapters.openai_admin import (
    OpenAIAdminAdapter,
    parse_openai_completions,
    parse_openai_costs,
    select_admin_key,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_openai_costs_sums_buckets() -> None:
    payload = json.loads((FIXTURES / "openai_costs.json").read_text())
    summary = parse_openai_costs(payload)
    assert summary is not None
    assert summary.label == "Cost (last 24h)"
    assert summary.unit == "USD"
    assert summary.used == 1234
    assert summary.limit == 0


def test_parse_openai_completions_groups_by_model() -> None:
    payload = json.loads((FIXTURES / "openai_completions.json").read_text())
    rows = parse_openai_completions(payload)
    labels = [r.label for r in rows]
    assert "gpt-5.4" in labels
    assert "gpt-5.4-mini" in labels
    gpt54 = next(r for r in rows if r.label == "gpt-5.4")
    assert gpt54.unit == "tokens"
    assert gpt54.used == 1_258_023
    assert gpt54.limit == 0


def test_select_admin_key_env_wins(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "sk-admin-from-env")
    assert select_admin_key("sk-proj-other") == "sk-admin-from-env"


def test_select_admin_key_falls_back_to_admin_provider_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    assert select_admin_key("sk-admin-abc123") == "sk-admin-abc123"


def test_select_admin_key_returns_none_for_regular_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    assert select_admin_key("sk-proj-xyz") is None


def test_openai_admin_adapter_metadata() -> None:
    assert OpenAIAdminAdapter.platform_id == "openai"
    assert OpenAIAdminAdapter.requires_admin_key is True


async def test_openai_admin_fetch_notes_malformed_successful_payloads(monkeypatch) -> None:
    async def fake_safe_get(
        url: str,
        params: dict[str, str | int],
        api_key: str,
    ) -> dict[str, Any]:
        del url, params
        assert api_key == "sk-admin-test"
        return {"data": {"unexpected": "shape"}}

    monkeypatch.setattr(openai_admin, "_safe_get", fake_safe_get)
    provider = LLMProvider(
        type="openai_responses",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("sk-admin-test"),
    )

    report = await OpenAIAdminAdapter().fetch(provider, oauth_mgr=None)  # type: ignore[arg-type]

    assert report.summary is None
    assert report.limits == []
    assert "OpenAI cost response had unexpected shape." in report.notes
    assert "OpenAI completions usage response had unexpected shape." in report.notes


async def test_openai_admin_fetch_notes_malformed_cost_entries(monkeypatch) -> None:
    async def fake_safe_get(
        url: str,
        params: dict[str, str | int],
        api_key: str,
    ) -> dict[str, Any]:
        del params
        assert api_key == "sk-admin-test"
        if url.endswith("/organization/costs"):
            return {"data": [{"results": [{"amount": "bad"}]}]}
        return {"data": []}

    monkeypatch.setattr(openai_admin, "_safe_get", fake_safe_get)
    provider = LLMProvider(
        type="openai_responses",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("sk-admin-test"),
    )

    report = await OpenAIAdminAdapter().fetch(provider, oauth_mgr=None)  # type: ignore[arg-type]

    assert report.summary is None
    assert "OpenAI cost response had unexpected shape." in report.notes
    assert "OpenAI completions usage response had unexpected shape." not in report.notes
