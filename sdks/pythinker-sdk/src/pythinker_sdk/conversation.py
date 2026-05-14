from __future__ import annotations

from collections.abc import Iterable

from pythinker_core.message import ContentPart, Message
from pythinker_core.tooling import ToolResult


def tool_result_to_message(result: ToolResult) -> Message:
    """Convert a tool result into a tool-role message for the next model step."""
    return Message(
        role="tool",
        tool_call_id=result.tool_call_id,
        content=result.return_value.output,
    )


class Conversation:
    """Small in-memory helper for building Pythinker message histories."""

    def __init__(self, messages: Iterable[Message] | None = None) -> None:
        self.history: list[Message] = list(messages or [])

    def add(self, message: Message) -> Message:
        """Append an existing message and return it."""
        self.history.append(message)
        return message

    def add_user(self, content: str | ContentPart | list[ContentPart]) -> Message:
        """Append a user message and return it."""
        return self.add(Message(role="user", content=content))

    def add_assistant(self, content: str | ContentPart | list[ContentPart]) -> Message:
        """Append an assistant message and return it."""
        return self.add(Message(role="assistant", content=content))

    def add_tool_result(self, result: ToolResult) -> Message:
        """Append a tool-result message and return it."""
        return self.add(tool_result_to_message(result))

    def extend_tool_results(self, results: Iterable[ToolResult]) -> list[Message]:
        """Append multiple tool-result messages in order and return them."""
        return [self.add_tool_result(result) for result in results]

    def last_text(self, sep: str = "") -> str:
        """Return extracted text from the most recent message, or an empty string."""
        if not self.history:
            return ""
        return self.history[-1].extract_text(sep=sep)
