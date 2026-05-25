"""Shared helpers for Pythinker tool renderers."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.style import Style as RichStyle
from rich.table import Table
from rich.text import Text

from pythinker_code.ui.shell.components import sanitize_ansi
from pythinker_code.ui.shell.motion import reduced_motion_enabled
from pythinker_code.ui.shell.render_constants import LISTING_LINE_NUMBER_MIN_WIDTH
from pythinker_code.ui.theme import tui_rich_style

__all__ = [
    "as_str",
    "fg",
    "format_lines_block",
    "format_numbered_lines_block",
    "invalid_arg",
    "missing_required_arg",
    "loading_marker",
    "running_spinner",
    "shorten_path",
    "tab_to_spaces",
    "tool_call_header",
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


def tool_call_header(
    name: str,
    summary: str | Text | None = None,
    *,
    style_token: str = "success",
    paren_style_token: str = "muted",
) -> Text:
    """Return the Blackbox/Claude-style tool-use row.

    Shape: ``● Tool(summary)``.  The surrounding ``ToolExecutionComponent``
    owns result gutters; individual renderers should keep this row compact.
    """
    header = Text()
    header.append("● ", style=tui_rich_style(style_token))
    header.append_text(tool_title(name))
    if summary is not None:
        paren_style = tui_rich_style(paren_style_token)
        header.append("(", style=paren_style)
        if isinstance(summary, Text):
            header.append_text(summary)
        else:
            header.append(summary)
        header.append(")", style=paren_style)
    return header


def loading_marker(
    *,
    done: bool = False,
    pulse: bool = True,
    now: float | None = None,
    style_token: str = "muted",
) -> Text:
    """Return the app-wide task marker.

    Running tasks use the same solid-dot appear/disappear pulse as the
    Composing / Thinking indicator; completed tasks use a green checkmark.
    The animated braille spinner is reserved for the bottom thinking-word
    status. Callers may pass ``style_token="accent"`` for prominent rows.
    """
    if done:
        return Text("✓ ", style=tui_rich_style("success"))
    if not pulse or reduced_motion_enabled():
        return Text("● ", style=tui_rich_style(style_token))
    t = time.monotonic() if now is None else now
    glyph = "●" if int(t / 0.8) % 2 == 0 else " "
    return Text(f"{glyph} ", style=tui_rich_style(style_token))


def running_spinner(
    renderable: RenderableType,
    *,
    execution_started: bool,
    has_result: bool,
    marker_style_token: str = "muted",
) -> RenderableType:
    """Wrap *renderable* in the animated tool marker while executing.

    Tool-use headers already render a static ``●`` for completed/error states.
    While a tool is running, that static marker would sit immediately after the
    animated marker (``• ● Bash(...)``). Strip the static header marker in the
    running state and place the content in a two-column grid so wrapped command
    text remains indented under the tool text instead of jumping to column 0.
    """
    if not (execution_started and not has_result):
        return renderable

    marker = loading_marker(style_token=marker_style_token)
    content = _strip_running_static_marker(renderable)
    table = Table.grid(padding=0)
    table.add_column(width=2, no_wrap=True)
    table.add_column(ratio=1)
    table.add_row(marker, content)
    return Group(table)


def _strip_running_static_marker(renderable: RenderableType) -> RenderableType:
    """Remove one leading static bullet from the first visible child.

    Most tool renderers now use ``tool_call_header()`` for completed states.
    Running rows add their animated marker outside the renderer, so the static
    header marker must be stripped even when the renderer returns a ``Group``
    or ``Padding`` around the header and follow-up rows.
    """
    if isinstance(renderable, Text):
        if not renderable.plain.startswith(("● ", "• ")):
            return renderable
        parts = renderable.divide([2])
        return parts[1] if len(parts) > 1 else Text("")
    if isinstance(renderable, Group) and renderable.renderables:
        first, *rest = renderable.renderables
        return Group(_strip_running_static_marker(first), *rest, fit=renderable.fit)
    if isinstance(renderable, Padding):
        return Padding(
            _strip_running_static_marker(renderable.renderable),
            (renderable.top, renderable.right, renderable.bottom, renderable.left),
            style=renderable.style,
            expand=renderable.expand,
        )
    return renderable


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


def format_numbered_lines_block(
    text: str,
    *,
    expanded: bool,
    collapsed_max_lines: int,
    start_line: int = 1,
    style_token: str = "tool_output",
) -> tuple[Text, int, int]:
    """Render source text with dim line numbers, capped like Blackbox code previews.

    Returns ``(rendered, remaining, total_lines)``.  A trailing newline is a
    terminator, not an extra empty source line, matching editor line numbering.
    """
    cleaned = sanitize_ansi(text or "").rstrip("\n")
    if not cleaned:
        return Text(""), 0, 0
    lines = cleaned.split("\n")
    total_lines = len(lines)
    max_lines = total_lines if expanded else max(0, collapsed_max_lines)
    shown = lines[:max_lines] if max_lines else []
    remaining = max(0, total_lines - len(shown))
    number_width = max(
        LISTING_LINE_NUMBER_MIN_WIDTH, len(str(start_line + max(0, total_lines - 1)))
    )
    body = Text()
    number_style = tui_rich_style("muted")
    content_style = tui_rich_style(style_token)
    for index, line in enumerate(shown):
        if index:
            body.append("\n")
        body.append(f"{start_line + index:>{number_width}} ", style=number_style)
        body.append(tab_to_spaces(line), style=content_style)
    return body, remaining, total_lines
