"""Blackbox-inspired motion helpers for the shell TUI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from rich.color import Color
from rich.style import Style
from rich.text import Text

from pythinker_code.soul import format_token_count
from pythinker_code.ui.shell.components.render_utils import cell_width
from pythinker_code.ui.shell.design_system import ShellTone, shell_style
from pythinker_code.ui.shell.glyphs import (
    REDUCED_MOTION_GLYPH,
    SHAPE_FRAME_INTERVAL_S,
    SHAPE_FRAMES,
    SPINNER_FRAME_INTERVAL_S,
    SPINNER_FRAMES,
)
from pythinker_code.ui.theme import tui_rich_style
from pythinker_code.utils.datetime import format_elapsed

_FRAMES = SPINNER_FRAMES
_FRAME_INTERVAL_S = SPINNER_FRAME_INTERVAL_S


def verb_spinner_style() -> Style:
    """Orange style for the active verb spinner word."""
    return Style(color=Color.parse("#EE9983"))  # brand-exception: verb shimmer orange


# ChatGPT-like clean shimmer: a subtle orange sweep on the active verb only.
_SHIMMER_BASE = "#EE9983"  # brand-exception: orange shimmer literal
_SHIMMER_MID = "#F2A892"  # brand-exception: orange shimmer literal
_SHIMMER_HIGHLIGHT = "#FFD5C7"  # brand-exception: orange shimmer literal
_SHIMMER_INTERVAL_S = 0.22
_SPINNER_SILVER_STYLE = Style(color=Color.parse("#C0C0C0"))  # brand-exception: silver spinner


def shimmer_spinner_style(elapsed_s: float, *, reduced_motion: bool = False) -> Style:
    """Clean orange shimmer color for active verb text.

    Reduced motion pins to the base orange so the word stays calm.
    """
    if reduced_motion or reduced_motion_enabled():
        return Style(color=Color.parse(_SHIMMER_BASE))
    palette = (_SHIMMER_BASE, _SHIMMER_MID, _SHIMMER_HIGHLIGHT, _SHIMMER_MID)
    idx = int(max(0.0, elapsed_s) / _SHIMMER_INTERVAL_S) % len(palette)
    return Style(color=Color.parse(palette[idx]))


def _shimmer_label_text(label: str, elapsed_s: float, *, reduced_motion: bool) -> Text:
    """Return a subtle per-character shimmer for the active verb label."""
    if reduced_motion or reduced_motion_enabled():
        return Text(label, style=shimmer_spinner_style(elapsed_s, reduced_motion=True))

    chars = list(label)
    if not chars:
        return Text("")
    # Sweep one bright highlight right-to-left with an asymmetric, slightly
    # wider trail. The uneven trail reads like an angled sheen instead of a flat pulse.
    phase = int(max(0.0, elapsed_s) / _SHIMMER_INTERVAL_S) % (len(chars) + 6)
    head = len(chars) + 2 - phase
    rendered = Text()
    for i, char in enumerate(chars):
        if char.isspace():
            rendered.append(char)
            continue
        offset = i - head
        if offset == 0:
            color = _SHIMMER_HIGHLIGHT
        elif offset in (-1, 1, 2, 3):
            color = _SHIMMER_MID
        else:
            color = _SHIMMER_BASE
        rendered.append(char, style=Style(color=Color.parse(color)))
    return rendered


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    label: str
    elapsed_s: float
    tokens: int = 0
    token_rate: int | None = None
    stalled: bool = False
    interrupt_hint: str = ""
    reduced_motion: bool = False
    label_style: Style | None = None
    # "braille" = dotted spinner (default); "shape" = morphing filled shape.
    spinner: Literal["braille", "shape"] = "braille"


def reduced_motion_enabled() -> bool:
    return os.environ.get("PYTHINKER_REDUCED_MOTION", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def spinner_frame_at(
    elapsed_s: float,
    *,
    reduced_motion: bool = False,
    frames: tuple[str, ...] = _FRAMES,
    interval_s: float = _FRAME_INTERVAL_S,
) -> str:
    if reduced_motion:
        return REDUCED_MOTION_GLYPH
    index = int(max(0.0, elapsed_s) / interval_s) % len(frames)
    return frames[index]


def _candidate_parts(snapshot: ActivitySnapshot) -> list[str]:
    parts = [format_elapsed(snapshot.elapsed_s)]
    if snapshot.tokens:
        parts.append(f"↓ {format_token_count(snapshot.tokens)} tokens")
    if snapshot.token_rate:
        parts.append(f"{snapshot.token_rate} t/s")
    if snapshot.interrupt_hint:
        hint = "esc" if snapshot.interrupt_hint == "esc to interrupt" else snapshot.interrupt_hint
        parts.append(hint)
    return parts


def _activity_label(label: str) -> str:
    stripped = label.rstrip()
    if stripped.endswith(("…", "...")):
        return stripped
    return f"{stripped}…"


def activity_status_line(snapshot: ActivitySnapshot, *, width: int | None = None) -> Text:
    reduced = snapshot.reduced_motion or reduced_motion_enabled()
    thinking_style = tui_rich_style("thinking_text")
    if snapshot.stalled:
        glyph_style = shell_style(ShellTone.WARNING)
    elif snapshot.spinner == "shape":
        # Composing / Thinking: neutral muted grey, not the bright coral verb accent.
        glyph_style = thinking_style
    else:
        # The dotted braille spinner is a marker; keep it silver while the verb shimmers.
        glyph_style = _SPINNER_SILVER_STYLE
    if snapshot.label_style is not None:
        label_style = snapshot.label_style
    elif snapshot.spinner == "shape":
        label_style = thinking_style
    else:
        label_style = shimmer_spinner_style(snapshot.elapsed_s, reduced_motion=reduced)
    if snapshot.label.lower() == "thinking":
        label_style += Style(italic=True)
    if snapshot.spinner == "shape":
        frames, interval_s = SHAPE_FRAMES, SHAPE_FRAME_INTERVAL_S
    else:
        frames, interval_s = _FRAMES, _FRAME_INTERVAL_S
    text = Text(
        spinner_frame_at(
            snapshot.elapsed_s, reduced_motion=reduced, frames=frames, interval_s=interval_s
        ),
        style=glyph_style,
    )
    text.append(" ")
    label_text = _activity_label(snapshot.label)
    if snapshot.label_style is None and snapshot.spinner != "shape":
        shimmered = _shimmer_label_text(label_text, snapshot.elapsed_s, reduced_motion=reduced)
        if snapshot.label.lower() == "thinking":
            shimmered.stylize(Style(italic=True))
        text.append_text(shimmered)
    else:
        text.append(label_text, style=label_style)

    parts = _candidate_parts(snapshot)
    if width is not None:
        base_width = cell_width(text.plain)
        kept: list[str] = []
        for part in parts:
            candidate = " · ".join([*kept, part])
            if base_width + 3 + cell_width(candidate) <= width:
                kept.append(part)
        parts = kept
    if parts:
        secondary_style = thinking_style
        text.append(" ", style=secondary_style)
        text.append("· ", style=secondary_style)
        text.append(" · ".join(parts), style=secondary_style)
    return text
