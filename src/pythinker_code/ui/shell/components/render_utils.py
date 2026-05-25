"""Width-aware rendering helpers for Pythinker components."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text

from pythinker_code.ui.theme import tui_rich_style

_ELLIPSIS = "…"
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_ST_RE = re.compile(r"\x1b\\")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class VisualTruncateResult:
    """Output of :func:`truncate_to_visual_lines`."""

    visual_lines: list[str]
    skipped_count: int


def truncate_to_visual_lines(
    text: str,
    max_visual_lines: int,
    width: int,
) -> VisualTruncateResult:
    """Truncate *text* to the last *max_visual_lines* visual lines at *width*.

    Each input line is wrapped to *width* (cell-aware) before truncation so
    very long lines collapse correctly. Returns the visible suffix plus a
    count of hidden lines.
    """
    if not text or max_visual_lines <= 0 or width <= 0:
        return VisualTruncateResult([], 0)

    cleaned = sanitize_ansi(text).replace("\r\n", "\n").replace("\r", "\n")
    visual: list[str] = []
    for raw in cleaned.split("\n"):
        if not raw:
            visual.append("")
            continue
        line = raw
        while line:
            chunk_chars: list[str] = []
            used = 0
            for ch in line:
                w = cell_len(ch)
                if used + w > width:
                    break
                chunk_chars.append(ch)
                used += w
            if not chunk_chars:
                # Single character wider than the available width — emit it
                # alone to avoid an infinite loop.
                chunk_chars = [line[0]]
            chunk = "".join(chunk_chars)
            visual.append(chunk)
            line = line[len(chunk) :]

    if len(visual) <= max_visual_lines:
        return VisualTruncateResult(visual, 0)
    skipped = len(visual) - max_visual_lines
    return VisualTruncateResult(visual[-max_visual_lines:], skipped)


def truncate_middle_to_visual_lines(
    text: str,
    max_visual_lines: int,
    width: int,
    *,
    hint: str = "ctrl+o to expand",
) -> VisualTruncateResult:
    """Truncate visual lines with a Codex-style head/tail ellipsis in the middle.

    Unlike :func:`truncate_to_visual_lines`, this preserves both early context
    and the most recent tail. This is better for terminal/tool output where the
    first few lines identify the command/result and the tail often contains the
    actionable failure.
    """
    full = truncate_to_visual_lines(text, max_visual_lines=10**9, width=width)
    lines = full.visual_lines
    if len(lines) <= max_visual_lines:
        return VisualTruncateResult(lines, 0)
    if max_visual_lines <= 0:
        return VisualTruncateResult([], len(lines))

    omitted = len(lines) - max_visual_lines + 1
    ellipsis = f"… +{omitted} lines ({hint})" if hint else f"… +{omitted} lines"
    ellipsis = truncate_to_width(ellipsis, width)
    if max_visual_lines == 1:
        return VisualTruncateResult([ellipsis], omitted)

    remaining = max_visual_lines - 1
    head_count = remaining // 2
    tail_count = remaining - head_count
    visible = [*lines[:head_count], ellipsis, *lines[-tail_count:]]
    return VisualTruncateResult(visible, omitted)


def cell_width(text: str) -> int:
    """Return terminal cell width of *text* (CJK-aware)."""
    return cell_len(text)


def truncate_to_width(text: str, max_width: int, *, ellipsis: str = _ELLIPSIS) -> str:
    """Truncate *text* so its terminal cell width fits within *max_width*.

    If *max_width* is too small to hold the ellipsis, returns the leading
    cells of *text* without an ellipsis.
    """
    if max_width <= 0:
        return ""
    if cell_len(text) <= max_width:
        return text
    ellipsis_w = cell_len(ellipsis)
    if max_width <= ellipsis_w:
        # No room for the marker — fall back to plain truncation.
        out: list[str] = []
        used = 0
        for ch in text:
            w = cell_len(ch)
            if used + w > max_width:
                break
            out.append(ch)
            used += w
        return "".join(out)
    budget = max_width - ellipsis_w
    used = 0
    cut = 0
    for i, ch in enumerate(text):
        w = cell_len(ch)
        if used + w > budget:
            cut = i
            break
        used += w
        cut = i + 1
    return text[:cut] + ellipsis


def render_message_response(renderable: RenderableType) -> RenderableType:
    """Render a Blackbox-style indented response gutter for tool details.

    Mirrors the reference message-response layout: result/progress
    content sits under a dim ``⎿`` marker so the call header and response are
    visually distinct without a heavy border.
    """
    table = Table.grid(padding=0)
    table.add_column(width=5, no_wrap=True)
    table.add_column(ratio=1)
    table.add_row(Text("  ⎿  ", style=tui_rich_style("muted")), renderable)
    return Group(table)


def dim(text: str | Text) -> Text:
    """Return *text* styled as dim grey ("muted") output."""
    if isinstance(text, Text):
        copy = text.copy()
        copy.stylize(tui_rich_style("muted"))
        return copy
    return Text(text, style=tui_rich_style("muted"))


def sanitize_ansi(text: str) -> str:
    """Strip ANSI escape sequences and other unsafe control bytes from *text*.

    Keeps newlines, carriage returns, and tabs. Use before feeding raw shell
    output into a Rich renderable to avoid cursor-movement and color leaks
    that break layout.
    """
    no_csi = _ANSI_CSI_RE.sub("", text)
    no_osc = _ANSI_OSC_RE.sub("", no_csi)
    no_st = _ANSI_ST_RE.sub("", no_osc)
    return _CONTROL_RE.sub("", no_st)


def render_plain(renderable: RenderableType, *, width: int = 80) -> str:
    """Render *renderable* to a plain string at the given *width*.

    Snapshot helper for tests — color codes are stripped so the output is
    a stable, comparable plain-text representation.
    """
    # Override TERM via _environ so Rich's `is_dumb_terminal` detection
    # doesn't kick in and force size to 80x25 (which silently ignores the
    # explicit `width=` argument). This matters in CI where TERM=dumb is set.
    console = Console(
        width=width,
        record=True,
        force_terminal=True,
        color_system=None,
        legacy_windows=False,
        _environ={"TERM": "xterm-256color"},
    )
    console.print(renderable)
    return console.export_text()
