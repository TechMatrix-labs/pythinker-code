"""Pythinker renderer for the ``Agent`` (subagent) tool.

The Agent tool is single-spawn; this renderer covers the single variant
only (spawn, run, surface the final result).
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.style import Style as RichStyle
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
    loading_marker,
    running_spinner,
    tool_title,
)
from pythinker_code.ui.theme import tui_rich_style
from pythinker_code.utils.datetime import format_elapsed

_TOOL_NAME = "Agent"
_DEFAULT_COLLAPSED_LINES = 6
_PROMPT_PREVIEW_CHARS = 80
_BACKGROUND_ACTIVE_STATUSES = frozenset({"created", "starting", "running", "awaiting_approval"})


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _render_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    subagent_type = as_str(args.get("subagent_type")) or "coder"
    description = as_str(args.get("description"))
    prompt = as_str(args.get("prompt"))
    resume = as_str(args.get("resume"))
    run_bg = bool(args.get("run_in_background"))
    model = as_str(args.get("model"))

    header = Text()
    header.append_text(tool_title("subagent"))
    header.append(" ")
    header.append_text(fg("accent", subagent_type))
    if description:
        header.append_text(fg("muted", f" [{description}]"))
    if model:
        header.append_text(fg("dim", f" ({model})"))
    if run_bg:
        header.append_text(fg("muted", " (background)"))
    if resume:
        header.append_text(fg("muted", f" (resume {resume[:8]})"))

    # Active subagent affordance: a running subagent gets the shared solid
    # loading marker. Animated dots are reserved for the bottom thinking words.
    head = running_spinner(
        header,
        execution_started=ctx.execution_started,
        has_result=ctx.has_result,
    )

    if prompt is None:
        if "prompt" in args:
            return Group(head, invalid_arg())
        return head
    preview_line = _truncate(prompt.split("\n", 1)[0], _PROMPT_PREVIEW_CHARS)
    body = fg("dim", f"  {preview_line}")
    return Group(head, body)


def _line_value(text: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _background_status(text: str) -> str | None:
    kind = _line_value(text, "kind")
    status = _line_value(text, "status")
    if kind == "agent" and status in _BACKGROUND_ACTIVE_STATUSES:
        return status
    return None


def _render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
    if not result.text:
        return None
    background_status = None if result.is_error else _background_status(result.text)
    if background_status is not None:
        description = as_str(ctx.args.get("description"))
        label = "background subagent working"
        if description:
            label = f"{label}: {description}"
        line = loading_marker()
        line.append(label, style=tui_rich_style("muted"))
        return Group(line, fg("dim", f"  status: {background_status}"))
    # Distinct success symbol so the eye doesn't mistake a finished subagent
    # for a generic tool tick — heavy check on success, heavy ballot on error.
    icon = fg("error", "✘") if result.is_error else fg("success", "✔")
    body, remaining = format_lines_block(
        result.text,
        expanded=ctx.expanded,
        collapsed_max_lines=_DEFAULT_COLLAPSED_LINES,
        style_token="error" if result.is_error else "tool_output",
    )
    head = Text()
    head.append_text(icon)
    head.append(" ")
    head.append("subagent finished", style=tui_rich_style("muted") + RichStyle(bold=True))
    if ctx.elapsed_s is not None:
        head.append(
            f" · Crunched for {format_elapsed(ctx.elapsed_s)}", style=tui_rich_style("muted")
        )
    if not body.plain:
        return head
    if remaining > 0:
        more = fg("muted", f"... ({remaining} more lines, ctrl+e to expand)")
        return Group(head, body, more)
    return Group(head, body)


AGENT_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="subagent",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
