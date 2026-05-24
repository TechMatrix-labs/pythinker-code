"""Canonical vertical-spacing vocabulary for the shell TUI.

One source of truth for blank rows and padding so the render layers stay visually
consistent. The governing rule:

    The live stream owns the gaps *between* action blocks. Cards, panels, markdown,
    and code renderers own only their *internal* layout. Never let two layers space
    the same seam.

The canonical blank row is ``Text("")`` (an empty string), not ``Text(" ")`` — an
empty row never picks up stray background styling. Padding constants are Rich
``(vertical, horizontal)`` tuples; the standard keeps vertical padding at 0 on cards
and panels so the stream spacer is the single inter-block gap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from rich.console import RenderableType
from rich.text import Text

if TYPE_CHECKING:
    from prompt_toolkit.formatted_text import StyleAndTextTuples

__all__ = [
    "BLANK_ROW",
    "STREAM_GAP_ROWS",
    "SECTION_GAP_ROWS",
    "CARD_PADDING",
    "TINTED_CARD_PADDING",
    "DIALOG_PANEL_PADDING",
    "WORKLOG_PANEL_PADDING",
    "CODE_BLOCK_PADDING",
    "blank_row",
    "append_gap",
    "ensure_prompt_newline",
]

#: Canonical blank renderable. Shared instance — Rich re-renders it per use.
BLANK_ROW: Final = Text("")

#: Rows the live stream inserts between successive action blocks.
STREAM_GAP_ROWS: Final = 1
#: Rows between semantic sections inside a panel/dialog.
SECTION_GAP_ROWS: Final = 1

#: ``(vertical, horizontal)`` padding for cards/panels. Vertical stays 0 so the
#: stream spacer is the only inter-block gap; horizontal gives the tint breathing room.
CARD_PADDING: Final = (0, 1)
TINTED_CARD_PADDING: Final = (0, 1)
DIALOG_PANEL_PADDING: Final = (0, 1)
WORKLOG_PANEL_PADDING: Final = (0, 1)
CODE_BLOCK_PADDING: Final = (0, 1)


def blank_row() -> Text:
    """Return a fresh canonical blank row."""
    return Text("")


def append_gap(renderables: list[RenderableType], rows: int = STREAM_GAP_ROWS) -> None:
    """Append *rows* blank rows to *renderables* (no-op when ``rows <= 0``)."""
    for _ in range(max(0, rows)):
        renderables.append(blank_row())


def ensure_prompt_newline(fragments: StyleAndTextTuples) -> None:
    """Ensure prompt-toolkit *fragments* end on a newline boundary.

    Replaces the hand-written ``if ... endswith("\\n")`` guards scattered through the
    prompt preamble so newline policy lives in one place.
    """
    if fragments and not fragments[-1][1].endswith("\n"):
        fragments.append(("", "\n"))
