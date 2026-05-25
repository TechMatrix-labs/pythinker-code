"""Interactive model picker: provider-grouped, type-to-filter.

Shows every configured model in a single scrollable view, organized by
provider section headers. Typing filters models live (case-insensitive
substring against display name, model id, and provider label). Up/down skips
over headers so the cursor only ever lands on a real model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension

from pythinker_code.config import LLMModel


@dataclass(frozen=True, slots=True)
class ModelEntry:
    name: str  # config key (selection result)
    display: str  # display name shown to the user
    model_id: str  # raw model id (for matching)


@dataclass(frozen=True, slots=True)
class ProviderGroup:
    key: str  # raw provider key (e.g. "managed:lm-studio")
    label: str  # humanized label
    models: tuple[ModelEntry, ...]


class ModelPickerApp:
    """Single-pane model picker with type-to-filter."""

    def __init__(
        self,
        *,
        groups: list[ProviderGroup],
        current_model_name: str | None,
    ) -> None:
        self._groups = groups
        self._current = current_model_name
        self._filter = ""
        self._visible_models: list[ModelEntry] = []
        self._selected_idx = 0
        self._refilter(initial=True)
        self._app = self._build_app()

    async def run(self) -> str | None:
        return await self._app.run_async()

    # ------------------------------------------------------------------
    # Filtering / selection
    # ------------------------------------------------------------------

    def _matches(self, group: ProviderGroup, model: ModelEntry) -> bool:
        if not self._filter:
            return True
        needle = self._filter.lower()
        return (
            needle in model.display.lower()
            or needle in model.model_id.lower()
            or needle in group.label.lower()
        )

    def _refilter(self, *, initial: bool = False) -> None:
        previous = (
            self._visible_models[self._selected_idx].name
            if self._visible_models and 0 <= self._selected_idx < len(self._visible_models)
            else None
        )
        visible: list[ModelEntry] = []
        for group in self._groups:
            for model in group.models:
                if self._matches(group, model):
                    visible.append(model)
        self._visible_models = visible
        if not visible:
            self._selected_idx = 0
            return
        # Pick a sensible default cursor position.
        target = previous if not initial else self._current
        for i, m in enumerate(visible):
            if m.name == target:
                self._selected_idx = i
                return
        self._selected_idx = 0

    def _move(self, delta: int) -> None:
        if not self._visible_models:
            return
        n = len(self._visible_models)
        self._selected_idx = (self._selected_idx + delta) % n

    @property
    def _selected_model(self) -> ModelEntry | None:
        if not self._visible_models:
            return None
        return self._visible_models[self._selected_idx]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _list_fragments(self) -> StyleAndTextTuples:
        fragments, _ = self._render_with_cursor()
        return fragments

    def _cursor_position(self) -> Point:
        _, row = self._render_with_cursor()
        return Point(x=0, y=row)

    def _render_with_cursor(self) -> tuple[StyleAndTextTuples, int]:
        """Render the list and return (fragments, cursor_row).

        cursor_row is the line index of the selected model — used to keep the
        viewport scrolled so the selected row is visible.
        """
        if not self._visible_models:
            return ([("class:option", "  (no models match filter)\n")], 0)

        selected_name = self._selected_model.name if self._selected_model else None
        out: StyleAndTextTuples = []
        cursor_row = 0
        row = 0
        for group in self._groups:
            visible = [m for m in group.models if self._matches(group, m)]
            if not visible:
                continue
            out.append(("class:provider-header", f"── {group.label} ─ {len(visible)}\n"))
            row += 1
            for model in visible:
                marker = "  (current)" if model.name == self._current else ""
                if model.name == selected_name:
                    cursor_row = row
                    out.append(("class:selected-row", f"  > {model.display}{marker}\n"))
                else:
                    out.append(("class:option", f"    {model.display}{marker}\n"))
                row += 1
        return (out, cursor_row)

    def _header_fragments(self) -> StyleAndTextTuples:
        total_visible = len(self._visible_models)
        total_all = sum(len(g.models) for g in self._groups)
        if self._filter:
            count_label = f" {total_visible} of {total_all} matching "
        else:
            count_label = f" {total_all} models "
        return [
            ("class:header.title", " SELECT MODEL "),
            ("class:header.meta", count_label),
        ]

    def _filter_fragments(self) -> StyleAndTextTuples:
        prompt = " Filter: "
        if self._filter:
            return [
                ("class:filter.label", prompt),
                ("class:filter.text", self._filter),
                ("class:filter.cursor", "█"),
            ]
        return [
            ("class:filter.label", prompt),
            ("class:filter.hint", "(type to filter, ↑↓ navigate, Enter select, Esc cancel)"),
        ]

    def _footer_fragments(self) -> StyleAndTextTuples:
        return [
            ("class:footer.text", " ↑↓ move "),
            ("class:footer.text", "· Enter select "),
            ("class:footer.text", "· Backspace edit "),
            ("class:footer.text", "· Esc clear/cancel "),
            ("class:footer.text", "· Ctrl+C cancel "),
        ]

    # ------------------------------------------------------------------
    # Application wiring
    # ------------------------------------------------------------------

    def _build_app(self) -> Application[str | None]:
        kb = KeyBindings()

        @kb.add("up")
        def _(event: KeyPressEvent) -> None:
            self._move(-1)

        @kb.add("down")
        def _(event: KeyPressEvent) -> None:
            self._move(1)

        @kb.add("pageup")
        def _(event: KeyPressEvent) -> None:
            self._move(-10)

        @kb.add("pagedown")
        def _(event: KeyPressEvent) -> None:
            self._move(10)

        @kb.add("enter", eager=True)
        def _(event: KeyPressEvent) -> None:
            chosen = self._selected_model
            if chosen is None:
                return  # nothing matches the filter — Enter is a no-op
            event.app.exit(result=chosen.name)

        @kb.add("c-c")
        def _(event: KeyPressEvent) -> None:
            event.app.exit(result=None)

        @kb.add("escape", eager=True)
        def _(event: KeyPressEvent) -> None:
            if self._filter:
                self._filter = ""
                self._refilter()
            else:
                event.app.exit(result=None)

        @kb.add("backspace")
        def _(event: KeyPressEvent) -> None:
            if self._filter:
                self._filter = self._filter[:-1]
                self._refilter()

        # Catch printable characters to extend the filter.
        @kb.add("<any>")
        def _(event: KeyPressEvent) -> None:
            data = event.data or ""
            if len(data) == 1 and data.isprintable():
                self._filter += data
                self._refilter()

        header = Window(
            FormattedTextControl(self._header_fragments),
            height=1,
            style="class:header",
        )
        filter_bar = Window(
            FormattedTextControl(self._filter_fragments),
            height=1,
            style="class:filter",
        )
        body = Window(
            FormattedTextControl(
                self._list_fragments,
                focusable=True,
                get_cursor_position=self._cursor_position,
            ),
            wrap_lines=False,
            height=Dimension(preferred=20, min=5),
        )
        footer = Window(
            FormattedTextControl(self._footer_fragments),
            height=1,
            style="class:footer",
        )

        return Application(
            layout=Layout(HSplit([header, filter_bar, body, footer])),
            key_bindings=kb,
            full_screen=False,
            erase_when_done=True,
            style=_model_picker_style(),
        )


def _model_picker_style():
    from prompt_toolkit.styles import Style as PTKStyle

    from pythinker_code.ui.theme import get_task_browser_style, get_tui_tokens

    base = get_task_browser_style()
    tokens = get_tui_tokens()
    extra = PTKStyle.from_dict(
        {
            "provider-header": f"{tokens.muted} bold",
            "selected-row": f"bg:{tokens.selected_bg} {tokens.info} bold",
            "option": "",
            "filter": f"bg:{tokens.tool_pending_bg}",
            "filter.label": f"bg:{tokens.tool_pending_bg} {tokens.muted}",
            "filter.text": f"bg:{tokens.tool_pending_bg} {tokens.info} bold",
            "filter.cursor": f"bg:{tokens.tool_pending_bg} {tokens.accent}",
            "filter.hint": f"bg:{tokens.tool_pending_bg} {tokens.dim} italic",
        }
    )
    return PTKStyle([*base.style_rules, *extra.style_rules])


def build_provider_groups(
    *,
    config_models: Mapping[str, LLMModel],
    label_for: Callable[[str], str],
) -> list[ProviderGroup]:
    """Group config.models by provider key, alpha-sorted by label/display.

    `label_for(provider_key) -> str` resolves the human label for a provider.
    """
    grouped: dict[str, list[ModelEntry]] = {}
    for name in sorted(config_models):
        cfg = config_models[name]
        provider_key = cfg.provider
        model_id = cfg.model
        display = cfg.display_name or model_id
        grouped.setdefault(provider_key, []).append(
            ModelEntry(name=name, display=display, model_id=model_id)
        )

    groups = [
        ProviderGroup(key=key, label=label_for(key), models=tuple(entries))
        for key, entries in grouped.items()
    ]
    groups.sort(key=lambda g: g.label.lower())
    return groups
