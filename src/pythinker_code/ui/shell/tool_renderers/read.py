"""Blackbox-style renderer for Pythinker's ``ReadFile`` tool.

The reference UI shows a compact path/range in the tool-use row and a typed
summary result (``Read N lines``, ``File not found``, etc.) rather than echoing
the entire file body into the terminal transcript.
"""

from __future__ import annotations

import re
from typing import Any

from rich.console import RenderableType
from rich.text import Text

from pythinker_code.ui.shell.tool_renderers import (
    ToolRenderContext,
    ToolRenderDefinition,
    ToolResultPayload,
)
from pythinker_code.ui.shell.tool_renderers._render_utils import (
    as_str,
    fg,
    invalid_arg,
    missing_required_arg,
    running_spinner,
    shorten_path,
    tool_call_header,
)

_TOOL_NAME = "ReadFile"
_READ_COUNT_RE = re.compile(r"(\d+)\s+lines?\s+read", re.IGNORECASE)


def _format_line_range(args: dict[str, Any]) -> Text | None:
    offset = args.get("line_offset")
    limit = args.get("n_lines")
    if offset in (None, 1) and limit is None:
        return None
    try:
        start = int(offset) if offset is not None else 1  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    # A negative offset is tail mode (read the last N lines from EOF). A forward
    # ``start-end`` range is meaningless here, so show it as ``tail N`` instead
    # of the confusing ``:-100--81``.
    if start < 0:
        text = f":tail {abs(start)}"
        if isinstance(limit, int):
            text += f" · limit {limit}"
        return fg("warning", text)
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
    summary = Text()
    if raw_path is None:
        # Either missing (still streaming) or wrong type.
        if "path" in args:
            summary.append_text(invalid_arg())
        elif ctx.has_result:
            summary.append_text(missing_required_arg("path"))
        else:
            summary.append_text(fg("tool_output", "..."))
    else:
        summary.append_text(fg("accent", shorten_path(raw_path, cwd=ctx.cwd)))

    range_text = _format_line_range(args)
    if range_text is not None:
        summary.append_text(range_text)
    style_token = "error" if ctx.is_error else "success" if ctx.has_result else "muted"
    line = tool_call_header("Read", summary, style_token=style_token)
    return running_spinner(line, execution_started=ctx.execution_started, has_result=ctx.has_result)


def _read_count(result: ToolResultPayload) -> int:
    message = result.details.get("message")
    if isinstance(message, str):
        match = _READ_COUNT_RE.search(message)
        if match:
            return int(match.group(1))
    output = result.details.get("output")
    text = output if isinstance(output, str) else result.text
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _friendly_error(text: str) -> str:
    lowered = text.lower()
    if "does not exist" in lowered or "file not found" in lowered:
        return "File not found"
    if "not a file" in lowered or "invalid path" in lowered:
        return "Invalid path"
    if "sensitive" in lowered:
        return "Sensitive file"
    if text.strip():
        return text.rstrip("\n")
    return "Error reading file"


def _render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
    ctx.state["__suppress_generic_expand_hint__"] = True
    if result.is_error:
        message = result.details.get("message")
        error_text = message if isinstance(message, str) and message else result.text
        return fg("error", _friendly_error(error_text))

    message = result.details.get("message")
    if isinstance(message, str) and message.startswith("Directory listing for `"):
        return fg("tool_output", "Listed directory")

    line_count = _read_count(result)
    noun = "line" if line_count == 1 else "lines"
    return fg("tool_output", f"Read {line_count} {noun}")


READ_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="read",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
