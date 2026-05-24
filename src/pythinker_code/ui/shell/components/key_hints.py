"""Helpers for formatting keybinding hints in Pythinker status lines."""

from __future__ import annotations

from rich.text import Text

from pythinker_code.ui.shell.keymap import key_text


def raw_key_hint(key: str, description: str) -> Text:
    """Format ``Esc cancel``-style hint with a raw key string.

    Use when no semantic keybinding is registered yet (or the binding is
    fixed at the OS/terminal level, e.g. ``Esc``).
    """
    out = Text()
    out.append(key, style="grey50")
    out.append(f" {description}", style="grey39")
    return out


def key_hint(key: str, description: str) -> Text:
    """Format a key hint, resolving semantic keybinding ids when available."""
    return raw_key_hint(key_text(key) or key, description)
