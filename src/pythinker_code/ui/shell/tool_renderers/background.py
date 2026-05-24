"""Pythinker renderers for Pythinker's background-task tools.

Covers ``TaskList``, ``TaskOutput``, and ``TaskStop``.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from pythinker_code.ui.shell.tool_renderers import (
    ToolRenderContext,
    ToolRenderDefinition,
    ToolResultPayload,
)
from pythinker_code.ui.shell.tool_renderers._render_utils import (
    as_str,
    fg,
    format_lines_block,
    invalid_arg,
    missing_required_arg,
    running_spinner,
    tool_call_header,
)


def _render_call_with_id(
    label: str, ctx: ToolRenderContext, *, extras: list[str]
) -> RenderableType:
    args = ctx.args or {}
    task_id = as_str(args.get("task_id"))
    summary = Text()
    if task_id is None:
        if "task_id" in args:
            summary.append_text(invalid_arg())
        elif ctx.has_result:
            summary.append_text(missing_required_arg("task_id"))
        else:
            summary.append_text(fg("muted", "..."))
    else:
        summary.append_text(fg("accent", task_id))
    for extra in extras:
        summary.append_text(fg("muted", f" · {extra}"))
    style_token = "error" if ctx.is_error else "success" if ctx.has_result else "muted"
    line = tool_call_header(label, summary, style_token=style_token)
    return running_spinner(
        line,
        execution_started=ctx.execution_started,
        has_result=ctx.has_result,
    )


def _render_block_result(
    ctx: ToolRenderContext,
    result: ToolResultPayload,
    *,
    collapsed_lines: int = 12,
) -> RenderableType | None:
    if not result.text:
        return None
    body, remaining = format_lines_block(
        result.text,
        expanded=ctx.expanded,
        collapsed_max_lines=collapsed_lines,
        style_token="error" if result.is_error else "tool_output",
    )
    if not body.plain:
        return None
    if remaining > 0:
        return Group(body, fg("muted", f"... ({remaining} more lines, ctrl+o to expand)"))
    return body


# ---------------------------------------------------------------------------
# TaskList
# ---------------------------------------------------------------------------


def _render_task_list_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    active_only = bool(args.get("active_only", True))
    limit = args.get("limit")
    summary = Text("active" if active_only else "all")
    if isinstance(limit, int) and limit != 20:
        summary.append_text(fg("muted", f" · limit {limit}"))
    style_token = "error" if ctx.is_error else "success" if ctx.has_result else "muted"
    line = tool_call_header("Tasks", summary, style_token=style_token)
    return running_spinner(line, execution_started=ctx.execution_started, has_result=ctx.has_result)


TASK_LIST_RENDERER = ToolRenderDefinition(
    name="TaskList",
    label="tasks",
    render_shell="default",
    render_call=_render_task_list_call,
    render_result=_render_block_result,
)


# ---------------------------------------------------------------------------
# TaskOutput
# ---------------------------------------------------------------------------


def _render_task_output_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    extras: list[str] = []
    if args.get("block"):
        timeout = args.get("timeout")
        extras.append(
            f"block, timeout {timeout}s" if isinstance(timeout, int) and timeout != 30 else "block"
        )
    return _render_call_with_id("TaskOutput", ctx, extras=extras)


TASK_OUTPUT_RENDERER = ToolRenderDefinition(
    name="TaskOutput",
    label="task output",
    render_shell="default",
    render_call=_render_task_output_call,
    render_result=lambda ctx, r: _render_block_result(ctx, r, collapsed_lines=20),
)


# ---------------------------------------------------------------------------
# TaskStop
# ---------------------------------------------------------------------------


def _render_task_stop_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    extras: list[str] = []
    reason = as_str(args.get("reason"))
    if reason and reason != "Stopped by TaskStop":
        extras.append(reason)
    return _render_call_with_id("TaskStop", ctx, extras=extras)


TASK_STOP_RENDERER = ToolRenderDefinition(
    name="TaskStop",
    label="task stop",
    render_shell="default",
    render_call=_render_task_stop_call,
    render_result=_render_block_result,
)
