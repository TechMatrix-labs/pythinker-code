from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pythinker_code.ui.shell import usage as usage_module
from pythinker_code.ui.shell.usage import (
    _gather_reports,
    _print_no_usage_providers,
    _select_providers,
)
from pythinker_code.ui.shell.usage_adapters.base import UsageReport, UsageRow


@pytest.mark.asyncio
async def test_gather_reports_runs_adapters_concurrently() -> None:
    fake_adapter_a = MagicMock()
    fake_adapter_a.fetch = AsyncMock(
        return_value=UsageReport(provider_label="A", summary=None, limits=[], notes=[])
    )
    fake_adapter_b = MagicMock()
    fake_adapter_b.fetch = AsyncMock(
        return_value=UsageReport(provider_label="B", summary=None, limits=[], notes=[])
    )

    provider_a = MagicMock()
    provider_b = MagicMock()
    oauth = MagicMock()

    reports = await _gather_reports(
        [(fake_adapter_a, provider_a), (fake_adapter_b, provider_b)],
        oauth_mgr=oauth,
    )
    assert [r.provider_label for r in reports] == ["A", "B"]
    fake_adapter_a.fetch.assert_awaited_once_with(provider_a, oauth)
    fake_adapter_b.fetch.assert_awaited_once_with(provider_b, oauth)


@pytest.mark.asyncio
async def test_gather_reports_isolates_failures() -> None:
    bad = MagicMock()
    bad.fetch = AsyncMock(side_effect=RuntimeError("boom"))
    bad.provider_label = "Bad"
    good = MagicMock()
    good.fetch = AsyncMock(
        return_value=UsageReport(provider_label="Good", summary=None, limits=[], notes=[])
    )

    reports = await _gather_reports(
        [(bad, MagicMock()), (good, MagicMock())], oauth_mgr=MagicMock()
    )
    labels = [r.provider_label for r in reports]
    assert "Good" in labels
    bad_report = next(r for r in reports if r.provider_label == "Bad")
    assert any("boom" in n for n in bad_report.notes)


@pytest.mark.asyncio
async def test_gather_reports_does_not_apply_outer_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MagicMock()
    adapter.platform_id = "slow"
    adapter.provider_label = "Slow"
    adapter.fetch = AsyncMock(
        return_value=UsageReport(provider_label="Slow", summary=None, limits=[], notes=[])
    )

    def fail_if_used(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("outer timeout used")

    monkeypatch.setattr(usage_module.asyncio, "wait_for", fail_if_used)

    reports = await _gather_reports([(adapter, MagicMock())], oauth_mgr=MagicMock())

    assert reports[0].provider_label == "Slow"
    assert reports[0].notes == []


def test_select_providers_filters_to_arg() -> None:
    config_providers: dict[str, Any] = {
        "managed:openrouter": MagicMock(),
        "managed:deepseek": MagicMock(),
        "managed:pythinker-code": MagicMock(),
    }
    pairs = _select_providers(
        config_providers,
        registered_platform_ids={"openrouter", "deepseek", "pythinker-code"},
        filter_provider_key="managed:openrouter",
    )
    assert len(pairs) == 1
    assert pairs[0][0] == "openrouter"


def test_select_providers_no_arg_returns_all_registered() -> None:
    config_providers: dict[str, Any] = {
        "managed:openrouter": MagicMock(),
        "managed:unknown": MagicMock(),
    }
    pairs = _select_providers(
        config_providers,
        registered_platform_ids={"openrouter"},
        filter_provider_key=None,
    )
    assert len(pairs) == 1
    assert pairs[0][0] == "openrouter"


def test_usage_report_to_dict_json_serializable() -> None:
    report = UsageReport(
        provider_label="X",
        summary=UsageRow(label="Total", used=100, limit=200, unit="USD"),
        limits=[UsageRow(label="Day", used=10, limit=0, unit="USD")],
        notes=["hello"],
        unit_hint="USD",
    )
    assert json.dumps(report.to_dict())


def test_print_json_writes_directly_to_console_file(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = StringIO()
    fake_console = SimpleNamespace(file=stream)
    value = {"provider_label": "[yellow]literal[/yellow]"}

    monkeypatch.setattr(usage_module, "console", fake_console)

    usage_module._print_json(value)

    assert json.loads(stream.getvalue()) == value


def test_print_no_usage_providers_json_emits_empty_array(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = StringIO()
    fake_console = SimpleNamespace(file=stream)

    monkeypatch.setattr(usage_module, "console", fake_console)

    _print_no_usage_providers(json_mode=True)

    assert json.loads(stream.getvalue()) == []
