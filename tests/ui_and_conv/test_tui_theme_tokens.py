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


def test_dark_tokens_have_brand_values():
    set_active_theme("dark")
    t = get_tui_tokens()
    assert t.accent == "#EE9983"          # coral
    assert t.border == "#3A506D"          # slate
    assert t.info == "#AFE3F1"            # cyan
    assert t.success == "#7BC97F"
    assert t.error == "#EF5E62"
    assert t.tool_pending_bg == "#1B2230"
    assert t.tool_error_bg == "#2E1D24"


def test_light_tokens_have_brand_values():
    set_active_theme("light")
    t = get_tui_tokens()
    assert t.accent == "#AE5430"          # text-safe coral
    assert t.info == "#176B7E"            # text-safe cyan
    assert t.text == "#213853"            # navy text
    assert t.error == "#C0392B"
    assert t.tool_pending_bg == "#EFE7E8"


def test_get_tui_tokens_with_explicit_theme_arg():
    set_active_theme("dark")
    light = get_tui_tokens("light")
    assert light.tool_pending_bg == "#EFE7E8"


def test_text_token_is_empty_string_for_terminal_default():
    # Dark theme: empty string = use terminal's default fg color.
    # Light theme uses an explicit navy text color (#213853).
    assert get_tui_tokens("dark").text == ""


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
    with pytest.raises(ValueError):
        tui_rich_style("not_a_real_token")


def test_dark_markdown_uses_brand_roles():
    colors = get_markdown_colors("dark")
    assert colors.heading == "#EE9983"      # coral
    assert colors.strong == "#EE9983"
    assert colors.emphasis == "#8B93A3"     # muted
    assert colors.inline_code == "#AFE3F1"  # cyan
    assert colors.link == "#AFE3F1"
    assert colors.spinner_active == "#EE9983"
    assert markdown_rich_style("link", theme="dark").color is not None


def test_info_token_exists_and_is_cyan():
    assert get_tui_tokens("dark").info == "#AFE3F1"
    assert get_tui_tokens("light").info == "#176B7E"
    # resolver works for the new token
    set_active_theme("dark")
    assert tui_rich_style("info").color is not None
