"""Width-aware rendering helpers for Pythinker components."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, RenderableType
from rich.text import Text

_ELLIPSIS = "…"
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
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


def dim(text: str | Text) -> Text:
    """Return *text* styled as dim grey ("muted") output."""
    if isinstance(text, Text):
        copy = text.copy()
        copy.stylize("grey50")
        return copy
    return Text(text, style="grey50")


def sanitize_ansi(text: str) -> str:
    """Strip ANSI escape sequences and other unsafe control bytes from *text*.

    Keeps newlines, carriage returns, and tabs. Use before feeding raw shell
    output into a Rich renderable to avoid cursor-movement and color leaks
    that break layout.
    """
    no_csi = _ANSI_CSI_RE.sub("", text)
    no_osc = _ANSI_OSC_RE.sub("", no_csi)
    return _CONTROL_RE.sub("", no_osc)


def render_plain(renderable: RenderableType, *, width: int = 80) -> str:
    """Render *renderable* to a plain string at the given *width*.

    Snapshot helper for tests — color codes are stripped so the output is
    a stable, comparable plain-text representation.
    """
    console = Console(
        width=width,
        record=True,
        force_terminal=True,
        color_system=None,
        legacy_windows=False,
    )
    console.print(renderable)
    return console.export_text()
