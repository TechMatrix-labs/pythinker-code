"""Tests for the non-blocking update parity + robust Windows native installer.

Kept in a separate file from test_shell_update.py to avoid colliding with
concurrent edits there. Covers: the cached-only startup notice, the Windows
PID-wait installer command shape, the /update slash command registration, and
the in-shell run_update_prompt flow.
"""

from __future__ import annotations

from types import SimpleNamespace

import pythinker_code.constant as constant
from pythinker_code.ui.shell import update


def _set_notice_state(
    monkeypatch, *, current, cached, dismissed=None, disabled=False, source=False
):
    monkeypatch.setattr(constant, "VERSION", current)
    monkeypatch.setattr(update, "_read_latest_version_cache", lambda: cached)
    monkeypatch.setattr(update, "_read_dismissed_version", lambda: dismissed)
    monkeypatch.setattr(update, "_auto_update_disabled", lambda: disabled)
    monkeypatch.setattr(update, "_is_running_from_source_checkout", lambda: source)
    monkeypatch.setattr(update, "_skipped_version_this_session", None)


def test_pending_update_notice_shows_when_newer(monkeypatch):
    _set_notice_state(monkeypatch, current="1.0.0", cached="1.2.0")
    notice = update.pending_update_notice()
    assert notice is not None
    assert "1.0.0" in notice and "1.2.0" in notice and "/update" in notice


def test_pending_update_notice_none_when_up_to_date(monkeypatch):
    _set_notice_state(monkeypatch, current="1.2.0", cached="1.2.0")
    assert update.pending_update_notice() is None


def test_pending_update_notice_none_when_no_cache(monkeypatch):
    _set_notice_state(monkeypatch, current="1.0.0", cached=None)
    assert update.pending_update_notice() is None


def test_pending_update_notice_none_when_dismissed(monkeypatch):
    _set_notice_state(monkeypatch, current="1.0.0", cached="1.2.0", dismissed="1.2.0")
    assert update.pending_update_notice() is None


def test_pending_update_notice_none_when_skipped_this_session(monkeypatch):
    _set_notice_state(monkeypatch, current="1.0.0", cached="1.2.0")
    update._skip_version_this_session("1.2.0")
    assert update.pending_update_notice() is None


def test_pending_update_notice_none_for_source_checkout(monkeypatch):
    _set_notice_state(monkeypatch, current="1.0.0", cached="1.2.0", source=True)
    assert update.pending_update_notice() is None


def test_windows_upgrade_helper_uses_encoded_powershell(monkeypatch):
    import base64

    monkeypatch.setattr(update, "_is_windows", lambda: True)
    monkeypatch.setattr(update.os, "getpid", lambda: 4242)

    def fake_which(name: str) -> str | None:
        return {
            "powershell": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            "uv": "C:\\Program Files\\uv\\uv.exe",
        }.get(name)

    monkeypatch.setattr(update, "which", fake_which)

    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(update.subprocess, "Popen", fake_popen)

    assert update._spawn_detached_windows_upgrade(["uv", "tool", "upgrade", "pythinker code"])

    args = captured["args"]
    assert isinstance(args, list)
    assert args[0] == "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    assert "-EncodedCommand" in args
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["creationflags"] & 0x00000010  # CREATE_NEW_CONSOLE

    encoded = args[args.index("-EncodedCommand") + 1]
    assert all(c.isalnum() or c in "+/=" for c in encoded)
    script = base64.b64decode(encoded).decode("utf-16-le")

    assert "Waiting for Pythinker (PID 4242) to exit..." in script
    assert "Wait-Process -Id 4242 -Timeout 60" in script
    assert "Start-Sleep" not in script
    assert "$psi.FileName = 'C:\\Program Files\\uv\\uv.exe'" in script
    assert "$psi.Arguments = 'tool upgrade \"pythinker code\"'" in script
    assert "Upgrade finished. Press any key to close this window." in script


