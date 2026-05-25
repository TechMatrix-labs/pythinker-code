"""Semantic keybinding registry for the shell UI.

The registry is intentionally small: it records shortcuts the Python shell
actually handles today, plus a handful of terminal-level controls that appear
in help overlays.  It gives renderers and slash commands one place to look up
printable key chords without hard-coding prompt-specific strings everywhere.

Two common surfaces:

* :func:`key_text(name)` returns the printable representation
  (``"ctrl+o"``, ``"esc/ctrl+c"``) for inline renderer hints.
* :func:`keybinding_help()` returns ordered metadata for `/keys` and prompt
  shortcut overlays.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from pythinker_code.ui.theme import tui_rich_style

__all__ = [
    "KeybindingInfo",
    "all_keybindings",
    "key_hint",
    "key_text",
    "keybinding_help",
    "keybinding_description",
    "register_keybinding",
]


@dataclass(frozen=True, slots=True)
class KeybindingInfo:
    """Human-facing metadata for one registered keybinding."""

    name: str
    keys: tuple[str, ...]
    description: str
    context: str = ""


# Default registry. Keys are Pythinker semantic ids ("app.tools.expand");
# values are the key chord(s) the host will dispatch. Context-specific chords
# may repeat: for example ctrl+o opens the editor at the idle prompt and
# expands tool output while reviewing the transcript.
_REGISTRY: dict[str, tuple[str, ...]] = {
    "app.prompt.help": ("?",),
    "app.mode.toggle": ("ctrl+x",),
    "app.plan.toggle": ("shift+tab",),
    "app.shell.oneshot": ("!",),
    "app.editor.external": ("ctrl+o",),
    "app.prompt.newline": ("ctrl+j", "alt+enter"),
    "app.clipboard.paste": ("ctrl+v",),
    "app.mention.files": ("@",),
    "app.command.slash": ("/",),
    "app.tools.expand": ("ctrl+o",),
    "app.todos.toggle": ("ctrl+t",),
    "app.interrupt": ("esc", "ctrl+c"),
    "app.exit": ("ctrl+d",),
    "app.suspend": ("ctrl+z",),
    "tui.select.cancel": ("esc",),
    "tui.select.confirm": ("enter",),
}

_BINDING_DESCRIPTIONS: dict[str, str] = {
    "app.prompt.help": "show shortcuts",
    "app.mode.toggle": "toggle agent/shell prompt",
    "app.plan.toggle": "toggle plan mode",
    "app.shell.oneshot": "run one shell command",
    "app.editor.external": "open prompt in editor",
    "app.prompt.newline": "insert newline",
    "app.clipboard.paste": "paste text/images/files",
    "app.mention.files": "mention files",
    "app.command.slash": "open slash commands",
    "app.tools.expand": "expand/collapse tool output",
    "app.todos.toggle": "show/hide pinned todo list",
    "app.interrupt": "cancel or interrupt",
    "app.exit": "exit on empty prompt",
    "app.suspend": "suspend terminal process",
    "tui.select.cancel": "cancel selection",
    "tui.select.confirm": "confirm selection",
}

_BINDING_CONTEXTS: dict[str, str] = {
    "app.prompt.help": "prompt",
    "app.mode.toggle": "prompt",
    "app.plan.toggle": "prompt",
    "app.shell.oneshot": "agent prompt",
    "app.editor.external": "prompt",
    "app.prompt.newline": "prompt",
    "app.clipboard.paste": "prompt",
    "app.mention.files": "agent prompt",
    "app.command.slash": "prompt",
    "app.tools.expand": "transcript",
    "app.todos.toggle": "running prompt",
    "app.interrupt": "global",
    "app.exit": "prompt",
    "app.suspend": "terminal",
    "tui.select.cancel": "modal",
    "tui.select.confirm": "modal",
}

_BINDING_ORDER: tuple[str, ...] = (
    "app.prompt.help",
    "app.mode.toggle",
    "app.plan.toggle",
    "app.shell.oneshot",
    "app.editor.external",
    "app.prompt.newline",
    "app.clipboard.paste",
    "app.mention.files",
    "app.command.slash",
    "app.tools.expand",
    "app.todos.toggle",
    "app.interrupt",
    "app.exit",
    "app.suspend",
    "tui.select.cancel",
    "tui.select.confirm",
)


def register_keybinding(name: str, *keys: str) -> None:
    """Register or override the key chord(s) for *name*.

    Last writer wins — extensions calling this at startup can replace any
    builtin binding. Empty *keys* removes the binding entirely.
    """
    if not keys:
        _REGISTRY.pop(name, None)
        return
    _REGISTRY[name] = tuple(keys)


def all_keybindings() -> dict[str, tuple[str, ...]]:
    """Return a copy of the full registry — useful for `/keys` overlays."""
    return dict(_REGISTRY)


def key_text(name: str) -> str:
    """Render the chord(s) bound to *name* as ``"ctrl+o"`` or ``"esc/ctrl+c"``.

    Returns an empty string when *name* is unknown — callers can fall back
    to a hard-coded label.
    """
    keys = _REGISTRY.get(name)
    if not keys:
        return ""
    return "/".join(keys)


def keybinding_description(name: str) -> str:
    """Return the human-facing action label for a keybinding id."""
    return _BINDING_DESCRIPTIONS.get(name, name)


def keybinding_help() -> list[KeybindingInfo]:
    """Return keybindings in prompt-help order with descriptions and context."""
    ordered_names = [name for name in _BINDING_ORDER if name in _REGISTRY]
    ordered_names.extend(sorted(name for name in _REGISTRY if name not in set(ordered_names)))
    return [
        KeybindingInfo(
            name=name,
            keys=_REGISTRY[name],
            description=keybinding_description(name),
            context=_BINDING_CONTEXTS.get(name, ""),
        )
        for name in ordered_names
    ]


def key_hint(name: str, description: str) -> Text:
    """Build a ``"<keys> <description>"`` hint as styled Rich Text."""
    out = Text()
    label = key_text(name)
    if label:
        out.append(label, style=tui_rich_style("dim"))
        out.append(" ")
    out.append(description, style=tui_rich_style("muted"))
    return out
