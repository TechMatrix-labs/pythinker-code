from rich.color import Color

from pythinker_code.ui.shell.motion import shimmer_spinner_style
from pythinker_code.ui.theme import set_active_theme


def _color_hex(color: Color | None) -> str:
    assert color is not None
    triplet = color.triplet
    assert triplet is not None
    return triplet.hex.lower()


def test_shimmer_returns_base_accent_when_reduced_motion():
    set_active_theme("dark")
    s = shimmer_spinner_style(0.0, reduced_motion=True)
    assert _color_hex(s.color) == "#ee9983"


def test_shimmer_varies_over_time_when_motion_enabled(monkeypatch):
    monkeypatch.delenv("PYTHINKER_REDUCED_MOTION", raising=False)
    set_active_theme("dark")
    first = _color_hex(shimmer_spinner_style(0.0, reduced_motion=False).color)
    later = _color_hex(shimmer_spinner_style(0.22, reduced_motion=False).color)
    # At least one sampled frame differs from the base when animating.
    assert first != later or first != "#ee9983"
