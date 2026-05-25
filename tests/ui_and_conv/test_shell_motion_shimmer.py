from pythinker_code.ui.shell.motion import shimmer_spinner_style
from pythinker_code.ui.theme import set_active_theme


def test_shimmer_returns_base_accent_when_reduced_motion():
    set_active_theme("dark")
    s = shimmer_spinner_style(0.0, reduced_motion=True)
    assert s.color.triplet.hex.lower() == "#ee9983"


def test_shimmer_varies_over_time_when_motion_enabled(monkeypatch):
    monkeypatch.delenv("PYTHINKER_REDUCED_MOTION", raising=False)
    set_active_theme("dark")
    first = shimmer_spinner_style(0.0, reduced_motion=False).color.triplet.hex
    later = shimmer_spinner_style(0.22, reduced_motion=False).color.triplet.hex
    # At least one sampled frame differs from the base when animating.
    assert first != later or first.lower() != "#ee9983"
