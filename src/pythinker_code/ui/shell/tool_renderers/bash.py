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
from rich.text import Text

from pythinker_code.ui.shell.components.bash_execution import (
    BashExecutionState,
    BashStatus,
    format_bash_command_for_header,
    render_bash_result_output,
)
from pythinker_code.ui.shell.components.render_utils import sanitize_ansi
from pythinker_code.ui.shell.tool_renderers import (
    ToolRenderContext,
    ToolRenderDefinition,
    ToolResultPayload,
)
from pythinker_code.ui.shell.tool_renderers._render_utils import (
    as_str,
    fg,
    invalid_arg,
    missing_required_arg,
    pending_tool_call_header,
    running_spinner,
    tool_call_header,
)

_TOOL_NAME = "Shell"


def _render_call(ctx: ToolRenderContext) -> RenderableType | None:
    """Render the stable shell tool header before any output rows."""
    args = ctx.args or {}
    command = as_str(args.get("command"))
    timeout = args.get("timeout")
    run_in_background = bool(args.get("run_in_background"))

    summary = Text()
    if command is None:
        if "command" in args:
            summary.append_text(invalid_arg())
        elif ctx.has_result:
            summary.append_text(missing_required_arg("command"))
        else:
            line = pending_tool_call_header("Bash")
            return running_spinner(
                line, execution_started=ctx.execution_started, has_result=ctx.has_result
            )
    else:
        summary.append_text(
            fg("tool_output", format_bash_command_for_header(command, expanded=ctx.expanded))
        )

    if isinstance(timeout, int) and timeout != 60:
        summary.append_text(fg("muted", f" (timeout {timeout}s)"))
    if run_in_background:
        description = as_str(args.get("description"))
        suffix = f" (background: {description})" if description else " (background)"
        summary.append_text(fg("muted", suffix))
    style_token = (
        "error" if ctx.is_error else "success" if ctx.has_result and not ctx.is_partial else "muted"
    )
    line = tool_call_header("Bash", summary, style_token=style_token)
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

    extras_raw = result.details.get("extras")
    extras = cast("dict[str, object]", extras_raw) if isinstance(extras_raw, dict) else {}
    status_value = extras.get("status")
    status: BashStatus
    if ctx.is_partial or status_value == "running":
        status = "running"
    elif status_value == "cancelled":
        status = "cancelled"
    else:
        status = "error" if result.is_error else "complete"

    output = result.details.get("output")
    output_text = output if isinstance(output, str) and output else result.text or ""
    if output_text.count("\n") > 4 or len(output_text) > 240:
        ctx.state["__suppress_generic_expand_hint__"] = True

    exit_code_raw = extras.get("exit_code")
    exit_code = exit_code_raw if status == "error" and isinstance(exit_code_raw, int) else None

    bash_state = BashExecutionState(
        command=command,
        output=sanitize_ansi(output_text),
        status=status,
        exit_code=exit_code,
        expanded=ctx.expanded,
        header_suffix="".join(suffix_parts),
    )
    return render_bash_result_output(bash_state, width=ctx.width)


SHELL_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="bash",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
