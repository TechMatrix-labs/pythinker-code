from __future__ import annotations

from rich.console import Console
from rich.style import Style

from pythinker_code.ui.shell.glyphs import SHAPE_FRAME_INTERVAL_S
from pythinker_code.ui.shell.motion import ActivitySnapshot, activity_status_line, spinner_frame_at


def _plain(renderable) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


def _ansi(renderable) -> str:
    console = Console(record=True, width=100, color_system="truecolor")
    console.print(renderable)
    return console.export_text(styles=True)


def _style_for(renderable, text: str) -> Style:
    start = renderable.plain.index(text)
    end = start + len(text)
    span = next(span for span in renderable.spans if span.start <= start and span.end >= end)
    return Style.parse(span.style) if isinstance(span.style, str) else span.style


def _span_colors_for(renderable, text: str) -> set[str]:
    start = renderable.plain.index(text)
    end = start + len(text)
    colors: set[str] = set()
    for span in renderable.spans:
        if span.end <= start or span.start >= end:
            continue
        style = Style.parse(span.style) if isinstance(span.style, str) else span.style
        if style.color is not None:
            colors.add(style.color.triplet.hex.lower())
    return colors


def test_spinner_frame_changes_with_time():
    assert spinner_frame_at(0.0) != spinner_frame_at(0.2)


def test_reduced_motion_uses_static_glyph():
    assert spinner_frame_at(0.2, reduced_motion=True) == "●"


def test_activity_status_line_contains_label_elapsed_tokens_and_interrupt_hint():
    line = activity_status_line(
        ActivitySnapshot(
            label="Thinking",
            elapsed_s=12.0,
            tokens=2400,
            token_rate=42,
            interrupt_hint="esc to interrupt",
        )
    )
    output = _plain(line)
    assert "Thinking…" in output
    assert "· 12s · ↓ 2.4k tokens · 42 t/s · esc" in output
    assert "esc to interrupt" not in output


def test_activity_status_line_hides_secondary_parts_at_narrow_width():
    line = activity_status_line(
        ActivitySnapshot(label="Thinking", elapsed_s=12.0, tokens=2400, token_rate=42),
        width=24,
    )
    output = _plain(line)
    assert "Thinking" in output
    assert "42 t/s" not in output


def test_activity_status_line_uses_clean_metadata_separator():
    line = activity_status_line(ActivitySnapshot(label="Pythinking", elapsed_s=30.0, tokens=1300))

    output = _plain(line).strip()

    assert "Pythinking… · 30s · ↓ 1.3k tokens" in output


def test_activity_status_line_uses_silver_spinner_and_shimmering_verb():
    from pythinker_code.ui.theme import set_active_theme

    set_active_theme("dark")
    start = activity_status_line(ActivitySnapshot(label="Cultivating", elapsed_s=0.0))
    sheen = activity_status_line(ActivitySnapshot(label="Cultivating", elapsed_s=0.88))
    later_sheen = activity_status_line(ActivitySnapshot(label="Cultivating", elapsed_s=1.10))

    base_style = Style.parse(start.style) if isinstance(start.style, str) else start.style
    assert base_style.color.triplet.hex.lower() == "#c0c0c0"
    assert _span_colors_for(sheen, "Cultivating") >= {"#ee9983", "#f2a892", "#ffd5c7"}
    assert _span_colors_for(later_sheen, "Cultivating") >= {"#ee9983", "#f2a892", "#ffd5c7"}
    assert "Cultivating…" in _plain(start)


def test_shape_activity_status_line_pulses_solid_dot():
    visible = activity_status_line(
        ActivitySnapshot(label="Composing", elapsed_s=0.0, spinner="shape")
    )
    hidden = activity_status_line(
        ActivitySnapshot(label="Composing", elapsed_s=SHAPE_FRAME_INTERVAL_S, spinner="shape")
    )

    assert visible.plain.startswith("● Composing…")
    assert hidden.plain.startswith("  Composing…")


def test_shape_activity_status_line_defaults_to_neutral_thinking_grey():
    from pythinker_code.ui.theme import tui_rich_style

    thinking_grey = tui_rich_style("thinking_text").color
    purple_muted = tui_rich_style("muted").color

    for label in ("Composing", "Thinking"):
        line = activity_status_line(ActivitySnapshot(label=label, elapsed_s=1.0, spinner="shape"))
        base_style = Style.parse(line.style) if isinstance(line.style, str) else line.style
        assert base_style.color == thinking_grey
        assert base_style.color != purple_muted
        assert _style_for(line, label).color == thinking_grey
