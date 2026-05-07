"""Tests for AutoModeInjectionProvider."""

from __future__ import annotations

from unittest.mock import MagicMock

from pythinker_code.soul.dynamic_injections.auto_mode import (
    _AUTO_INJECTION_TYPE,
    _AUTO_PROMPT,
    AutoModeInjectionProvider,
)


def _mock_soul(
    is_auto: bool,
    is_auto_flag: bool = True,
    is_yolo: bool = False,
    is_subagent: bool = False,
    has_ask_user: bool = True,
) -> MagicMock:
    soul = MagicMock()
    soul.is_auto = is_auto
    soul.is_auto_flag = is_auto_flag
    soul.is_yolo = is_yolo
    soul.is_subagent = is_subagent
    soul.has_tool.return_value = has_ask_user
    return soul


async def test_injects_when_auto_enabled() -> None:
    provider = AutoModeInjectionProvider()
    result = await provider.get_injections([], _mock_soul(is_auto=True))
    assert len(result) == 1
    assert result[0].type == _AUTO_INJECTION_TYPE
    assert result[0].content == _AUTO_PROMPT
    assert "auto" in result[0].content.lower()
    assert "Do NOT call AskUserQuestion" in result[0].content


async def test_runtime_auto_does_not_inject_prompt() -> None:
    provider = AutoModeInjectionProvider()
    result = await provider.get_injections([], _mock_soul(is_auto=True, is_auto_flag=False))
    assert result == []


async def test_no_injection_when_auto_disabled() -> None:
    provider = AutoModeInjectionProvider()
    result = await provider.get_injections([], _mock_soul(is_auto=False))
    assert result == []


async def test_persistent_auto_injected_once_even_if_auto_stays_on() -> None:
    provider = AutoModeInjectionProvider()
    first = await provider.get_injections([], _mock_soul(is_auto=True))
    second = await provider.get_injections([], _mock_soul(is_auto=True))
    assert len(first) == 1
    assert second == []


async def test_runtime_auto_does_not_rearm_prompt() -> None:
    provider = AutoModeInjectionProvider()
    soul = _mock_soul(is_auto=True, is_auto_flag=False)
    first = await provider.get_injections([], soul)
    second = await provider.get_injections([], soul)
    assert first == []
    assert second == []


async def test_injected_when_both_auto_and_yolo() -> None:
    provider = AutoModeInjectionProvider()
    result = await provider.get_injections([], _mock_soul(is_auto=True, is_yolo=True))
    assert len(result) == 1
    assert result[0].type == _AUTO_INJECTION_TYPE


async def test_injects_even_when_ask_user_unavailable() -> None:
    """Auto is a global non-interactive mode, independent of tool availability."""
    provider = AutoModeInjectionProvider()
    soul = _mock_soul(is_auto=True, has_ask_user=False)
    result = await provider.get_injections([], soul)
    assert len(result) == 1
    assert result[0].type == _AUTO_INJECTION_TYPE
    soul.has_tool.assert_not_called()


async def test_injects_in_subagent() -> None:
    """Subagents still need to know auto is non-interactive and auto-approved."""
    provider = AutoModeInjectionProvider()
    result = await provider.get_injections(
        [],
        _mock_soul(is_auto=True, is_subagent=True),
    )
    assert len(result) == 1
    assert result[0].type == _AUTO_INJECTION_TYPE


async def test_rearms_after_auto_toggle_cycle() -> None:
    provider = AutoModeInjectionProvider()
    soul = _mock_soul(is_auto=True)

    first = await provider.get_injections([], soul)
    second = await provider.get_injections([], soul)
    assert len(first) == 1
    assert second == []

    await provider.on_auto_changed(False)
    await provider.on_auto_changed(True)

    third = await provider.get_injections([], soul)
    assert len(third) == 1
    assert third[0].type == _AUTO_INJECTION_TYPE


async def test_rearms_after_context_compaction() -> None:
    provider = AutoModeInjectionProvider()
    soul = _mock_soul(is_auto=True)

    first = await provider.get_injections([], soul)
    second = await provider.get_injections([], soul)
    assert len(first) == 1
    assert second == []

    await provider.on_context_compacted()

    third = await provider.get_injections([], soul)
    assert len(third) == 1
    assert third[0].type == _AUTO_INJECTION_TYPE
