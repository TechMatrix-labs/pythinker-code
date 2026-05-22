"""Pythinker renderer for Pythinker's ``SetTodoList`` tool.

Renders the todo list with aligned status icons:

* ``○`` pending
* ``◐`` in_progress (highlighted)
* ``●`` done (success)
"""

from __future__ import annotations

from typing import Any, cast

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.table import Table
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
    tool_title,
)

_TOOL_NAME = "SetTodoList"
_DEFAULT_COLLAPSED_LINES = 12

_ICONS = {
    "pending": "○",
    "in_progress": "◐",
    "done": "●",
}

_TREE_BRANCH = "├─"
_TREE_LAST = "└─"
_LEFT_INSET = 2


def _icon_token(status: str) -> str:
    if status == "done":
        return "success"
    if status == "in_progress":
        return "accent"
    return "muted"


def _todo_level_and_title(item: dict[str, Any]) -> tuple[int, str]:
    """Return display nesting level and a cleaned title.

    The public todo schema is intentionally tiny, but tool-call payloads and
    persisted older sessions can still carry presentation hints. Prefer an
    explicit ``level``/``depth``/``indent`` when present; otherwise infer one
    from leading spaces in the title so pasted markdown-ish plans render as a
    real tree instead of a flat wall of text.
    """
    raw_title = as_str(item.get("title")) or ""
    explicit = item.get("level", item.get("depth", item.get("indent")))
    if isinstance(explicit, int):
        return max(0, min(explicit, 6)), raw_title.strip()

    leading_spaces = len(raw_title) - len(raw_title.lstrip(" "))
    level = max(0, min(leading_spaces // 2, 6))
    return level, raw_title.strip()


def _status_title(status: str, title: str) -> Text:
    if status == "done":
        return fg("muted", title)
    if status == "in_progress":
        out = fg("accent", title)
        out.stylize("bold")
        return out
    return fg("tool_output", title)


def _render_call(ctx: ToolRenderContext) -> RenderableType:
    args = ctx.args or {}
    todos = args.get("todos")

    header = Text()
    header.append_text(tool_title("todos"))

    if todos is None:
        header.append_text(fg("muted", " (read)"))
        return Padding(header, (0, 0, 0, _LEFT_INSET))

    if not isinstance(todos, list):
        header.append_text(fg("muted", " ..."))
        return Padding(header, (0, 0, 0, _LEFT_INSET))

    todos_list = cast("list[Any]", todos)
    items: list[dict[str, Any]] = [
        cast("dict[str, Any]", t) for t in todos_list if isinstance(t, dict)
    ]
    counts = {"pending": 0, "in_progress": 0, "done": 0}
    for item in items:
        status = as_str(item.get("status")) or "pending"
        if status in counts:
            counts[status] += 1

    if not items:
        header.append_text(fg("muted", " (empty)"))
        return Padding(header, (0, 0, 0, _LEFT_INSET))

    total = len(items)
    badge = f" {counts['done']}/{total} done"
    if counts["in_progress"]:
        badge += f" · {counts['in_progress']} active"
    if counts["pending"]:
        badge += f" · {counts['pending']} pending"
    header.append_text(fg("muted", badge))

    visible = items if ctx.expanded else items[:_DEFAULT_COLLAPSED_LINES]
    table = Table.grid(padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column(width=2, no_wrap=True)
    table.add_column(ratio=1)
    for index, item in enumerate(visible):
        status = as_str(item.get("status")) or "pending"
        level, title = _todo_level_and_title(item)
        icon = _ICONS.get(status, "○")
        has_continuation_row = not ctx.expanded and len(items) > len(visible)
        branch = (
            _TREE_LAST if index == len(visible) - 1 and not has_continuation_row else _TREE_BRANCH
        )
        gutter = ("  " * level) + branch
        table.add_row(
            fg("dim", gutter),
            fg(_icon_token(status), icon),
            _status_title(status, title),
        )

    rows: list[RenderableType] = [header, table]
    if not ctx.expanded and len(items) > len(visible):
        remaining = len(items) - len(visible)
        rows.append(fg("muted", f"{_TREE_LAST} ... +{remaining} more (ctrl+e to expand)"))
    return Padding(Group(*rows), (0, 0, 0, _LEFT_INSET))


def _render_result(ctx: ToolRenderContext, result: ToolResultPayload) -> RenderableType | None:
    if not result.text or not result.is_error:
        return None
    body, _ = format_lines_block(
        result.text,
        expanded=True,
        collapsed_max_lines=0,
        style_token="error",
    )
    return body if body.plain else None


TODO_RENDERER = ToolRenderDefinition(
    name=_TOOL_NAME,
    label="todos",
    render_shell="default",
    render_call=_render_call,
    render_result=_render_result,
)
