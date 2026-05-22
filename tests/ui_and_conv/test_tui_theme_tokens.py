"""Tests for the Pythinker semantic theme tokens added to ui/theme.py."""

from __future__ import annotations

import dataclasses

import pytest
from rich.style import Style as RichStyle

from pythinker_code.ui.theme import (
    TuiTokens,
    get_active_theme,
    get_markdown_colors,
    get_tui_tokens,
    markdown_rich_style,
    set_active_theme,
    tui_rich_style,
)


@pytest.fixture(autouse=True)
def _restore_active_theme():
    """Snapshot/restore the global active theme so tests don't bleed."""
    saved = get_active_theme()
    try:
        yield
    finally:
        set_active_theme(saved)


def test_dark_tokens_have_pi_reference_values():
    set_active_theme("dark")
    t = get_tui_tokens()
    #  values (packages/.../theme/dark.json).
    assert t.tool_pending_bg == "#282832"
    assert t.tool_success_bg == "#283228"
    assert t.tool_error_bg == "#3c2828"
    assert t.accent == "#7dd3fc"


def test_light_tokens_have_pi_reference_values():
    set_active_theme("light")
    t = get_tui_tokens()
    assert t.tool_pending_bg == "#e8e8f0"
    assert t.tool_success_bg == "#e8f0e8"
    assert t.tool_error_bg == "#f0e8e8"
    assert t.accent == "#0284c7"


def test_get_tui_tokens_with_explicit_theme_arg():
    set_active_theme("dark")
    light = get_tui_tokens("light")
    assert light.tool_pending_bg.startswith("#e8")


def test_text_token_is_empty_string_for_terminal_default():
    # Theme convention: empty string = use terminal's default fg color.
    assert get_tui_tokens("dark").text == ""
    assert get_tui_tokens("light").text == ""


def test_tokens_dataclass_is_frozen():
    t = get_tui_tokens("dark")
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.accent = "#000000"  # type: ignore[misc]


def test_all_token_fields_are_strings():
    t = get_tui_tokens("dark")
    for field in dataclasses.fields(TuiTokens):
        assert isinstance(getattr(t, field.name), str), field.name


def test_tui_rich_style_bg_token_produces_bgcolor():
    set_active_theme("dark")
    style = tui_rich_style("tool_pending_bg")
    assert isinstance(style, RichStyle)
    assert style.bgcolor is not None
    assert style.color is None


def test_tui_rich_style_fg_token_produces_color():
    set_active_theme("dark")
    style = tui_rich_style("accent")
    assert style.color is not None
    assert style.bgcolor is None


def test_tui_rich_style_empty_token_produces_empty_style():
    # text="" means terminal default — should not set color or bgcolor.
    set_active_theme("dark")
    style = tui_rich_style("text")
    assert style.color is None
    assert style.bgcolor is None


def test_tui_rich_style_unknown_token_raises():
    with pytest.raises(AttributeError):
        tui_rich_style("not_a_real_token")


def test_dark_markdown_uses_lighter_blue_accents():
    colors = get_markdown_colors("dark")

    assert colors.link == "#93c5fd"
    assert colors.spinner_active == "#7dd3fc"
    assert markdown_rich_style("link", theme="dark").color is not None
