"""Shared Rich primitives for the Pythinker shell TUI."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from pythinker_code.ui.shell.components.render_utils import cell_width, truncate_to_width


class ShellTone(StrEnum):
    NORMAL = "normal"
    MUTED = "muted"
    ACCENT = "accent"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


StatusName = Literal[
    "running",
    "completed",
    "failed",
    "denied",
    "interrupted",
    "waiting",
    "question",
    "approval",
]


_TONE_STYLES: dict[ShellTone, Style] = {
    ShellTone.NORMAL: Style(color="default"),
    ShellTone.MUTED: Style(color="#8b90a8"),
    ShellTone.ACCENT: Style(color="#BAC4FD"),
    ShellTone.SUCCESS: Style(color="#A6E3A1"),
    ShellTone.WARNING: Style(color="#F2CC60"),
    ShellTone.ERROR: Style(color="#F38BA8"),
    ShellTone.INFO: Style(color="#B8D7FF"),
}

_STATUS: dict[StatusName, tuple[str, ShellTone]] = {
    "running": ("●", ShellTone.ACCENT),
    "completed": ("✓", ShellTone.SUCCESS),
    "failed": ("!", ShellTone.ERROR),
    "denied": ("×", ShellTone.WARNING),
    "interrupted": ("■", ShellTone.MUTED),
    "waiting": ("○", ShellTone.MUTED),
    "question": ("?", ShellTone.WARNING),
    "approval": ("?", ShellTone.ACCENT),
}


def shell_style(tone: ShellTone) -> Style:
    return _TONE_STYLES[tone]


def status_icon(name: StatusName) -> Text:
    icon, tone = _STATUS[name]
    return Text(icon, style=shell_style(tone))


def keyboard_hint(key: str, label: str) -> Text:
    text = Text()
    text.append(key, style=shell_style(ShellTone.ACCENT) + Style(bold=True))
    if label:
        text.append(f" {label}", style=shell_style(ShellTone.MUTED))
    return text


def dialog_title(kind: StatusName, title: str) -> Text:
    text = Text()
    text.append_text(status_icon(kind))
    text.append(f" {title}", style=Style(bold=True))
    return text


def render_segment_line(
    *,
    left: list[str],
    right: list[str],
    width: int,
    tone: ShellTone = ShellTone.MUTED,
) -> Text:
    left_text = " | ".join(part for part in left if part)
    right_parts = [part for part in right if part]
    right_text = " | ".join(right_parts)
    if width <= 0:
        return Text("")
    while right_parts and cell_width(left_text) + 2 + cell_width(right_text) > width:
        right_parts.pop()
        right_text = " | ".join(right_parts)
    if not right_text:
        return Text(truncate_to_width(left_text, width), style=shell_style(tone))
    gap = max(2, width - cell_width(left_text) - cell_width(right_text))
    return Text(left_text + (" " * gap) + right_text, style=shell_style(tone))


def render_row(icon: str | Text, content: RenderableType) -> RenderableType:
    return Group(Text.assemble(icon, " "), content)
