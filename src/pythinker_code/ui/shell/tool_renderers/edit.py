"""Pythinker renderer for Pythinker's ``StrReplaceFile`` tool.

 .

Source tool name → Pythinker tool name: ``edit`` → ``StrReplaceFile``.
Param shape: Pythinker uses ``edit: Edit | list[Edit]`` where each ``Edit``
has ``{old, new, replace_all}``.

Pythinker's tool produces the diff out-of-band (via display
blocks), so the renderer reconstructs it from the call args at render time.
That means the diff appears as soon as the streaming args are complete and
remains visible after execution.
"""

from __future__ import annotations

from typing import Any, cast

from rich.console import Group, RenderableType
from rich.text import Text

from pythinker_code.ui.shell.components import (
    compute_edit_diff_string,
    render_diff,
)
from pythinker_code.ui.shell.tool_renderers import (
    ToolRenderContext,
    ToolRenderDefinition,
    ToolResultPayload,
)
from pythinker_code.ui.shell.tool_renderers._render_utils import (
    as_str,
    fg,
    invalid_arg,
    running_spinner,
    shorten_path,
    tool_title,
)

_TOOL_NAME = "StrReplaceFile"


def _normalize_edits(edit_arg: Any) -> list[dict[str, Any]]:
    """Coerce ``args["edit"]`` into a list of dicts, ignoring junk."""
    if edit_arg is None:
        return []
    items: list[Any] = cast("list[Any]", edit_arg) if isinstance(edit_arg, list) else [edit_arg]
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(cast("dict[str, Any]", item))
    return out


def _build_combined_diff(edits: list[dict[str, Any]]) -> str:
    """Render each edit's (old → new) as a Pythinker-format diff block, joined.

    For multi-edit calls we render them sequentially with a blank separator.
    Each block is line-numbered relative to its own ``old`` text — we don't
    have the file content here, so absolute line numbers aren't possible.
    """
    blocks: list[str] = []
    for edit in edits:
        old = edit.get("old")
        new = edit.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            continue
        result = compute_edit_diff_string(old, new)
        if result.diff:
            blocks.append(result.diff)
    return "\n\n".join(blocks)


def _render_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    raw_path = as_str(args.get("path"))

    header = Text()
    header.append_text(tool_title("edit"))
    header.append(" ")

    if raw_path is None:
        header.append_text(invalid_arg() if "path" in args else fg("tool_output", "..."))
    else:
        header.append_text(fg("accent", shorten_path(raw_path, cwd=ctx.cwd)))

    edits = _normalize_edits(args.get("edit"))
    if not edits:
        return running_spinner(header, execution_started=ctx.execution_started, has_result=ctx.has_result)

    if len(edits) > 1:
        header.append_text(fg("tool_output", f" ({len(edits)} edits)"))

    head = running_spinner(header, execution_started=ctx.execution_started, has_result=ctx.has_result)

    diff_text = _build_combined_diff(edits)
    if not diff_text:
        return head
    diff_renderable = render_diff(diff_text)
    return Group(head, Text(""), diff_renderable)


def _render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
    # Errors: surface the message; success: nothing — the call preview
    # already shows the diff and the card background turns green.
    if not result.is_error:
        return None
    if not result.text:
        return None
    return fg("error", result.text.rstrip("\n"))


EDIT_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="edit",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
