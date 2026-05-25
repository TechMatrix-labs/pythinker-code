"""Generic fallback renderer used when no tool-specific renderer is registered.

Mirrors the ``formatToolExecution`` shape: tool name in the header, args
as a JSON blob, and the textual result below.
"""

from __future__ import annotations

import json

from rich.console import Group, RenderableType
from rich.text import Text

from pythinker_code.ui.shell.components.render_utils import sanitize_ansi
from pythinker_code.ui.shell.render_constants import expand_hint
from pythinker_code.ui.shell.tool_renderers import (
    ToolRenderContext,
    ToolRenderDefinition,
    ToolResultPayload,
)
from pythinker_code.ui.shell.tool_renderers._render_utils import (
    fg,
    format_lines_block,
    running_spinner,
    tool_call_header,
)
from pythinker_code.ui.theme import tui_rich_style

_GENERIC_TOOL_NAME = "__generic__"
"""Sentinel name used to register the fallback. Tools without their own
entry can be looked up via ``get_tool_renderer(name) or _generic()``."""

# Cap unregistered-tool output (e.g. a large Skill payload) so a huge result
# can't flood scrollback or overlap the live spinner; ctrl+o reveals the rest.
_GENERIC_COLLAPSED_LINES = 15


def _render_call(ctx: ToolRenderContext) -> RenderableType | None:
    label = str(ctx.state.get("__tool_name__", _GENERIC_TOOL_NAME))
    style_token = "error" if ctx.is_error else "success" if ctx.has_result else "muted"
    header = tool_call_header(label, None, style_token=style_token)

    if not ctx.args:
        return running_spinner(
            header, execution_started=ctx.execution_started, has_result=ctx.has_result
        )

    try:
        body = json.dumps(ctx.args, indent=2, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        body = repr(ctx.args)
    rendered = Group(header, Text(body, style=tui_rich_style("muted")))
    return running_spinner(
        rendered, execution_started=ctx.execution_started, has_result=ctx.has_result
    )


def _render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
    text = sanitize_ansi(result.text or "").rstrip("\n")
    if not text:
        return None
    style_token = "error" if result.is_error else "tool_output"
    body, remaining = format_lines_block(
        text,
        expanded=ctx.expanded,
        collapsed_max_lines=_GENERIC_COLLAPSED_LINES,
        style_token=style_token,
    )
    if remaining > 0:
        # We render our own count-aware hint, so suppress the duplicate generic one.
        ctx.state["__suppress_generic_expand_hint__"] = True
        return Group(body, fg("muted", expand_hint(remaining)))
    return body


GENERIC_RENDERER = ToolRenderDefinition(
    name=_GENERIC_TOOL_NAME,
    label="Tool",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)


def generic_renderer() -> ToolRenderDefinition:
    """Return the generic fallback renderer instance."""
    return GENERIC_RENDERER
