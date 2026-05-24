"""Shared helpers for Pythinker tool renderers."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.style import Style as RichStyle
from rich.table import Table
from rich.text import Text

from pythinker_code.ui.shell.components import sanitize_ansi
from pythinker_code.ui.theme import tui_rich_style

__all__ = [
    "as_str",
    "fg",
    "format_lines_block",
    "invalid_arg",
    "missing_required_arg",
    "loading_marker",
    "running_spinner",
    "shorten_path",
    "tab_to_spaces",
    "tool_title",
]


def as_str(value: Any) -> str | None:
    """the ``str(...)`` helper: keep strings, return ``None`` for anything else.

    The renderer treats ``None`` as "missing" (placeholder) and a non-string
    value as "invalid".
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


def fg(token: str, content: str | Text) -> Text:
    """Wrap *content* in a Rich Text styled by a TUI theme *token*.

    Mirrors the ``theme.fg(token, text)``. ``content`` may already be a
    ``Text`` (style is applied non-destructively).
    """
    style = tui_rich_style(token)
    if isinstance(content, Text):
        out = content.copy()
        out.stylize(style)
        return out
    return Text(content, style=style)


def tool_title(label: str) -> Text:
    """Bold tool-name title ."""
    base = tui_rich_style("tool_title")
    return Text(label, style=base + RichStyle(bold=True))


def loading_marker(*, done: bool = False, pulse: bool = True, now: float | None = None) -> Text:
    """Return the app-wide task marker.

    Running tasks always show a visible dot that pulses between heavy/light
    dot glyphs; completed tasks use a green checkmark. The animated braille
    spinner is reserved for the bottom thinking-word status.
    """
    if done:
        return Text("✓ ", style=tui_rich_style("success"))
    if not pulse:
        return Text("● ", style=tui_rich_style("muted"))
    t = time.monotonic() if now is None else now
    glyph = "●" if int(t / 0.8) % 2 == 0 else "•"
    return Text(f"{glyph} ", style=tui_rich_style("muted"))


def running_spinner(
    renderable: RenderableType,
    *,
    execution_started: bool,
    has_result: bool,
) -> RenderableType:
    """Wrap *renderable* in the solid loading marker while the tool is executing.

    Returns *renderable* unchanged once a result has arrived (or if execution
    has not yet been dispatched), so callers need no guard of their own.
    """
    if not (execution_started and not has_result):
        return renderable

    marker = loading_marker()
    if isinstance(renderable, Text):
        out = marker.copy()
        out.append_text(renderable)
        return out

    table = Table.grid(padding=0)
    table.add_column(width=2, no_wrap=True)
    table.add_column(ratio=1)
    table.add_row(marker, renderable)
    return Group(table)


def invalid_arg() -> Text:
    """Placeholder rendered when an arg is not a valid string."""
    return fg("error", "<invalid>")


def missing_required_arg(name: str) -> Text:
    """Clear placeholder for a required arg absent from a finished invalid call."""
    return fg("error", f"<missing {name}>")


def shorten_path(path: str, *, cwd: str | None = None) -> str:
    """Display-shorten an absolute path in the standard way.

    * paths inside ``cwd`` are made relative;
    * paths inside ``$HOME`` are prefixed with ``~``;
    * other absolute paths stay absolute.
    """
    if not path:
        return path
    cwd = cwd or os.getcwd()
    try:
        p = Path(path)
        if p.is_absolute():
            try:
                rel = p.relative_to(cwd)
                s = str(rel)
                return s if s != "." else path
            except ValueError:
                home = Path.home()
                try:
                    rel = p.relative_to(home)
                    return f"~/{rel}" if str(rel) != "." else "~"
                except ValueError:
                    return path
        return path
    except (TypeError, ValueError):
        return path


def tab_to_spaces(text: str, *, tab_size: int = 4) -> str:
    """Replace tabs with spaces; preserves newlines."""
    if "\t" not in text:
        return text
    return text.expandtabs(tab_size)


def format_lines_block(
    text: str,
    *,
    expanded: bool,
    collapsed_max_lines: int,
    style_token: str = "tool_output",
) -> tuple[Text, int]:
    """Render *text* as a block of styled lines, capped at *collapsed_max_lines*.

    Returns a ``(rendered, remaining)`` tuple where *remaining* is the number
    of lines hidden by the collapsed view (``0`` when expanded or short).
    Always strips ANSI from input to keep layout safe.
    """
    cleaned = sanitize_ansi(text or "").rstrip("\n")
    if not cleaned:
        return Text(""), 0
    lines = cleaned.split("\n")
    max_lines = len(lines) if expanded else max(0, collapsed_max_lines)
    shown = lines[:max_lines] if max_lines else []
    remaining = max(0, len(lines) - len(shown))
    body = Text("\n".join(tab_to_spaces(line) for line in shown))
    body.stylize(tui_rich_style(style_token))
    return body, remaining
