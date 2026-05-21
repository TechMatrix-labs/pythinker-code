"""Pythinker tool execution card.

Wraps a registered :class:`ToolRenderDefinition` and renders it as a card
with a status-tinted background. Mirrors

in the  codebase.

The card lifecycle:

* arguments stream in        → status = ``PENDING``,  bg = ``tool_pending_bg``
* execution starts           → status = ``RUNNING``,  bg = ``tool_pending_bg``
* result arrives, no error   → status = ``SUCCESS``,  bg = ``tool_success_bg``
* result arrives, error      → status = ``ERROR``,    bg = ``tool_error_bg``
* user cancels / denies      → status = ``CANCELLED`` / ``DENIED``

If the renderer produces no visible output for the current state, the
component renders an empty string (the ``hidden-component`` behavior).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.style import Style
from rich.text import Text

from pythinker_code.ui.shell.components.key_hints import key_hint
from pythinker_code.ui.shell.tool_renderers import (
    ToolRenderContext,
    ToolRenderDefinition,
    ToolResultPayload,
)
from pythinker_code.ui.theme import tui_rich_style


class ToolExecutionStatus(Enum):
    """Lifecycle states of a tool call card."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    CANCELLED = "cancelled"


_PENDING_LIKE = frozenset({ToolExecutionStatus.PENDING, ToolExecutionStatus.RUNNING})


@dataclass(slots=True)
class _CallState:
    """Snapshot of the inputs the component needs to compose a render."""

    tool_name: str
    tool_call_id: str
    cwd: str = ""
    args: dict[str, Any] | None = None
    args_complete: bool = False
    execution_started: bool = False
    expanded: bool = False
    result: ToolResultPayload | None = None
    is_partial: bool = False


class ToolExecutionComponent:
    """Single tool invocation rendered as a Pythinker card."""

    def __init__(
        self,
        tool_name: str,
        tool_call_id: str,
        *,
        definition: ToolRenderDefinition,
        cwd: str = "",
    ) -> None:
        self._definition = definition
        self._state = _CallState(tool_name=tool_name, tool_call_id=tool_call_id, cwd=cwd)
        self._renderer_state: dict[str, Any] = {"__tool_name__": tool_name}
        self._status = ToolExecutionStatus.PENDING

    # -- Mutators ------------------------------------------------------------

    def update_args(self, args: dict[str, Any]) -> None:
        self._state.args = args

    def set_args_complete(self) -> None:
        self._state.args_complete = True

    def mark_execution_started(self) -> None:
        self._state.execution_started = True
        if self._status == ToolExecutionStatus.PENDING:
            self._status = ToolExecutionStatus.RUNNING

    def set_result(
        self,
        result: ToolResultPayload,
        *,
        is_partial: bool = False,
    ) -> None:
        self._state.result = result
        self._state.is_partial = is_partial
        if is_partial:
            self._status = ToolExecutionStatus.RUNNING
        else:
            self._status = (
                ToolExecutionStatus.ERROR if result.is_error else ToolExecutionStatus.SUCCESS
            )

    def set_status(self, status: ToolExecutionStatus) -> None:
        """Force a specific status (e.g. DENIED, CANCELLED)."""
        self._status = status

    def set_expanded(self, expanded: bool) -> None:
        self._state.expanded = expanded

    @property
    def status(self) -> ToolExecutionStatus:
        return self._status

    @property
    def expanded(self) -> bool:
        return self._state.expanded

    @property
    def tool_call_id(self) -> str:
        return self._state.tool_call_id

    def invalidate(self) -> None:  # pragma: no cover — protocol stub
        """Drop cached output. Currently a no-op (no caching layer yet)."""

    # -- Rendering -----------------------------------------------------------

    def render(self, width: int = 0) -> RenderableType:  # noqa: ARG002 — width reserved
        """Return the card renderable for the current state.

        *width* is accepted for protocol compatibility; Rich console width
        is the source of truth at print time.
        """
        ctx = self._build_context()
        children: list[RenderableType] = []

        if self._definition.render_call is not None:
            try:
                call = self._definition.render_call(ctx)
            except Exception:  # noqa: BLE001 — renderer crash falls back to header
                call = self._call_fallback()
            if call is not None:
                children.append(call)
        else:
            children.append(self._call_fallback())

        result = self._state.result
        if result is not None and self._definition.render_result is not None:
            try:
                rendered_result = self._definition.render_result(ctx, result)
            except Exception:  # noqa: BLE001
                rendered_result = self._result_fallback()
            if rendered_result is not None:
                children.append(rendered_result)
        elif result is not None:
            fallback = self._result_fallback()
            if fallback is not None:
                children.append(fallback)

        if not self._state.expanded and self._is_truncatable():
            children.append(key_hint("Ctrl+E", "expand"))

        if not children:
            return Text("")

        if len(children) <= 1:
            body: RenderableType = children[0] if children else Text("")
        else:
            # Insert blank line between call header (children[0]) and result/hints.
            body = Group(children[0], Text(""), *children[1:])

        if self._definition.render_shell == "self":
            return body

        bg_style = self._background_style()
        # Padding with style fills the padded area with the tint, giving the
        # "content box" feel without an extra border character.
        return Padding(body, (1, 1), style=bg_style)

    # -- Internals -----------------------------------------------------------

    def _build_context(self) -> ToolRenderContext:
        return ToolRenderContext(
            args=self._state.args or {},
            tool_call_id=self._state.tool_call_id,
            cwd=self._state.cwd,
            execution_started=self._state.execution_started,
            args_complete=self._state.args_complete,
            is_partial=self._state.is_partial,
            has_result=self._state.result is not None,
            expanded=self._state.expanded,
            is_error=self._state.result.is_error if self._state.result else False,
            state=self._renderer_state,
        )

    def _background_style(self) -> Style:
        if self._status == ToolExecutionStatus.ERROR or self._status == ToolExecutionStatus.DENIED:
            token = "tool_error_bg"
        elif self._status == ToolExecutionStatus.SUCCESS:
            token = "tool_success_bg"
        elif self._status in _PENDING_LIKE:
            token = "tool_pending_bg"
        else:
            token = "tool_pending_bg"
        return tui_rich_style(token)

    def _call_fallback(self) -> RenderableType:
        return Text(self._definition.label or self._state.tool_name, style="bold")

    def _result_fallback(self) -> RenderableType | None:
        result = self._state.result
        if result is None or not result.text:
            return None
        style = "red" if result.is_error else "grey70"
        return Text(result.text, style=style)

    def _is_truncatable(self) -> bool:
        """Heuristic: only show the expand hint when there's likely more to see."""
        result = self._state.result
        if result is None or not result.text:
            return False
        text = result.text
        return len(text) > 240 or text.count("\n") > 4
