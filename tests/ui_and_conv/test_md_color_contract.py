# tests/ui_and_conv/test_md_color_contract.py
"""Tier-1 ANSI/color contract tests (spec area 4).

Uses the truecolor-preserving capture so we can assert on SGR sequences,
exactly like tests/ui_and_conv/test_tui_render_snapshots.py.
"""

from __future__ import annotations

from pythinker_code.ui.shell.components.markdown import pythinker_markdown
from pythinker_code.ui.theme import get_markdown_colors
from tests.ui_and_conv._md_contract_helpers import render_ansi


def _sgr_fg(hexcolor: str) -> str:
    """Build the truecolor foreground SGR fragment for a #rrggbb color."""
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"38;2;{r};{g};{b}"


def test_code_block_border_does_not_use_inline_code_color():
    """Bug class: 'border colors inheriting code-span color'.

    The bordered code block frame uses code_block_border; inline code uses
    inline_code. They must be distinct colors, and the captured frame must not
    paint the border in the inline-code color.
    """
    colors = get_markdown_colors("dark")
    assert colors.code_block_border != colors.inline_code, (
        "precondition: palette must distinguish border from inline code"
    )
    md = "Here is `inline` and a block:\n\n```python\nx = 1\n```\n"
    coloured = render_ansi(pythinker_markdown(md), width=60)
    # The rounded frame characters must not carry the inline-code foreground.
    inline_fg = _sgr_fg(colors.inline_code)
    for frame_char in ("╭", "╰", "─"):
        idx = coloured.find(frame_char)
        if idx == -1:
            continue
        window = coloured[max(0, idx - 24) : idx]
        assert inline_fg not in window, "border frame inherited inline-code color"
