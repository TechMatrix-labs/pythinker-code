from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from pythinker_core.message import Message

from pythinker_code.soul.dynamic_injection import DynamicInjection, DynamicInjectionProvider

if TYPE_CHECKING:
    from pythinker_code.soul.pythinkersoul import PythinkerSoul

_AUTO_INJECTION_TYPE = "auto_mode"

_AUTO_PROMPT = (
    "You are running in auto mode. No user is present to answer "
    "questions or approve actions. All tool calls are auto-approved by "
    "the harness.\n"
    "- Do NOT call AskUserQuestion — it will be auto-dismissed with no "
    "answer, wasting a turn. Make your best judgment and proceed.\n"
    "- You CAN use EnterPlanMode / ExitPlanMode normally. They will be "
    "auto-approved. Planning still helps you think before acting; use "
    "it for non-trivial tasks, then exit and execute.\n"
    "- Finish the user's request end-to-end in this run. Do not defer "
    "decisions to a human."
)

AUTO_DISABLED_REMINDER = (
    "Auto mode is now disabled. The user is back at the terminal and CAN answer "
    "AskUserQuestion.\n"
    "- Ignore any earlier auto mode reminders that said no user is present or "
    "that you must not call AskUserQuestion.\n"
    "- AskUserQuestion is available again when a decision genuinely changes "
    "your next action. Do not ask routine confirmations or progress check-ins.\n"
    "- Tool calls are no longer auto-approved by auto mode. They may still be "
    "auto-approved if yolo mode remains active."
)


class AutoModeInjectionProvider(DynamicInjectionProvider):
    """Injects auto-mode (no user present) guidance for the model."""

    def __init__(self) -> None:
        self._injected: bool = False

    async def get_injections(
        self,
        history: Sequence[Message],
        soul: PythinkerSoul,
    ) -> list[DynamicInjection]:
        _ = history
        if not soul.is_auto:
            return []
        if not soul.is_auto_flag:
            return []

        if self._injected:
            return []
        self._injected = True
        return [DynamicInjection(type=_AUTO_INJECTION_TYPE, content=_AUTO_PROMPT)]

    async def on_context_compacted(self) -> None:
        # Compaction rewrites history; the prior auto-mode reminder may have
        # been summarized away, so let the next auto step restate the
        # constraint.
        self._injected = False

    async def on_auto_changed(self, enabled: bool) -> None:
        # A runtime toggle changes the latest truth about user presence.
        # Re-arm so the next LLM step can inject the current auto guidance.
        _ = enabled
        self._injected = False
