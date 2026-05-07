from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from pythinker_code.soul import Soul
from pythinker_code.utils.slashcmd import SlashCommandCall


@pytest.mark.asyncio
async def test_shell_prompt_dispatches_registered_usage_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pythinker_code.ui.shell import Shell, shell_slash_registry

    assert shell_slash_registry.find_command("usage") is not None
    calls: list[tuple[str, str]] = []

    async def record_slash_command(self: Shell, command_call: SlashCommandCall) -> None:
        calls.append((command_call.name, command_call.args))

    async def fail_soul_command(self: Shell, user_input: object) -> bool:
        raise AssertionError(f"expected shell slash dispatch, got soul command: {user_input!r}")

    monkeypatch.setattr(Shell, "_run_slash_command", record_slash_command)
    monkeypatch.setattr(Shell, "run_soul_command", fail_soul_command)

    shell = Shell(cast(Soul, SimpleNamespace(available_slash_commands=[], name="test")))

    assert await shell.run("/usage --json")
    assert calls == [("usage", "--json")]


@pytest.mark.asyncio
async def test_shell_prompt_exit_returns_without_slash_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pythinker_code.ui.shell import Shell

    async def fail_slash_command(self: Shell, command_call: SlashCommandCall) -> None:
        raise AssertionError(f"expected exit guard, got slash command: {command_call!r}")

    async def fail_soul_command(self: Shell, user_input: object) -> bool:
        raise AssertionError(f"expected exit guard, got soul command: {user_input!r}")

    monkeypatch.setattr(Shell, "_run_slash_command", fail_slash_command)
    monkeypatch.setattr(Shell, "run_soul_command", fail_soul_command)

    shell = Shell(cast(Soul, SimpleNamespace(available_slash_commands=[], name="test")))

    assert await shell.run("/exit")
