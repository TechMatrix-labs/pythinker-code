"""Reusable selector framework for Pythinker.

Provides a generic, prompt_toolkit-backed selector that mirrors the shape of
the existing :mod:`pythinker_code.ui.shell.model_picker` but works on any
list of items. Specific dialogs (theme, thinking, settings, oauth-provider)
build on this so they all share the same key bindings, search filter
behavior, header/footer chrome, and theme tokens.

Why a new framework rather than reuse ``prompt_toolkit.shortcuts.choice_input``?

* ChoiceInput doesn't support type-to-filter, which we want for any
  selector with > 5 items.
* It doesn't theme via Pythinker's :func:`get_prompt_style` palette so the
  visual treatment drifts from the rest of the shell.
* It doesn't expose a header line for explanatory text or a hint footer.

Public API:

* :class:`SelectorItem` — one row.
* :class:`SelectorConfig` — title + items + optional preselection / hint.
* :func:`run_selector` — async; returns the selected value or ``None``.
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

from pythinker_code.ui.theme import get_prompt_style

__all__ = [
    "SelectorConfig",
    "SelectorItem",
    "run_selector",
]


@dataclass(frozen=True, slots=True)
class SelectorItem[T]:
    """A row in a selector.

    Attributes:
        value: Returned by :func:`run_selector` when this item is chosen.
        label: Bold primary column, e.g. ``"dark"`` or ``"claude-opus-4-7"``.
        description: Optional muted secondary column shown to the right.
        is_current: Marks the item as the active selection — pre-selected
            on open and labelled ``(current)`` in the description.
    """

    value: T
    label: str
    description: str = ""
    is_current: bool = False


@dataclass(frozen=True, slots=True)
class SelectorConfig[T]:
    """Static configuration for a selector dialog."""

    title: str
    items: Sequence[SelectorItem[T]]
    """Source rows. May be empty — the selector will show a placeholder."""

    hint: str = "↑↓ navigate · Enter select · Esc cancel · type to filter"
    """Footer shown below the item list."""

    enable_filter: bool = True
    """When False, type-to-filter is disabled (useful for tiny selectors)."""


def _format_item_line[T](
    item: SelectorItem[T],
    *,
    is_selected: bool,
    width: int,
) -> StyleAndTextTuples:
    """One row in the selector — marker + label + description.

    Reuses the same ``slash-completion-menu`` style classes as the prompt's
    completion menu so the visual treatment is consistent.
    """
    marker = "› " if is_selected else "  "
    marker_style = (
        "class:slash-completion-menu.marker.current"
        if is_selected
        else "class:slash-completion-menu.marker"
    )
    label_style = (
        "class:slash-completion-menu.command.current"
        if is_selected
        else "class:slash-completion-menu.command"
    )
    meta_style = (
        "class:slash-completion-menu.meta.current"
        if is_selected
        else "class:slash-completion-menu.meta"
    )
    row_bg = (
        "class:slash-completion-menu.row.current" if is_selected else "class:slash-completion-menu"
    )

    desc_parts: list[str] = []
    if item.is_current:
        desc_parts.append("(current)")
    if item.description:
        desc_parts.append(item.description)
    description = " ".join(desc_parts)

    label = item.label
    gap = "  "
    # Width budget: marker(2) + label + gap(2) + description + trailing pad
    used = len(marker) + len(label) + len(gap) + len(description)
    pad = max(0, width - used)
    return [
        (marker_style, marker),
        (label_style, label),
        (row_bg, gap),
        (meta_style, description),
        (row_bg, " " * pad),
        ("", "\n"),
    ]


class _SelectorState[T]:
    """Internal state for the selector application."""

    def __init__(self, config: SelectorConfig[T]) -> None:
        self.config = config
        self.filter = ""
        self.selected_idx = 0
        self.visible: list[SelectorItem[T]] = []
        self.result: T | None = None
        self.cancelled = False
        self._refilter(initial=True)

    def _matches(self, item: SelectorItem[T]) -> bool:
        if not self.filter:
            return True
        needle = self.filter.lower()
        return needle in item.label.lower() or needle in item.description.lower()

    def _refilter(self, *, initial: bool = False) -> None:
        previous_value = None
        if not initial and self.visible and 0 <= self.selected_idx < len(self.visible):
            previous_value = self.visible[self.selected_idx].value

        self.visible = [item for item in self.config.items if self._matches(item)]

        if not self.visible:
            self.selected_idx = 0
            return

        # Try to preserve the selected value across filter edits.
        if previous_value is not None:
            for i, item in enumerate(self.visible):
                if item.value == previous_value:
                    self.selected_idx = i
                    return

        # On initial open, prefer the item flagged is_current.
        if initial:
            for i, item in enumerate(self.visible):
                if item.is_current:
                    self.selected_idx = i
                    return

        # Fall back to the first visible row.
        self.selected_idx = 0

    def move(self, delta: int) -> None:
        if not self.visible:
            return
        self.selected_idx = (self.selected_idx + delta) % len(self.visible)

    def commit(self) -> bool:
        if not self.visible:
            return False
        self.result = self.visible[self.selected_idx].value
        return True

    def append_filter(self, ch: str) -> None:
        self.filter += ch
        self._refilter()

    def backspace_filter(self) -> None:
        if self.filter:
            self.filter = self.filter[:-1]
            self._refilter()

    def clear_filter(self) -> None:
        if self.filter:
            self.filter = ""
            self._refilter()


def _build_application[T](state: _SelectorState[T]) -> Application[None]:
    config = state.config

    def header_text() -> StyleAndTextTuples:
        out: StyleAndTextTuples = [
            ("class:slash-completion-menu.command.current", config.title),
            ("", "\n"),
        ]
        if config.enable_filter:
            filter_display = state.filter or "(type to filter)"
            out.append(("class:slash-completion-menu.meta", f"filter: {filter_display}"))
            out.append(("", "\n"))
        return out

    def items_text() -> StyleAndTextTuples:
        if not state.visible:
            return [
                ("class:slash-completion-menu.meta", "  no matches"),
                ("", "\n"),
            ]
        # Width is provided by prompt_toolkit during render, but Window
        # control APIs don't pass it here — use a reasonable default; the
        # row-level background handles trailing fill for any extra cells.
        width = 80
        rows: StyleAndTextTuples = []
        for i, item in enumerate(state.visible):
            rows.extend(_format_item_line(item, is_selected=i == state.selected_idx, width=width))
        return rows

    def hint_text() -> StyleAndTextTuples:
        return [("class:slash-completion-menu.meta", config.hint)]

    bindings = KeyBindings()

    def on_up(event: KeyPressEvent) -> None:
        state.move(-1)
        event.app.invalidate()

    def on_down(event: KeyPressEvent) -> None:
        state.move(1)
        event.app.invalidate()

    def on_enter(event: KeyPressEvent) -> None:
        if state.commit():
            event.app.exit()

    def on_cancel(event: KeyPressEvent) -> None:
        state.cancelled = True
        event.app.exit()

    bindings.add("up")(on_up)
    bindings.add("down")(on_down)
    bindings.add("enter")(on_enter)
    bindings.add("escape", eager=True)(on_cancel)
    bindings.add("c-c")(on_cancel)
    bindings.add("c-d")(on_cancel)

    if config.enable_filter:

        def on_backspace(event: KeyPressEvent) -> None:
            state.backspace_filter()
            event.app.invalidate()

        def on_clear(event: KeyPressEvent) -> None:
            state.clear_filter()
            event.app.invalidate()

        def on_any(event: KeyPressEvent) -> None:
            ch = event.data
            if ch and len(ch) == 1 and ch.isprintable():
                state.append_filter(ch)
                event.app.invalidate()

        bindings.add("backspace")(on_backspace)
        bindings.add("c-u")(on_clear)
        bindings.add("<any>")(on_any)

    layout = Layout(
        HSplit(
            [
                Window(
                    FormattedTextControl(header_text),
                    height=Dimension(min=2, max=2),
                    style="class:slash-completion-menu",
                ),
                Window(
                    FormattedTextControl(items_text),
                    style="class:slash-completion-menu",
                ),
                Window(
                    FormattedTextControl(hint_text),
                    height=Dimension(min=1, max=1),
                    style="class:slash-completion-menu",
                ),
            ]
        )
    )

    return Application(
        layout=layout,
        key_bindings=bindings,
        full_screen=False,
        style=get_prompt_style(),
        mouse_support=False,
    )


async def run_selector[T](config: SelectorConfig[T]) -> T | None:
    """Show *config* as an interactive selector. Returns the chosen value
    or ``None`` if the user cancelled.

    Empty selectors (no items, no items match the filter) still let the user
    cancel — they just can't commit.
    """
    state: _SelectorState[T] = _SelectorState(config)
    app = _build_application(state)
    await app.run_async()
    if state.cancelled or state.result is None:
        return None
    return state.result
