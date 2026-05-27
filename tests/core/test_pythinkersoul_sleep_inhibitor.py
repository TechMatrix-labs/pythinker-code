from __future__ import annotations

from pathlib import Path

import pytest
from pythinker_core.message import Message
from pythinker_core.tooling.empty import EmptyToolset

import pythinker_code.soul.pythinkersoul as pythinkersoul_module
from pythinker_code.soul.agent import Agent, Runtime
from pythinker_code.soul.context import Context
from pythinker_code.soul.pythinkersoul import PythinkerSoul, TurnOutcome


class FakeSleepInhibitor:
    instances: list[FakeSleepInhibitor] = []

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.calls: list[bool] = []
        self.instances.append(self)

    def set_turn_running(self, turn_running: bool) -> None:
        self.calls.append(turn_running)


def _make_soul(runtime: Runtime, tmp_path: Path) -> PythinkerSoul:
    agent = Agent(
        name="Sleep Inhibitor Agent",
        system_prompt="Test prompt.",
        toolset=EmptyToolset(),
        runtime=runtime,
    )
    return PythinkerSoul(agent, context=Context(file_backend=tmp_path / "history.jsonl"))


@pytest.mark.asyncio
async def test_turn_acquires_and_releases_sleep_inhibitor(
    runtime: Runtime,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.config.prevent_idle_sleep = True
    FakeSleepInhibitor.instances = []
    monkeypatch.setattr(pythinkersoul_module, "SleepInhibitor", FakeSleepInhibitor)
    soul = _make_soul(runtime, tmp_path)

    async def fake_agent_loop() -> TurnOutcome:
        return TurnOutcome(
            stop_reason="no_tool_calls",
            final_message=Message(role="assistant", content="done"),
            step_count=1,
        )

    monkeypatch.setattr(soul, "_agent_loop", fake_agent_loop)

    await soul._turn(Message(role="user", content="hello"))

    inhibitor = FakeSleepInhibitor.instances[0]
    assert inhibitor.enabled is True
    assert inhibitor.calls == [True, False]


@pytest.mark.asyncio
async def test_turn_releases_sleep_inhibitor_on_error(
    runtime: Runtime,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.config.prevent_idle_sleep = True
    FakeSleepInhibitor.instances = []
    monkeypatch.setattr(pythinkersoul_module, "SleepInhibitor", FakeSleepInhibitor)
    soul = _make_soul(runtime, tmp_path)

    async def fake_agent_loop() -> TurnOutcome:
        raise RuntimeError("boom")

    monkeypatch.setattr(soul, "_agent_loop", fake_agent_loop)

    with pytest.raises(RuntimeError, match="boom"):
        await soul._turn(Message(role="user", content="hello"))

    inhibitor = FakeSleepInhibitor.instances[0]
    assert inhibitor.calls == [True, False]
