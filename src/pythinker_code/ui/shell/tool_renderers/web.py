"""Pythinker renderers for Pythinker's ``FetchURL`` and ``SearchWeb`` tools."""

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
    tool_title,
)


def _shorten_url(url: str, *, max_chars: int = 60) -> str:
    if len(url) <= max_chars:
        return url
    return url[: max_chars - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# FetchURL
# ---------------------------------------------------------------------------


def _render_fetch_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    url = as_str(args.get("url"))
    line = Text()
    line.append_text(tool_title("fetch"))
    line.append(" ")
    if url is None:
        line.append_text(invalid_arg() if "url" in args else fg("muted", "..."))
    else:
        line.append_text(fg("accent", _shorten_url(url)))
    return running_spinner(line, execution_started=ctx.execution_started, has_result=ctx.has_result)


def _render_fetch_result(
    ctx: ToolRenderContext, result: ToolResultPayload
) -> RenderableType | None:
    if not result.text:
        return None
    body, remaining = format_lines_block(
        result.text,
        expanded=ctx.expanded,
        collapsed_max_lines=15,
        style_token="error" if result.is_error else "tool_output",
    )
    if not body.plain:
        return None
    if remaining > 0:
        more = fg("muted", f"... ({remaining} more lines, ctrl+e to expand)")
        return Group(body, more)
    return body


FETCH_RENDERER = ToolRenderDefinition(
    name="FetchURL",
    label="fetch",
    render_shell="default",
    render_call=_render_fetch_call,
    render_result=_render_fetch_result,
)


# ---------------------------------------------------------------------------
# SearchWeb
# ---------------------------------------------------------------------------


def _render_search_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    query = as_str(args.get("query"))
    limit = args.get("limit")
    include_content = bool(args.get("include_content"))

    line = Text()
    line.append_text(tool_title("search"))
    line.append(" ")
    if query is None:
        line.append_text(invalid_arg() if "query" in args else fg("muted", "..."))
    else:
        line.append_text(fg("accent", f'"{query}"'))
    extras: list[str] = []
    if isinstance(limit, int) and limit != 5:
        extras.append(f"limit {limit}")
    if include_content:
        extras.append("with content")
    for extra in extras:
        line.append_text(fg("muted", f" ({extra})"))
    return running_spinner(line, execution_started=ctx.execution_started, has_result=ctx.has_result)


def _render_search_result(
    ctx: ToolRenderContext, result: ToolResultPayload
) -> RenderableType | None:
    if not result.text:
        return None
    body, remaining = format_lines_block(
        result.text,
        expanded=ctx.expanded,
        collapsed_max_lines=15,
        style_token="error" if result.is_error else "tool_output",
    )
    if not body.plain:
        return None
    if remaining > 0:
        more = fg("muted", f"... ({remaining} more lines, ctrl+e to expand)")
        return Group(body, more)
    return body


SEARCH_RENDERER = ToolRenderDefinition(
    name="SearchWeb",
    label="search",
    render_shell="default",
    render_call=_render_search_call,
    render_result=_render_search_result,
)
