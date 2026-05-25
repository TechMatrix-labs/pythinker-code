"""Brand-styled Rich Panel factory: rounded borders + theme tokens."""

from __future__ import annotations

from rich import box
from rich.console import RenderableType
from rich.panel import Panel

from pythinker_code.ui.theme import tui_rich_style


def brand_panel(
    renderable: RenderableType,
    *,
    title: str | None = None,
    active: bool = False,
    padding: tuple[int, int] = (0, 1),
) -> Panel:
    """A Panel with rounded corners and brand border colors.

    ``active=True`` uses the informational accent border; otherwise the slate border.
    """
    border = tui_rich_style("border_accent" if active else "border")
    return Panel(
        renderable,
        title=title,
        box=box.ROUNDED,
        border_style=border,
        padding=padding,
    )
