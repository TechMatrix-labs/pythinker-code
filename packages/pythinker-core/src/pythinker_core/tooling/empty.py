from typing import TYPE_CHECKING

from pythinker_core.message import ToolCall
from pythinker_core.tooling import HandleResult, Tool, ToolResult, Toolset
from pythinker_core.tooling.error import ToolNotFoundError

if TYPE_CHECKING:

    def type_check(empty: "EmptyToolset"):
        _: Toolset = empty


class EmptyToolset:
    """A toolset implementation that always contains no tools."""

    @property
    def tools(self) -> list[Tool]:
        return []

    def handle(self, tool_call: ToolCall) -> HandleResult:
        return ToolResult(
            tool_call_id=tool_call.id,
            return_value=ToolNotFoundError(tool_call.function.name),
        )
