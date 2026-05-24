"""Shared constants and helpers for file/diff rendering across the shell TUI.

Single source of truth for values that were previously duplicated across the
inline diff renderer (``components/diff.py``), the panel diff renderer
(``utils/rich/diff_render.py``), and the line-listing helpers
(``tool_renderers/_render_utils.py``).
"""

from __future__ import annotations

from typing import Final

from pythinker_code.ui.shell.keymap import key_text

__all__ = [
    "DIFF_CONTEXT_LINES",
    "DIFF_LINE_NUMBER_MIN_WIDTH",
    "LISTING_LINE_NUMBER_MIN_WIDTH",
    "EXPAND_KEY_ID",
    "EXPAND_KEY_FALLBACK",
    "expand_hint",
]

#: Lines of unchanged context kept around each diff hunk.
DIFF_CONTEXT_LINES: Final = 3
#: Minimum gutter width for diff line numbers (diffs are usually short hunks).
DIFF_LINE_NUMBER_MIN_WIDTH: Final = 2
#: Minimum gutter width for full file listings (more lines → wider numbers).
LISTING_LINE_NUMBER_MIN_WIDTH: Final = 4

#: Semantic keybinding id for "expand truncated output".
EXPAND_KEY_ID: Final = "app.tools.expand"
#: Shown when no binding is registered for :data:`EXPAND_KEY_ID`.
EXPAND_KEY_FALLBACK: Final = "ctrl+o"


def expand_hint(remaining: int) -> str:
    """Return the canonical "N more lines, press <key> to expand" hint.

    Resolves the live expand keybinding so every truncated body shows the same
    wording and the correct key (replacing the hardcoded ``ctrl+o``/``ctrl-e``
    variants that had drifted apart across renderers).
    """
    key = key_text(EXPAND_KEY_ID) or EXPAND_KEY_FALLBACK
    plural = "s" if remaining != 1 else ""
    return f"… {remaining} more line{plural} ({key} to expand)"
