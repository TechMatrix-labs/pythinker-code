"""Pi-style settings list component for prompt_toolkit selectors.

This module ports the state-machine shape of Pi's ``SettingsList`` to the
Pythinker prompt_toolkit shell. It is intentionally split into a pure
``_SettingsListState`` (unit-testable without a TTY) plus a small
``run_settings_list`` application wrapper.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension

from pythinker_code.ui.shell.components.render_utils import cell_width, truncate_to_width
from pythinker_code.ui.theme import get_prompt_style

__all__ = [
    "SettingItem",
    "SettingsListConfig",
    "SettingsListResult",
    "run_settings_list",
]


@dataclass(frozen=True, slots=True)
class SettingItem:
    """One row in a settings list.

    Rows with ``values`` cycle through those values on Enter/Space. Rows
    without values are read-only in this first port; richer text/submenu
    editors can be layered on later.
    """

    id: str
    label: str
    current_value: str
    description: str = ""
    values: Sequence[str] | None = None


@dataclass(frozen=True, slots=True)
class SettingsListConfig:
    """Static configuration for a settings list dialog."""

    title: str
    items: Sequence[SettingItem]
    max_visible: int = 10
    enable_search: bool = True
    hint: str = "↑↓ navigate · Enter/Space change · Ctrl+D apply · Esc cancel"


@dataclass(frozen=True, slots=True)
class SettingsListResult:
    """Result returned by :func:`run_settings_list`."""

    changes: dict[str, str]


class _SettingsListState:
    """Pure settings-list state machine."""

    def __init__(self, config: SettingsListConfig) -> None:
        self.config = config
        self.search = ""
        self.selected_idx = 0  # index into ``visible``
        self.visible: list[int] = []  # indices into config.items
        self.values: dict[str, str] = {item.id: item.current_value for item in config.items}
        self._original_values = dict(self.values)
        self.applied = False
        self.cancelled = False
        self._refilter(initial=True)

    def _haystack(self, item: SettingItem) -> str:
        return f"{item.label} {item.id} {item.description} {self.values[item.id]}".lower()

    @staticmethod
    def _fuzzy_match(needle: str, haystack: str) -> bool:
        if not needle:
            return True
        pos = 0
        for ch in needle.lower():
            found = haystack.find(ch, pos)
            if found < 0:
                return False
            pos = found + 1
        return True

    def _matches(self, item: SettingItem) -> bool:
        return self._fuzzy_match(self.search, self._haystack(item))

    def _refilter(self, *, initial: bool = False) -> None:
        previous_id: str | None = None
        if not initial and self.visible and 0 <= self.selected_idx < len(self.visible):
            previous_id = self.config.items[self.visible[self.selected_idx]].id

        self.visible = [i for i, item in enumerate(self.config.items) if self._matches(item)]
        if not self.visible:
            self.selected_idx = 0
            return

        if previous_id is not None:
            for pos, item_idx in enumerate(self.visible):
                if self.config.items[item_idx].id == previous_id:
                    self.selected_idx = pos
                    return
        self.selected_idx = 0

    @property
    def current_item(self) -> SettingItem | None:
        if not self.visible or self.selected_idx >= len(self.visible):
            return None
        return self.config.items[self.visible[self.selected_idx]]

    def current_value(self, item: SettingItem) -> str:
        return self.values[item.id]

    def move(self, delta: int) -> None:
        if not self.visible:
            return
        self.selected_idx = (self.selected_idx + delta) % len(self.visible)

    def activate(self) -> bool:
        """Cycle the selected setting. Returns True when a value changed."""
        item = self.current_item
        if item is None or not item.values:
            return False
        values = list(item.values)
        if not values:
            return False
        try:
            pos = values.index(self.values[item.id])
        except ValueError:
            pos = -1
        new_value = values[(pos + 1) % len(values)]
        changed = new_value != self.values[item.id]
        self.values[item.id] = new_value
        return changed

    def append_search(self, ch: str) -> None:
        self.search += ch
        self._refilter()

    def backspace_search(self) -> None:
        if self.search:
            self.search = self.search[:-1]
            self._refilter()

    def clear_search(self) -> None:
        if self.search:
            self.search = ""
            self._refilter()

    def changes(self) -> dict[str, str]:
        return {
            key: value
            for key, value in self.values.items()
            if self._original_values.get(key) != value
        }

    def apply(self) -> None:
        self.applied = True

    def cancel(self) -> None:
        self.cancelled = True

    def visible_window(self) -> tuple[int, int]:
        if not self.visible:
            return (0, 0)
        max_visible = max(1, self.config.max_visible)
        start = max(0, min(self.selected_idx - max_visible // 2, len(self.visible) - max_visible))
        end = min(start + max_visible, len(self.visible))
        return (start, end)


def _format_setting_line(
    item: SettingItem,
    value: str,
    *,
    is_selected: bool,
    width: int,
    label_width: int,
) -> StyleAndTextTuples:
    prefix = "→ " if is_selected else "  "
    prefix_style = (
        "class:slash-completion-menu.marker.current"
        if is_selected
        else "class:slash-completion-menu.marker"
    )
    label_style = (
        "class:slash-completion-menu.command.current"
        if is_selected
        else "class:slash-completion-menu.command"
    )
    value_style = (
        "class:slash-completion-menu.meta.current"
        if is_selected
        else "class:slash-completion-menu.meta"
    )
    row_style = (
        "class:slash-completion-menu.row.current" if is_selected else "class:slash-completion-menu"
    )

    padded_label = item.label + " " * max(0, label_width - cell_width(item.label))
    used = cell_width(prefix) + label_width + 2
    value_text = truncate_to_width(value, max(0, width - used - 1), ellipsis="")
    pad = max(0, width - used - cell_width(value_text))
    return [
        (prefix_style, prefix),
        (label_style, padded_label),
        (row_style, "  "),
        (value_style, value_text),
        (row_style, " " * pad),
        ("", "\n"),
    ]


def _build_application(state: _SettingsListState) -> Application[None]:
    config = state.config

    def header_text() -> StyleAndTextTuples:
        out: StyleAndTextTuples = [
            ("class:slash-completion-menu.command.current", config.title),
            ("", "\n"),
        ]
        if config.enable_search:
            display = state.search or "(type to search)"
            out.append(("class:slash-completion-menu.meta", f"search: {display}"))
            out.append(("", "\n"))
        return out

    def items_text() -> StyleAndTextTuples:
        if not state.visible:
            return [("class:slash-completion-menu.meta", "  no matching settings"), ("", "\n")]

        width = 88
        start, end = state.visible_window()
        visible_items = [config.items[i] for i in state.visible]
        label_width = min(30, max(cell_width(item.label) for item in config.items))
        rows: StyleAndTextTuples = []
        for pos in range(start, end):
            item = visible_items[pos]
            rows.extend(
                _format_setting_line(
                    item,
                    state.current_value(item),
                    is_selected=pos == state.selected_idx,
                    width=width,
                    label_width=label_width,
                )
            )

        if start > 0 or end < len(state.visible):
            scroll_text = f"  ({state.selected_idx + 1}/{len(state.visible)})"
            rows.append(("class:slash-completion-menu.meta", scroll_text))
            rows.append(("", "\n"))

        selected = state.current_item
        if selected and selected.description:
            rows.append(("", "\n"))
            description = f"  {truncate_to_width(selected.description, width - 2)}"
            rows.append(("class:slash-completion-menu.meta", description))
            rows.append(("", "\n"))
        return rows

    def hint_text() -> StyleAndTextTuples:
        changed = state.changes()
        suffix = f" · {len(changed)} changed" if changed else ""
        return [("class:slash-completion-menu.meta", config.hint + suffix)]

    bindings = KeyBindings()

    def _redraw(event: KeyPressEvent) -> None:
        event.app.invalidate()

    @bindings.add("up")
    def _(event: KeyPressEvent) -> None:
        state.move(-1)
        _redraw(event)

    @bindings.add("down")
    def _(event: KeyPressEvent) -> None:
        state.move(1)
        _redraw(event)

    @bindings.add("enter")
    def _(event: KeyPressEvent) -> None:
        state.activate()
        _redraw(event)

    @bindings.add(" ")
    def _(event: KeyPressEvent) -> None:
        state.activate()
        _redraw(event)

    @bindings.add("c-d")
    def _(event: KeyPressEvent) -> None:
        state.apply()
        event.app.exit()

    @bindings.add("escape", eager=True)
    @bindings.add("c-c")
    def _(event: KeyPressEvent) -> None:
        state.cancel()
        event.app.exit()

    if config.enable_search:

        @bindings.add("backspace")
        def _(event: KeyPressEvent) -> None:
            state.backspace_search()
            _redraw(event)

        @bindings.add("c-u")
        def _(event: KeyPressEvent) -> None:
            state.clear_search()
            _redraw(event)

        @bindings.add("<any>")
        def _(event: KeyPressEvent) -> None:
            ch = event.data
            if ch and len(ch) == 1 and ch.isprintable() and ch != " ":
                state.append_search(ch)
                _redraw(event)

    header_height = 2 if config.enable_search else 1
    return Application(
        layout=Layout(
            HSplit(
                [
                    Window(
                        FormattedTextControl(header_text),
                        height=Dimension(min=header_height, max=header_height),
                        style="class:slash-completion-menu",
                    ),
                    Window(FormattedTextControl(items_text), style="class:slash-completion-menu"),
                    Window(
                        FormattedTextControl(hint_text),
                        height=Dimension(min=1, max=1),
                        style="class:slash-completion-menu",
                    ),
                ]
            )
        ),
        key_bindings=bindings,
        full_screen=False,
        style=get_prompt_style(),
        mouse_support=False,
    )


async def run_settings_list(config: SettingsListConfig) -> SettingsListResult | None:
    """Run an interactive settings list and return changed values.

    Returns ``None`` when cancelled. Applying with no changes returns an empty
    ``SettingsListResult`` so callers can distinguish apply vs cancel.
    """
    state = _SettingsListState(config)
    app = _build_application(state)
    await app.run_async()
    if state.cancelled or not state.applied:
        return None
    return SettingsListResult(changes=state.changes())
