"""Pythinker renderer for Pythinker's ``Glob`` tool.

 .

Source tool name → Pythinker tool name: ``find`` → ``Glob``.
Param mapping: ``path`` → ``directory``; ``limit`` is not exposed in Pythinker.
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
    running_spinner,
    shorten_path,
    tool_title,
)

_TOOL_NAME = "Glob"
_DEFAULT_COLLAPSED_LINES = 20


def _render_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    pattern = as_str(args.get("pattern"))
    raw_dir = as_str(args.get("directory"))

    line = Text()
    line.append_text(tool_title("find"))
    line.append(" ")

    if pattern is None:
        line.append_text(invalid_arg() if "pattern" in args else fg("tool_output", "..."))
    else:
        line.append_text(fg("accent", pattern))

    line.append_text(fg("tool_output", " in "))
    if "directory" in args and raw_dir is None:
        line.append_text(invalid_arg())
    else:
        line.append_text(fg("tool_output", shorten_path(raw_dir or ".", cwd=ctx.cwd)))

    if args.get("include_dirs") is False:
        line.append_text(fg("tool_output", " (files only)"))
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
    if remaining > 0:
        more = fg("muted", f"... ({remaining} more lines, ctrl+e to expand)")
        return Group(body, more)
    return body


FIND_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="find",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
