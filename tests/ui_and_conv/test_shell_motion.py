from __future__ import annotations

from rich.console import Console

from pythinker_code.ui.shell.motion import ActivitySnapshot, activity_status_line, spinner_frame_at


def _plain(renderable) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


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
    assert "(12s · ↓ 2.4k tokens · 42 t/s · esc)" in output
    assert "esc to interrupt" not in output


def test_activity_status_line_hides_secondary_parts_at_narrow_width():
    line = activity_status_line(
        ActivitySnapshot(label="Thinking", elapsed_s=12.0, tokens=2400, token_rate=42),
        width=24,
    )
    output = _plain(line)
    assert "Thinking" in output
    assert "42 t/s" not in output


def test_activity_status_line_uses_parenthesized_metadata():
    line = activity_status_line(ActivitySnapshot(label="Pythinking", elapsed_s=30.0, tokens=1300))

    output = _plain(line).strip()

    assert "Pythinking… (30s · ↓ 1.3k tokens)" in output
