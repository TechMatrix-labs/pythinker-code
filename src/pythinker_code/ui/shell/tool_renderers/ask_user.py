"""Pythinker renderer for Pythinker's ``AskUserQuestion`` tool."""

from __future__ import annotations

from typing import Any, cast

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

_TOOL_NAME = "AskUserQuestion"
_DEFAULT_COLLAPSED_LINES = 8


def _render_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    questions = args.get("questions")

    if not isinstance(questions, list) or not questions:
        summary = Text()
        if "questions" in args:
            summary.append_text(invalid_arg())
        elif ctx.has_result:
            summary.append_text(missing_required_arg("questions"))
        else:
            summary.append_text(fg("muted", "..."))
        header = tool_call_header(
            "Ask", summary, style_token="success" if ctx.has_result else "muted"
        )
        return running_spinner(
            header, execution_started=ctx.execution_started, has_result=ctx.has_result
        )

    questions_list = cast("list[Any]", questions)
    qs: list[dict[str, Any]] = [
        cast("dict[str, Any]", q) for q in questions_list if isinstance(q, dict)
    ]
    count_summary = f"{len(qs)} questions" if len(qs) != 1 else "1 question"
    header = tool_call_header(
        "Ask",
        fg("muted", count_summary),
        style_token="error" if ctx.is_error else "success" if ctx.has_result else "muted",
    )

    children: list[RenderableType] = [header]
    for q in qs[:2]:
        question_text = as_str(q.get("question")) or ""
        if question_text:
            children.append(fg("accent", f"? {question_text}"))
        opts = q.get("options")
        if isinstance(opts, list):
            opts_list = cast("list[Any]", opts)
            for opt in opts_list[:4]:
                if not isinstance(opt, dict):
                    continue
                opt_dict = cast("dict[str, Any]", opt)
                label = as_str(opt_dict.get("label")) or "?"
                children.append(fg("dim", f"  • {label}"))
    if len(qs) > 2:
        children.append(fg("muted", f"... +{len(qs) - 2} more"))
    rendered = Group(*children)
    return running_spinner(
        rendered, execution_started=ctx.execution_started, has_result=ctx.has_result
    )


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
        more = fg("muted", f"... ({remaining} more lines, ctrl+o to expand)")
        return Group(body, more)
    return body


ASK_USER_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="ask user",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
