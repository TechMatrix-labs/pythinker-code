import asyncio
from typing import Any

from pythinker_code.llm import ALL_MODEL_CAPABILITIES, ModelCapability
from pythinker_code.soul import StatusSnapshot, wire_send
from pythinker_code.ui.shell import Shell
from pythinker_code.utils.slashcmd import SlashCommand
from pythinker_code.wire.types import ContentPart, StepBegin, TextPart


class EchoSoul:
    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "EchoSoul"

    @property
    def model_name(self) -> str:
        return "mock"

    @property
    def model_capabilities(self) -> set[ModelCapability]:
        return ALL_MODEL_CAPABILITIES

    @property
    def status(self) -> StatusSnapshot:
        return StatusSnapshot(context_usage=0.0)

    @property
    def available_slash_commands(self) -> list[SlashCommand[Any]]:
        return []

    async def run(
        self,
        user_input: str | list[ContentPart],
        *,
        skip_user_prompt_hook: bool = False,
    ) -> None:
        # ``skip_user_prompt_hook`` is part of the Soul protocol but EchoSoul
        # has no hooks to skip; accept and ignore it for signature compatibility.
        del skip_user_prompt_hook
        wire_send(StepBegin(n=1))
        if isinstance(user_input, str):
            wire_send(TextPart(text=user_input))
        else:
            for part in user_input:
                wire_send(part)


if __name__ == "__main__":
    soul = EchoSoul()
    ui = Shell(soul)
    asyncio.run(ui.run())
