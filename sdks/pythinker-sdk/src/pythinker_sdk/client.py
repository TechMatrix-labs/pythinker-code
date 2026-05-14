from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pythinker_core import GenerateResult, StepResult, generate, step
from pythinker_core.chat_provider import ChatProvider, StreamedMessagePart
from pythinker_core.chat_provider.pythinker import Pythinker
from pythinker_core.message import ContentPart, Message
from pythinker_core.tooling import Tool, ToolResult, Toolset
from pythinker_core.tooling.simple import SimpleToolset
from pythinker_core.utils.aio import Callback

from pythinker_sdk.conversation import Conversation


class MaxStepsReachedError(RuntimeError):
    """Raised when an agent loop reaches its configured maximum step count."""


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Result returned by :meth:`PythinkerClient.run_until_done`."""

    conversation: Conversation
    steps: tuple[StepResult, ...]
    message: Message
    tool_results: tuple[ToolResult, ...]


class PythinkerClient:
    """Ergonomic wrapper around Pythinker Core generation and tool-step primitives."""

    def __init__(
        self,
        chat_provider: ChatProvider | None = None,
        *,
        model: str = "pythinker-ai",
        api_key: str | None = None,
        base_url: str | None = None,
        stream: bool = True,
        system_prompt: str = "You are a helpful assistant.",
        toolset: Toolset | None = None,
        **client_kwargs: Any,
    ) -> None:
        self.chat_provider = chat_provider or Pythinker(
            model=model,
            api_key=api_key,
            base_url=base_url,
            stream=stream,
            **client_kwargs,
        )
        self.system_prompt = system_prompt
        self.toolset = toolset or SimpleToolset()

    @classmethod
    def from_env(
        cls,
        *,
        model: str = "pythinker-ai",
        api_key: str | None = None,
        base_url: str | None = None,
        stream: bool = True,
        system_prompt: str = "You are a helpful assistant.",
        toolset: Toolset | None = None,
        **client_kwargs: Any,
    ) -> PythinkerClient:
        """Create a client using explicit options plus Pythinker environment fallbacks.

        `api_key` and `base_url` are forwarded to `Pythinker`. When either is omitted,
        `Pythinker` reads `PYTHINKER_API_KEY` and `PYTHINKER_BASE_URL` itself.
        """
        return cls(
            model=model,
            api_key=api_key,
            base_url=base_url,
            stream=stream,
            system_prompt=system_prompt,
            toolset=toolset,
            **client_kwargs,
        )

    async def generate(
        self,
        prompt: str | ContentPart | list[ContentPart] | None = None,
        *,
        history: Sequence[Message] | Conversation | None = None,
        system_prompt: str | None = None,
        tools: Sequence[Tool] | None = None,
        on_message_part: Callback[[StreamedMessagePart], None] | None = None,
    ) -> GenerateResult:
        """Generate one assistant message from a prompt or explicit history."""
        message_history = self._history_with_prompt(prompt, history)
        return await generate(
            chat_provider=self.chat_provider,
            system_prompt=self.system_prompt if system_prompt is None else system_prompt,
            tools=self.toolset.tools if tools is None else tools,
            history=message_history,
            on_message_part=on_message_part,
        )

    async def step(
        self,
        prompt: str | ContentPart | list[ContentPart] | None = None,
        *,
        history: Sequence[Message] | Conversation | None = None,
        system_prompt: str | None = None,
        toolset: Toolset | None = None,
        on_message_part: Callback[[StreamedMessagePart], None] | None = None,
    ) -> StepResult:
        """Run one assistant step and dispatch any tool calls through the configured toolset."""
        message_history = self._history_with_prompt(prompt, history)
        return await step(
            chat_provider=self.chat_provider,
            system_prompt=self.system_prompt if system_prompt is None else system_prompt,
            toolset=self.toolset if toolset is None else toolset,
            history=message_history,
            on_message_part=on_message_part,
        )

    async def run_until_done(
        self,
        prompt: str | ContentPart | list[ContentPart] | None = None,
        *,
        conversation: Conversation | None = None,
        max_steps: int = 8,
        system_prompt: str | None = None,
        toolset: Toolset | None = None,
        on_message_part: Callback[[StreamedMessagePart], None] | None = None,
    ) -> AgentRunResult:
        """Run an agent loop until the assistant returns no tool calls.

        The conversation is updated in-place. Tool-result messages are appended after
        each step so the next step has the required tool context.
        """
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")

        active_conversation = conversation or Conversation()
        if prompt is not None:
            active_conversation.add_user(prompt)

        steps: list[StepResult] = []
        tool_results: list[ToolResult] = []
        active_toolset = self.toolset if toolset is None else toolset
        active_system_prompt = self.system_prompt if system_prompt is None else system_prompt

        for _ in range(max_steps):
            result = await step(
                chat_provider=self.chat_provider,
                system_prompt=active_system_prompt,
                toolset=active_toolset,
                history=active_conversation.history,
                on_message_part=on_message_part,
            )
            steps.append(result)
            active_conversation.add(result.message)

            current_tool_results = await result.tool_results()
            tool_results.extend(current_tool_results)
            active_conversation.extend_tool_results(current_tool_results)

            if not result.tool_calls:
                return AgentRunResult(
                    conversation=active_conversation,
                    steps=tuple(steps),
                    message=result.message,
                    tool_results=tuple(tool_results),
                )

        raise MaxStepsReachedError(f"Agent loop reached max_steps={max_steps}")

    @staticmethod
    def _history_with_prompt(
        prompt: str | ContentPart | list[ContentPart] | None,
        history: Sequence[Message] | Conversation | None,
    ) -> list[Message]:
        if isinstance(history, Conversation):
            message_history = list(history.history)
        elif history is None:
            message_history = []
        else:
            message_history = list(history)

        if prompt is not None:
            message_history.append(Message(role="user", content=prompt))
        return message_history
