"""Pythinker renderer for Pythinker's ``Think`` tool."""

from __future__ import annotations

from rich.console import Group, RenderableType

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

_TOOL_NAME = "Think"
_DEFAULT_COLLAPSED_LINES = 6


def _render_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    thought = as_str(args.get("thought"))
    style_token = "error" if ctx.is_error else "success" if ctx.has_result else "muted"

    if thought is None:
        if "thought" in args:
            header = tool_call_header("Think", invalid_arg(), style_token=style_token)
        elif ctx.has_result:
            header = tool_call_header(
                "Think", missing_required_arg("thought"), style_token=style_token
            )
        else:
            header = tool_call_header("Think", fg("muted", "..."), style_token=style_token)
        return running_spinner(
            header, execution_started=ctx.execution_started, has_result=ctx.has_result
        )

    header = tool_call_header("Think", None, style_token=style_token)
    if not thought:
        return running_spinner(
            header, execution_started=ctx.execution_started, has_result=ctx.has_result
        )
    body, remaining = format_lines_block(
        thought,
        expanded=ctx.expanded,
        collapsed_max_lines=_DEFAULT_COLLAPSED_LINES,
        style_token="muted",
    )
    children: list[RenderableType] = [header, body]
    if remaining > 0:
        children.append(fg("muted", f"... ({remaining} more lines, ctrl+o to expand)"))
    rendered = Group(*children)
    return running_spinner(
        rendered, execution_started=ctx.execution_started, has_result=ctx.has_result
    )


def _render_result(_ctx: ToolRenderContext, _result: ToolResultPayload) -> RenderableType | None:
    return None


THINK_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="think",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
