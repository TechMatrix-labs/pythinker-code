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

from rich.console import RenderableType
from rich.style import Style as RichStyle
from rich.text import Text

from pythinker_code.ui.shell.components.bash_execution import (
    BashExecutionState,
    BashStatus,
    format_bash_command_for_header,
    render_bash_result_output,
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
    """Render the stable shell tool header before any output rows."""
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
        line.append(
            format_bash_command_for_header(command, expanded=ctx.expanded),
            style=bash_mode + RichStyle(bold=True),
        )

    if isinstance(timeout, int) and timeout != 60:
        line.append_text(fg("muted", f" (timeout {timeout}s)"))
    if run_in_background:
        description = as_str(args.get("description"))
        suffix = f" (background: {description})" if description else " (background)"
        line.append_text(fg("muted", suffix))
    return running_spinner(line, execution_started=ctx.execution_started, has_result=ctx.has_result)


def _render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
    """Render shell output/status under the shared response gutter."""
    args = ctx.args or {}
    command = as_str(args.get("command")) or ""
    if not command:
        return None

    suffix_parts: list[str] = []
    timeout = args.get("timeout")
    if isinstance(timeout, int) and timeout != 60:
        suffix_parts.append(f" (timeout {timeout}s)")
    if bool(args.get("run_in_background")):
        description = as_str(args.get("description"))
        suffix_parts.append(f" (background: {description})" if description else " (background)")

    status: BashStatus = "error" if result.is_error else "complete"
    bash_state = BashExecutionState(
        command=command,
        output=result.text or "",
        status=status,
        exit_code=None if not result.is_error else 1,
        expanded=ctx.expanded,
        header_suffix="".join(suffix_parts),
    )
    return render_bash_result_output(bash_state, width=ctx.width)


SHELL_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="bash",
    render_shell="self",
    render_call=_render_call,
    render_result=_render_result,
)
