"""Canonical glyphs for shell TUI animations.

Single source for the loading-spinner frames and the reduced-motion glyph that
were previously duplicated between :mod:`pythinker_code.ui.shell.motion` and
:mod:`pythinker_code.ui.shell.spinner_words`.
"""

from __future__ import annotations

from typing import Final

#: Braille dotted spinner frames, rendered left-to-right per tick.
SPINNER_FRAMES: Final = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
#: Solid dot pulse for the Composing / Thinking activity lines instead of the
#: dotted braille spinner. The blank frame keeps the label column stable while
#: making the dot appear and disappear.
SHAPE_FRAMES: Final = ("●", " ")
#: Seconds each braille spinner frame stays on screen.
SPINNER_FRAME_INTERVAL_S: Final = 0.08
#: Seconds each solid-dot pulse frame stays on screen.
SHAPE_FRAME_INTERVAL_S: Final = 0.45
#: Static stand-in used when motion is disabled.
REDUCED_MOTION_GLYPH: Final = "●"

__all__ = [
    "SPINNER_FRAMES",
    "SHAPE_FRAMES",
    "SPINNER_FRAME_INTERVAL_S",
    "SHAPE_FRAME_INTERVAL_S",
    "REDUCED_MOTION_GLYPH",
]
