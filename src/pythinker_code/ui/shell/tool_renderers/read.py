"""Pythinker renderer for Pythinker's ``ReadFile`` tool.

 .

Source tool name → Pythinker tool name: ``read`` → ``ReadFile``.
Param mapping: ``offset/limit`` → ``line_offset/n_lines``.
"""

from __future__ import annotations

from typing import Any

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
    running_spinner,
    shorten_path,
    tool_title,
)

_TOOL_NAME = "ReadFile"
_DEFAULT_COLLAPSED_LINES = 10


def _format_line_range(args: dict[str, Any]) -> Text | None:
    offset = args.get("line_offset")
    limit = args.get("n_lines")
    if offset in (None, 1) and limit is None:
        return None
    try:
        start = int(offset) if offset is not None else 1  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if limit is None:
        return fg("warning", f":{start}")
    try:
        end = start + int(limit) - 1  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fg("warning", f":{start}")
    return fg("warning", f":{start}-{end}")


def _render_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    raw_path = as_str(args.get("path"))
    title = tool_title("read")
    line = Text()
    line.append_text(title)
    line.append(" ")

    if raw_path is None:
        # Either missing (still streaming) or wrong type.
        if "path" in args:
            line.append_text(invalid_arg())
        else:
            line.append_text(fg("tool_output", "..."))
    else:
        line.append_text(fg("accent", shorten_path(raw_path, cwd=ctx.cwd)))

    range_text = _format_line_range(args)
    if range_text is not None:
        line.append_text(range_text)
    return running_spinner(line, execution_started=ctx.execution_started, has_result=ctx.has_result)


def _render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
    if not result.text:
        return None
    body, remaining = format_lines_block(
        result.text,
        expanded=ctx.expanded,
        collapsed_max_lines=_DEFAULT_COLLAPSED_LINES,
        style_token="error" if result.is_error else "tool_output",
    )
    if not body.plain:
        return None

    line_count = result.text.count("\n") + (0 if result.text.endswith("\n") else 1)
    noun = "line" if line_count == 1 else "lines"
    summary = fg("muted", f"Read {line_count} {noun}")
    if remaining > 0:
        more = fg("muted", f"... ({remaining} more lines, ctrl+e to expand)")
        return Group(summary, body, more)
    return Group(summary, body)


READ_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="read",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
