"""Blackbox-inspired motion helpers for the shell TUI."""

from __future__ import annotations

import os
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text

from pythinker_code.soul import format_token_count
from pythinker_code.ui.shell.components.render_utils import cell_width
from pythinker_code.ui.shell.design_system import ShellTone, shell_style
from pythinker_code.utils.datetime import format_elapsed

_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_FRAME_INTERVAL_S = 0.08
_VERB_SPINNER_STYLE = Style(color="#F5A97F")


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


def reduced_motion_enabled() -> bool:
    return os.environ.get("PYTHINKER_REDUCED_MOTION", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def spinner_frame_at(elapsed_s: float, *, reduced_motion: bool = False) -> str:
    if reduced_motion:
        return "●"
    index = int(max(0.0, elapsed_s) / _FRAME_INTERVAL_S) % len(_FRAMES)
    return _FRAMES[index]


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
    glyph_style = shell_style(ShellTone.WARNING) if snapshot.stalled else _VERB_SPINNER_STYLE
    label_style = snapshot.label_style if snapshot.label_style is not None else _VERB_SPINNER_STYLE
    if snapshot.label.lower() == "thinking":
        label_style += Style(italic=True)
    text = Text(
        spinner_frame_at(snapshot.elapsed_s, reduced_motion=reduced),
        style=glyph_style,
    )
    text.append(" ")
    text.append(_activity_label(snapshot.label), style=label_style)

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
        text.append(" ", style=shell_style(ShellTone.MUTED))
        text.append("· ", style=shell_style(ShellTone.MUTED))
        text.append(" · ".join(parts), style=shell_style(ShellTone.MUTED))
    return text
