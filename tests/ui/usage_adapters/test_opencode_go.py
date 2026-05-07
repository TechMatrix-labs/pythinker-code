from __future__ import annotations

import asyncio

import pytest

from pythinker_code.ui.shell.usage_adapters.opencode_go import (
    _WINDOW_REGEXES,
    OpenCodeGoAdapter,
    _report_from_caps,
    _report_from_windows,
)


class _StubOAuth:
    def resolve_api_key(self, api_key, oauth):  # pyright: ignore[reportUnusedParameter]
        return ""


class _StubProvider:
    pass


def test_opencode_go_metadata() -> None:
    assert OpenCodeGoAdapter.platform_id == "opencode-go"
    assert OpenCodeGoAdapter.requires_admin_key is False


def test_opencode_go_falls_back_to_static_caps_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_GO_WORKSPACE_ID", raising=False)
    monkeypatch.delenv("OPENCODE_GO_AUTH_COOKIE", raising=False)

    adapter = OpenCodeGoAdapter()
    report = asyncio.run(adapter.fetch(_StubProvider(), _StubOAuth()))  # type: ignore[arg-type]

    assert report.summary is not None
    assert report.summary.label == "5h cap"
    assert report.summary.unit == "USD"
    assert report.summary.limit == 1200
    by_label = {r.label: r for r in report.limits}
    assert by_label["Weekly cap"].limit == 3000
    assert by_label["Monthly cap"].limit == 6000
    assert any("OPENCODE_GO_WORKSPACE_ID" in n for n in report.notes)


def test_opencode_go_partial_env_surfaces_missing_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCODE_GO_WORKSPACE_ID", "ws-123")
    monkeypatch.delenv("OPENCODE_GO_AUTH_COOKIE", raising=False)

    adapter = OpenCodeGoAdapter()
    report = asyncio.run(adapter.fetch(_StubProvider(), _StubOAuth()))  # type: ignore[arg-type]
    assert any("OPENCODE_GO_AUTH_COOKIE" in n for n in report.notes)


def test_window_regexes_parse_pct_first_shape() -> None:
    """Match the SolidJS hydration shape with usagePercent before resetInSec."""
    html = (
        "...prelude..."
        "rollingUsage:$R[12]={usagePercent:42.5,resetInSec:7200,foo:1},"
        "weeklyUsage:$R[34]={usagePercent:18,resetInSec:432000},"
        "monthlyUsage:$R[56]={usagePercent:5,resetInSec:1296000}"
        "...rest..."
    )
    for field, label in (
        ("rollingUsage", "5h"),
        ("weeklyUsage", "Weekly"),
        ("monthlyUsage", "Monthly"),
    ):
        pct_first, _ = _WINDOW_REGEXES[field]
        match = pct_first.search(html)
        assert match is not None, f"failed to parse {label} window"


def test_window_regexes_parse_reset_first_shape() -> None:
    """Match the SolidJS hydration shape with resetInSec before usagePercent."""
    html = "rollingUsage:$R[1]={resetInSec:60,usagePercent:99}"
    _, reset_first = _WINDOW_REGEXES["rollingUsage"]
    match = reset_first.search(html)
    assert match is not None
    assert match.group(1) == "60"
    assert match.group(2) == "99"


def test_report_from_windows_clamps_and_orders_rows() -> None:
    windows = {
        "5h": (35.0, 7200.0),
        "Weekly": (0.0, 432000.0),
        "Monthly": (150.0, 0.0),  # bogus >100% — must clamp to 0% remaining
    }
    report = _report_from_windows(windows, live=True)
    assert report.summary is not None
    assert report.summary.label == "5h window"
    assert report.summary.used == 65  # 100 - 35
    by_label = {r.label: r for r in (report.summary, *report.limits)}
    assert by_label["Weekly window"].used == 100
    assert by_label["Monthly window"].used == 0  # clamped
    assert any("scraped" in n.lower() for n in report.notes)


def test_report_from_caps_includes_error_note_when_present() -> None:
    report = _report_from_caps(error_note="boom")
    assert report.summary is not None
    assert report.summary.unit == "USD"
    assert any("boom" in n for n in report.notes)
    assert any("16017" in n for n in report.notes)
