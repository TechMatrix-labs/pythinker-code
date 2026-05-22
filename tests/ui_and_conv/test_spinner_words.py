from __future__ import annotations

from pythinker_code.ui.shell.spinner_words import (
    SPINNER_FRAMES,
    SPINNER_VERBS,
    spinner_message,
    spinner_verb,
)


def test_spinner_verbs_match_blackbox_word_bank() -> None:
    """The shell spinner carries the full Blackbox loading-word bank."""
    assert len(SPINNER_VERBS) == 187
    assert SPINNER_VERBS[:3] == ("Accomplishing", "Actioning", "Actualizing")
    assert "Pythinking" in SPINNER_VERBS
    assert "Clauding" not in SPINNER_VERBS
    assert "Fiddle-faddling" in SPINNER_VERBS
    assert "Flibbertigibbeting" in SPINNER_VERBS
    assert "Whatchamacalliting" in SPINNER_VERBS
    assert SPINNER_VERBS[-3:] == ("Wrangling", "Zesting", "Zigzagging")


def test_spinner_frames_use_requested_braille_dotted_design() -> None:
    assert SPINNER_FRAMES == ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def test_spinner_word_stays_stable_for_thirty_seconds() -> None:
    assert spinner_verb(120.0) == spinner_verb(149.9)


def test_spinner_word_rotates_after_interval() -> None:
    assert spinner_verb(120.0) != spinner_verb(150.0)


def test_spinner_message_uses_single_unicode_ellipsis() -> None:
    assert spinner_message(0).endswith("…")
    assert not spinner_message(0).endswith("...")
