"""Pythinker renderer for Pythinker's ``Shell`` tool.

  but
delegates the actual visual treatment to the bordered
:func:`render_bash_execution` component for completed results, giving the
shell tool the same look as Pythinker's interactive shell mode.

Source tool name → Pythinker tool name: ``bash`` → ``Shell``.
Param mapping: Pythinker has ``command``, ``timeout``, ``run_in_background``,
``description``; Pythinker has ``command``, ``timeout`` only.
"""

from __future__ import annotations

from typing import cast

from rich.console import RenderableType
from rich.style import Style as RichStyle
from rich.text import Text

from pythinker_code.ui.shell.components.bash_execution import (
    BashExecutionState,
    BashStatus,
    render_bash_execution,
)
from pythinker_code.ui.shell.tool_renderers import (
    ToolRenderContext,
    ToolRenderDefinition,
    ToolResultPayload,
)
from pythinker_code.ui.shell.tool_renderers._render_utils import (
    as_str,
    fg,
    invalid_arg,
    running_spinner,
)
from pythinker_code.ui.theme import tui_rich_style

_TOOL_NAME = "Shell"


def _render_call(ctx: ToolRenderContext) -> RenderableType | None:
    """Header for the call.

    When the result is already in hand we suppress the header — the
    bordered :func:`render_bash_execution` block produced by
    :func:`_render_result` already contains the ``$ <command>`` line and
    a free-floating header above it would look like a duplicate.
    """
    if ctx.state.get("__bash_use_bordered__"):
        return None

    args = ctx.args or {}
    command = as_str(args.get("command"))
    timeout = args.get("timeout")
    run_in_background = bool(args.get("run_in_background"))

    bash_mode = tui_rich_style("bash_mode")
    line = Text("$ ", style=bash_mode + RichStyle(bold=True))
    if command is None:
        if "command" in args:
            line.append_text(invalid_arg())
        else:
            line.append_text(fg("tool_output", "..."))
    else:
        line.append(command, style=bash_mode + RichStyle(bold=True))

    if isinstance(timeout, int) and timeout != 60:
        line.append_text(fg("muted", f" (timeout {timeout}s)"))
    if run_in_background:
        description = as_str(args.get("description"))
        suffix = f" (background: {description})" if description else " (background)"
        line.append_text(fg("muted", suffix))
    return running_spinner(line, execution_started=ctx.execution_started, has_result=ctx.has_result)


def _render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
    """Render a Pythinker bordered shell card with output, status, exit code."""
    args = ctx.args or {}
    command = as_str(args.get("command")) or ""
    if not command:
        return None
    # Mark for the call renderer so it skips the duplicate header.
    state = cast("dict[str, object]", ctx.state)
    state["__bash_use_bordered__"] = True

    status: BashStatus = "error" if result.is_error else "complete"
    bash_state = BashExecutionState(
        command=command,
        output=result.text or "",
        status=status,
        exit_code=None if not result.is_error else 1,
        expanded=ctx.expanded,
    )
    return render_bash_execution(bash_state)


SHELL_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="bash",
    render_shell="self",
    render_call=_render_call,
    render_result=_render_result,
)
