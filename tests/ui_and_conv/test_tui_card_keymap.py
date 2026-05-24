"""Tests for the Pythinker keybinding registry."""

from __future__ import annotations

import pytest

from pythinker_code.ui.shell.components import render_plain
from pythinker_code.ui.shell.keymap import (
    all_keybindings,
    key_hint,
    key_text,
    keybinding_help,
    register_keybinding,
)


@pytest.fixture(autouse=True)
def _restore_registry():
    snapshot = all_keybindings()
    yield
    # Restore by re-registering everything; register_keybinding with no keys
    # deletes, so we re-set defaults for the modified ones too.
    for name, keys in snapshot.items():
        register_keybinding(name, *keys)


def test_known_binding_returns_chord():
    assert key_text("app.tools.expand") == "ctrl+o"
    assert key_text("app.editor.external") == "ctrl+o"
    assert key_text("app.mode.toggle") == "ctrl+x"


def test_unknown_binding_returns_empty_string():
    assert key_text("nope") == ""


def test_multi_key_binding_joins_with_slash():
    assert key_text("app.interrupt") == "esc/ctrl+c"


def test_register_overrides_builtin():
    register_keybinding("app.tools.expand", "ctrl+o")
    assert key_text("app.tools.expand") == "ctrl+o"


def test_register_removes_when_no_keys_given():
    register_keybinding("app.tools.expand")
    assert key_text("app.tools.expand") == ""


def test_key_hint_renders_text_and_description():
    out = render_plain(key_hint("app.tools.expand", "expand"), width=40)
    assert "ctrl+o" in out
    assert "expand" in out


def test_keybinding_help_includes_prompt_context_and_descriptions():
    help_rows = keybinding_help()
    by_name = {row.name: row for row in help_rows}

    assert by_name["app.shell.oneshot"].keys == ("!",)
    assert by_name["app.shell.oneshot"].description == "run one shell command"
    assert by_name["app.shell.oneshot"].context == "agent prompt"
