from __future__ import annotations

from pythinker_code.ui.shell import _background_idle_reminder


def test_reminder_no_running_tasks_is_unchanged() -> None:
    out = _background_idle_reminder(0)
    assert out == (
        "<system-reminder>Background tasks completed while you were idle.</system-reminder>"
    )
    assert "block=true" not in out


def test_reminder_singular_steers_away_from_blocking() -> None:
    out = _background_idle_reminder(1)
    assert "1 background task is still running" in out
    assert "Do not block on a single task with TaskOutput(block=true)" in out
    assert out.startswith("<system-reminder>") and out.endswith("</system-reminder>")


def test_reminder_plural_steers_away_from_blocking() -> None:
    out = _background_idle_reminder(3)
    assert "3 background tasks are still running" in out
    assert "return control now" in out
    assert "re-woken" in out
