from __future__ import annotations

from rich.console import Console

from pythinker_code.ui.shell.components.render_utils import cell_width
from pythinker_code.ui.shell.design_system import (
    ShellTone,
    dialog_title,
    keyboard_hint,
    render_row,
    render_segment_line,
    shell_style,
    status_icon,
)


def _plain(renderable, *, width: int = 80) -> str:
    console = Console(record=True, width=width, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_status_icon_names_are_stable():
    assert status_icon("running").plain == "●"
    assert status_icon("completed").plain == "✓"
    assert status_icon("failed").plain == "!"
    assert status_icon("denied").plain == "×"
    assert status_icon("interrupted").plain == "■"
    assert status_icon("waiting").plain == "○"
    assert status_icon("question").plain == "?"
    assert status_icon("approval").plain == "?"


def test_keyboard_hint_uses_key_and_label():
    output = _plain(keyboard_hint("esc", "interrupt"))
    assert "esc" in output
    assert "interrupt" in output


def test_segment_line_hides_right_segments_before_wrapping():
    line = render_segment_line(
        left=["Pythinker Code", "insert"],
        right=["very-long-context-value", "shift+up/down agents"],
        width=32,
        tone=ShellTone.MUTED,
    )
    output = _plain(line, width=32)
    assert "Pythinker Code" in output
    assert all(cell_width(row) <= 32 for row in output.splitlines() if row)


def test_dialog_title_includes_icon_and_title():
    output = _plain(dialog_title("approval", "Run shell command"))
    assert "Run shell command" in output


def test_render_row_combines_icon_and_content():
    output = _plain(render_row(status_icon("completed"), "done"))
    assert "✓" in output
    assert "done" in output


def test_shell_style_resolves_brand_tokens_and_switches_theme():
    from pythinker_code.ui.theme import set_active_theme

    set_active_theme("dark")
    assert shell_style(ShellTone.ACCENT).color.triplet.hex.lower() == "#5ea7e8"
    assert shell_style(ShellTone.SUCCESS).color.triplet.hex.lower() == "#7bc97f"
    set_active_theme("light")
    assert shell_style(ShellTone.ACCENT).color.triplet.hex.lower() == "#256ea8"
    set_active_theme("dark")


def test_verb_spinner_stays_orange_independent_of_accent_token():
    from pythinker_code.ui.shell.motion import verb_spinner_style
    from pythinker_code.ui.theme import set_active_theme

    set_active_theme("dark")
    assert verb_spinner_style().color.triplet.hex.lower() == "#ee9983"
