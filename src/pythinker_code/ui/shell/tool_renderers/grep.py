"""Pythinker renderer for Pythinker's ``Grep`` tool.

 .

Param differences:

* ``limit`` → ``head_limit`` (Pythinker default 250 vs Pythinker's 100).
* Pythinker has ``output_mode`` (files_with_matches | content | count_matches).
* Pythinker uses ``-i`` alias for ``ignore_case``.
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

_TOOL_NAME = "Grep"
_DEFAULT_COLLAPSED_LINES = 15


def _render_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    pattern = as_str(args.get("pattern"))
    raw_path = as_str(args.get("path"))
    glob = as_str(args.get("glob"))
    head_limit = args.get("head_limit")
    output_mode = as_str(args.get("output_mode"))

    line = Text()
    line.append_text(tool_title("grep"))
    line.append(" ")

    if pattern is None:
        if "pattern" in args:
            line.append_text(invalid_arg())
        else:
            line.append_text(fg("tool_output", "..."))
    else:
        line.append_text(fg("accent", f"/{pattern}/"))

    path_display = shorten_path(raw_path or ".", cwd=ctx.cwd) if raw_path is not None else None
    line.append_text(fg("tool_output", " in "))
    if "path" in args and raw_path is None:
        line.append_text(invalid_arg())
    else:
        line.append_text(fg("tool_output", path_display or "."))

    extras: list[str] = []
    if glob:
        extras.append(f"({glob})")
    if output_mode and output_mode != "files_with_matches":
        extras.append(output_mode)
    if isinstance(head_limit, int) and head_limit not in (0, 250):
        extras.append(f"limit {head_limit}")
    for extra in extras:
        line.append_text(fg("tool_output", f" {extra}"))
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


GREP_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="grep",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
