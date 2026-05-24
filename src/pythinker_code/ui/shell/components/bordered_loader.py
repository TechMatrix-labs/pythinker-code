"""Bordered spinner card with optional cancel hint.

A Rich-friendly stand-in for the bordered loader pattern used elsewhere in
the TUI — top/bottom rules in the active accent color, a centered spinner +
message, and an optional ``esc to cancel`` line. Stateless: callers pass a
:class:`BorderedLoaderState` and re-call :func:`render_bordered_loader`
each tick.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.text import Text

from pythinker_code.ui.shell.keymap import key_text
from pythinker_code.ui.shell.motion import reduced_motion_enabled
from pythinker_code.ui.theme import tui_rich_style

__all__ = [
    "BorderedLoaderState",
    "render_bordered_loader",
]


@dataclass(frozen=True, slots=True)
class BorderedLoaderState:
    """Inputs for :func:`render_bordered_loader`.

    Attributes:
        message: Status text shown next to the spinner.
        cancellable: When ``True``, append a ``<esc> cancel`` hint line.
        spinner: Deprecated; loading now renders as the shared solid circle.
        accent_token: TUI token name for the border + spinner color.
    """

    message: str
    cancellable: bool = True
    spinner: str = "dots"
    accent_token: str = "border_accent"


def render_bordered_loader(state: BorderedLoaderState) -> RenderableType:
    """Build the bordered loader renderable for *state*."""
    accent = tui_rich_style(state.accent_token)
    muted = tui_rich_style("muted")

    glyph = "●" if reduced_motion_enabled() or int(time.monotonic() / 0.8) % 2 == 0 else " "
    loading = Text(f"{glyph} ", style=muted)
    loading.append(state.message, style=muted)

    children: list[RenderableType] = [Rule(style=accent), loading]
    if state.cancellable:
        cancel_key = key_text("tui.select.cancel") or "esc"
        hint = Text()
        hint.append(cancel_key, style=tui_rich_style("dim"))
        hint.append(" cancel", style=muted)
        children.append(hint)
    children.append(Rule(style=accent))
    return Group(*children)
