"""Pythinker renderer for the ``Agent`` (subagent) tool."""

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
    missing_required_arg,
    running_spinner,
    tool_call_header,
)
from pythinker_code.ui.theme import tui_rich_style
from pythinker_code.utils.datetime import format_elapsed

_TOOL_NAME = "Agent"
_DEFAULT_COLLAPSED_LINES = 6
_PROMPT_PREVIEW_CHARS = 80
_BACKGROUND_ACTIVE_STATUSES = frozenset({"created", "starting", "running", "awaiting_approval"})


def _subagent_loader(_ctx: ToolRenderContext) -> Text:
    """Return the pulsating solid-circle loader used for active subagent result rows."""
    return loading_marker(style_token="accent")


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

    secondary_token = "thinking_text"
    summary = Text()
    summary.append_text(fg("border_accent", subagent_type))
    if description:
        summary.append_text(fg(secondary_token, f" · {description}"))
    if model:
        summary.append_text(fg("dim", f" · {model}"))
    if run_bg:
        summary.append_text(fg(secondary_token, " · background"))
    if resume:
        summary.append_text(fg(secondary_token, f" · resume {resume[:8]}"))

    style_token = "error" if ctx.is_error else "success" if ctx.has_result else secondary_token
    header = tool_call_header(
        "Agent", summary, style_token=style_token, paren_style_token=secondary_token
    )

    missing: list[RenderableType] = []
    if description is None and ctx.has_result:
        missing.append(missing_required_arg("description"))
    if prompt is None:
        if "prompt" in args:
            missing.append(invalid_arg())
        elif ctx.has_result:
            missing.append(missing_required_arg("prompt"))
        rendered = Group(header, *missing) if missing else header
        return running_spinner(
            rendered,
            execution_started=ctx.execution_started,
            has_result=ctx.has_result,
            marker_style_token=secondary_token,
        )

    preview_line = _truncate(prompt.split("\n", 1)[0], _PROMPT_PREVIEW_CHARS)
    body = Text()
    body.append("Prompt: ", style=tui_rich_style(secondary_token) + RichStyle(bold=True))
    body.append(preview_line, style=tui_rich_style(secondary_token))
    rendered = Group(header, *missing, body) if missing else Group(header, body)
    return running_spinner(
        rendered,
        execution_started=ctx.execution_started,
        has_result=ctx.has_result,
        marker_style_token=secondary_token,
    )


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
        line = _subagent_loader(ctx)
        line.append(label, style=tui_rich_style("accent") + RichStyle(bold=True))
        return Group(line, fg("dim", f"status: {background_status}"))

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
    head.append("Agent finished", style=tui_rich_style("thinking_text") + RichStyle(bold=True))
    if ctx.elapsed_s is not None:
        head.append(
            f" · Crunched for {format_elapsed(ctx.elapsed_s)}",
            style=tui_rich_style("thinking_text"),
        )
    if not body.plain:
        return head
    if remaining > 0:
        more = fg("muted", f"... ({remaining} more lines, ctrl+o to expand)")
        return Group(head, body, more)
    return Group(head, body)


AGENT_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="subagent",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
