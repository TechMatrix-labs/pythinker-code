from __future__ import annotations

from pythinker_code.ui.shell import render_constants as rc


def test_diff_constants_values() -> None:
    assert rc.DIFF_CONTEXT_LINES == 3
    assert rc.DIFF_LINE_NUMBER_MIN_WIDTH == 2
    assert rc.LISTING_LINE_NUMBER_MIN_WIDTH == 4


def test_expand_hint_singular_vs_plural() -> None:
    assert rc.expand_hint(1) == f"… 1 more line ({rc.EXPAND_KEY_FALLBACK} to expand)"
    assert rc.expand_hint(7) == f"… 7 more lines ({rc.EXPAND_KEY_FALLBACK} to expand)"


def test_expand_hint_uses_resolved_key_not_hardcoded_ctrl_e() -> None:
    # Regression: the panel preview previously hardcoded "ctrl-e", which never
    # matched the real expand binding shown everywhere else.
    hint = rc.expand_hint(3)
    assert "ctrl-e" not in hint
    assert "expand" in hint


def test_expand_hint_uses_ellipsis_glyph() -> None:
    # One canonical leading glyph ("…"), not the ASCII "..." variant.
    assert rc.expand_hint(2).startswith("…")