async def test_shell_auto_update_toast_shows_new_version_immediately(monkeypatch):
    import pythinker_code.ui.shell as shell_mod

    async def fake_refresh():
        return update.UpdateResult.UPDATE_AVAILABLE

    toast_calls: list[tuple[str, dict[str, object]]] = []
    invalidated: list[bool] = []

    def fake_toast(message: str, **kwargs):
        toast_calls.append((message, kwargs))

    shell = shell_mod.Shell.__new__(shell_mod.Shell)
    # SimpleNamespace stand-in for the CustomPromptSession; only invalidate()
    # is exercised by _auto_update().
    shell._prompt_session = SimpleNamespace(  # type: ignore[assignment]
        invalidate=lambda: invalidated.append(True)
    )

    monkeypatch.setattr(shell_mod, "refresh_update_cache_if_due", fake_refresh)
    monkeypatch.setattr(
        shell_mod,
        "pending_update_notice",
        lambda: "Update available: 0.19.0 → 0.21.0. Run /update to install.",
    )
    monkeypatch.setattr(shell_mod, "toast", fake_toast)

    await shell_mod.Shell._auto_update(shell)

    assert toast_calls == [
        (
            "Update available: 0.19.0 → 0.21.0. Run /update to install.",
            {
                "topic": "update",
                "duration": 30.0,
                "immediate": True,
                "style": "fg:ansibrightyellow bold",
            },
        )
    ]
    assert invalidated == [True]


def test_windows_installer_waits_on_pid_and_cleans_up(monkeypatch, tmp_path):
    import base64

    monkeypatch.setattr(update, "_is_windows", lambda: True)
    monkeypatch.setattr(
        update,
        "which",
        lambda name: "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
        if name == "powershell"
        else None,
    )
    monkeypatch.setattr(update.os, "getpid", lambda: 4242)

    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(update.subprocess, "Popen", fake_popen)

    installer = tmp_path / "PythinkerSetup-1.2.0.exe"
    installer.write_bytes(b"stub")
    assert update._spawn_detached_windows_installer(installer) is True

    args = captured["args"]
    assert isinstance(args, list)
    # PowerShell -EncodedCommand sidesteps the cmd+list2cmdline+CommandLineToArgvW
    # multi-layer quoting that previously turned the Wait-Process call into a
    # string literal PowerShell printed verbatim instead of running.
    assert args[0] == "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    assert "-EncodedCommand" in args
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["creationflags"] & 0x00000010  # CREATE_NEW_CONSOLE

    encoded = args[args.index("-EncodedCommand") + 1]
    # The encoded payload must contain no characters cmd.exe needs to escape.
    assert all(c.isalnum() or c in "+/=" for c in encoded)

    script = base64.b64decode(encoded).decode("utf-16-le")
    # Robust wait on this process's own PID instead of a fixed sleep, capped:
    assert "Wait-Process -Id 4242" in script
    assert "-Timeout 60" in script
    assert "Start-Sleep" not in script
    assert "timeout /t" not in script
    # Silent install + staged-tmpdir cleanup:
    assert "/VERYSILENT" in script
    assert "/SUPPRESSMSGBOXES" in script
    assert "/NORESTART" in script
    assert "[System.Diagnostics.ProcessStartInfo]::new()" in script
    assert "Remove-Item" in script
    assert "-Recurse" in script
    # The actual installer + tmpdir paths are embedded as PS string literals:
    assert str(installer) in script
    assert str(installer.parent) in script
    # User-visible bookend messages:
    assert "Waiting for Pythinker (PID 4242) to exit..." in script
    assert "Installer finished" in script


def test_update_command_registered():
    from pythinker_code.ui.shell import slash

    assert slash.registry.find_command("update") is not None
    assert slash.registry.find_command("upgrade") is not None


async def test_run_update_prompt_reports_up_to_date(monkeypatch):
    monkeypatch.setattr(constant, "VERSION", "2.0.0")
    force_refresh_values: list[bool] = []

    async def fake_resolve(*, force_refresh: bool = False):
        force_refresh_values.append(force_refresh)
        return "1.0.0"

    monkeypatch.setattr(update, "_resolve_latest_version_for_prompt", fake_resolve)
    assert await update.run_update_prompt() is update.UpdateResult.UP_TO_DATE
    assert force_refresh_values == [True]


async def test_run_update_prompt_skip_returns_none(monkeypatch):
    monkeypatch.setattr(constant, "VERSION", "1.0.0")

    async def fake_resolve(*, force_refresh: bool = False):
        assert force_refresh is True
        return "1.2.0"

    async def fake_prompt(current, latest):
        return update.UpdatePromptSelection.SKIP

    monkeypatch.setattr(update, "_resolve_latest_version_for_prompt", fake_resolve)
    monkeypatch.setattr(update, "_prompt_update_selection", fake_prompt)
    assert await update.run_update_prompt() is None
