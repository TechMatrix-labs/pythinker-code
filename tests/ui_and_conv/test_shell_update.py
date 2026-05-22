from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from rich.console import Console

from pythinker_code.ui.shell import update


@pytest.mark.asyncio
async def test_schedule_auto_update_check_runs_silent_and_throttles(monkeypatch, tmp_path):
    last_check_file = tmp_path / "last_update_check.txt"
    calls: list[tuple[bool, bool]] = []

    async def fake_do_update(*, print: bool, check_only: bool) -> update.UpdateResult:
        calls.append((print, check_only))
        return update.UpdateResult.UP_TO_DATE

    monkeypatch.setattr(update, "LAST_UPDATE_CHECK_FILE", last_check_file)
    monkeypatch.setattr(update.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(update, "do_update", fake_do_update)

    task = update.schedule_auto_update_check()

    assert task is not None
    assert await task is update.UpdateResult.UP_TO_DATE
    assert calls == [(False, True)]
    assert last_check_file.exists()

    calls.clear()
    assert update.schedule_auto_update_check() is None
    assert calls == []


@pytest.mark.asyncio
async def test_schedule_auto_update_check_notifies_when_update_is_available(monkeypatch, tmp_path):
    async def fake_do_update(*, print: bool, check_only: bool) -> update.UpdateResult:
        return update.UpdateResult.UPDATE_AVAILABLE

    banners: list[bool] = []
    monkeypatch.setattr(update, "LAST_UPDATE_CHECK_FILE", tmp_path / "last_update_check.txt")
    monkeypatch.setattr(update.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(update, "do_update", fake_do_update)
    monkeypatch.setattr(update, "print_update_banner", lambda: banners.append(True))

    task = update.schedule_auto_update_check()

    assert task is not None
    assert await task is update.UpdateResult.UPDATE_AVAILABLE
    await asyncio.sleep(0)
    assert banners == [True]


@pytest.mark.asyncio
async def test_do_update_on_windows_spawns_detached_and_exits(monkeypatch, tmp_path):
    spawned: list[list[str]] = []

    async def fake_get_latest(session):
        return "999.0.0"

    monkeypatch.setattr(update, "LATEST_VERSION_FILE", tmp_path / "latest.txt")
    monkeypatch.setattr(update, "_get_latest_version", fake_get_latest)
    monkeypatch.setattr(update, "_is_windows", lambda: True)

    def fake_spawn(cmd: list[str]) -> bool:
        spawned.append(cmd)
        return True

    monkeypatch.setattr(update, "_spawn_detached_windows_upgrade", fake_spawn)

    async def _noop_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(update.asyncio, "sleep", _noop_sleep)

    def fake_run(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called on Windows path")

    monkeypatch.setattr(update.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        await update.do_update(print=False, check_only=False)

    assert excinfo.value.code == 0
    assert spawned and "pythinker-code" in spawned[0]


def test_update_banner_uses_codex_style_release_prompt(monkeypatch):
    rendered = Console(width=100, record=True, color_system=None)
    monkeypatch.setattr(update, "console", rendered)
    monkeypatch.setattr(
        update,
        "_detect_upgrade_command",
        lambda: ["uv", "tool", "upgrade", "pythinker-code"],
    )

    update._render_update_banner("1.2.0", "1.3.0")
    output = rendered.export_text()

    assert "✨ Update available! 1.2.0 -> 1.3.0" in output
    assert "Release notes:" in output
    assert "pythinker update" in output
    assert "uv tool upgrade pythinker-code" in output
    assert "Update Available" not in output
    assert "╭" not in output


@pytest.mark.asyncio
async def test_schedule_auto_update_check_respects_opt_out(monkeypatch, tmp_path):
    async def fail_do_update(*, print: bool, check_only: bool) -> update.UpdateResult:
        raise AssertionError("auto update check should not run")

    monkeypatch.setenv("PYTHINKER_CLI_NO_AUTO_UPDATE", "1")
    monkeypatch.setattr(update, "LAST_UPDATE_CHECK_FILE", tmp_path / "last_update_check.txt")
    monkeypatch.setattr(update.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(update, "do_update", fail_do_update)

    assert update.schedule_auto_update_check() is None
