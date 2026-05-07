"""Tests for the `skip_auto_prompt_injection` config gate.

Yolo no longer has a dynamic prompt. This field gates only the auto prompt
provider. Plan mode injection is unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pythinker_core.tooling.empty import EmptyToolset

from pythinker_code.soul.agent import Agent, Runtime
from pythinker_code.soul.context import Context
from pythinker_code.soul.dynamic_injections.auto_mode import AutoModeInjectionProvider
from pythinker_code.soul.dynamic_injections.plan_mode import PlanModeInjectionProvider
from pythinker_code.soul.pythinkersoul import PythinkerSoul


def _make_soul(runtime: Runtime, tmp_path: Path) -> PythinkerSoul:
    agent = Agent(
        name="Test Agent",
        system_prompt="Test system prompt.",
        toolset=EmptyToolset(),
        runtime=runtime,
    )
    return PythinkerSoul(agent, context=Context(file_backend=tmp_path / "history.jsonl"))


def _provider_types(soul: PythinkerSoul) -> set[type]:
    # Access the private list to introspect provider composition.
    return {type(p) for p in soul._injection_providers}  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("skip", [False, True])
def test_skip_auto_prompt_injection_gates_auto_provider(
    runtime: Runtime, tmp_path: Path, skip: bool
) -> None:
    runtime.config.skip_auto_prompt_injection = skip
    soul = _make_soul(runtime, tmp_path)
    types_ = _provider_types(soul)

    # Plan is always present and never gated by this flag.
    assert PlanModeInjectionProvider in types_
    assert not any(provider.__name__.lower().startswith("yolo") for provider in types_)

    if skip:
        assert AutoModeInjectionProvider not in types_
    else:
        assert AutoModeInjectionProvider in types_
