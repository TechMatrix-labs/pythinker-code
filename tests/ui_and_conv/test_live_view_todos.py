from __future__ import annotations

import importlib

from pythinker_core.message import ToolCall
from pythinker_core.tooling import ToolResult, ToolReturnValue
from rich.color import Color
from rich.console import Console, Group
from rich.style import Style

from pythinker_code.tools.display import TodoDisplayBlock, TodoDisplayItem
from pythinker_code.ui.shell.visualize import _LiveView
from pythinker_code.ui.theme import tui_rich_style
from pythinker_code.wire.types import StatusUpdate, TurnBegin

_live_view_module = importlib.import_module("pythinker_code.ui.shell.visualize._live_view")


def _render(renderable) -> str:
    console = Console(width=100, record=True, highlight=False)
    console.print(renderable)
    return console.export_text()


def _style_for(renderable, text: str) -> Style:
    start = renderable.plain.index(text)
    end = start + len(text)
    span = next(span for span in renderable.spans if span.start <= start and span.end >= end)
    return Style.parse(span.style) if isinstance(span.style, str) else span.style


def _color_hex(color: Color | None) -> str:
    assert color is not None
    triplet = color.triplet
    assert triplet is not None
    return triplet.hex.lower()


def _span_colors_for(renderable, text: str) -> set[str]:
    start = renderable.plain.index(text)
    end = start + len(text)
    colors: set[str] = set()
    for span in renderable.spans:
        if span.end <= start or span.start >= end:
            continue
        style = Style.parse(span.style) if isinstance(span.style, str) else span.style
        if style.color is not None:
            colors.add(_color_hex(style.color))
    return colors


def _todo_call(call_id: str = "todo-1") -> ToolCall:
    return ToolCall(
        id=call_id,
        function=ToolCall.FunctionBody(
            name="SetTodoList",
            arguments='{"todos":[{"title":"Implement pinned todos","status":"in_progress"}]}',
        ),
    )


def _todo_result(call_id: str = "todo-1") -> ToolResult:
    return ToolResult(
        tool_call_id=call_id,
        return_value=ToolReturnValue(
            is_error=False,
            output="Todo list updated",
            message="Todo list updated",
            display=[
                TodoDisplayBlock(
                    items=[
                        TodoDisplayItem(title="Implement pinned todos", status="in_progress"),
                        TodoDisplayItem(title="Explore UI", status="done"),
                        TodoDisplayItem(title="Ask question", status="done"),
                        TodoDisplayItem(title="Sketch behavior", status="done"),
                        TodoDisplayItem(title="Write tests", status="done"),
                        TodoDisplayItem(title="Run checks", status="done"),
                    ]
                )
            ],
        ),
    )


def test_todo_update_pins_current_task_under_activity_line(monkeypatch) -> None:
    now = 1000.0
    monkeypatch.setattr(_live_view_module.time, "monotonic", lambda: now)
    # Pin the animated star marker to its static ``✶`` frame for a deterministic
    # assertion on the activity-line content.
    monkeypatch.setenv("PYTHINKER_REDUCED_MOTION", "1")
    view = _LiveView(StatusUpdate(context_tokens=10_000))
    view.dispatch_wire_message(TurnBegin(user_input="work"))
    view.dispatch_wire_message(_todo_call())
    view.dispatch_wire_message(_todo_result())

    now = 1460.0
    rendered = _render(view._working_indicator())

    assert "✶ Implement pinned todos… (7m 40s · ↓ 10k tokens)" in rendered
    assert rendered.count("Implement pinned todos") == 1
    assert "⎿  ◼ Implement pinned todos" not in rendered
    assert "⎿  ✔ Explore UI" in rendered
    assert "✔ Write tests" in rendered
    assert "… +1 completed" not in rendered
    assert "todos(" not in rendered
    assert "Accomplishing" not in rendered


def test_active_todo_activity_line_alternates_with_spinner_verb(monkeypatch) -> None:
    now = 1000.0
    monkeypatch.setattr(_live_view_module.time, "monotonic", lambda: now)
    monkeypatch.setenv("PYTHINKER_REDUCED_MOTION", "1")
    view = _LiveView(StatusUpdate(context_tokens=10_000))
    view.dispatch_wire_message(TurnBegin(user_input="work"))
    view.dispatch_wire_message(_todo_call())
    view.dispatch_wire_message(_todo_result())

    now = 1465.0
    rendered = _render(view._working_indicator())

    assert f"✶ {_live_view_module.spinner_message(now)} (7m 45s · ↓ 10k tokens)" in rendered
    assert "⎿  ◼ Implement pinned todos" in rendered
    assert "✔ Explore UI" in rendered


def test_active_todo_activity_line_uses_muted_orange() -> None:
    view = _LiveView(StatusUpdate(context_tokens=10_000))

    line = view._todo_activity_line("Implement pinned todos", elapsed_s=0.88, width=100)

    assert _span_colors_for(line, "Implement pinned todos") == {"#e6b450"}


def test_active_pinned_todo_row_uses_shimmer_palette(monkeypatch) -> None:
    monkeypatch.delenv("PYTHINKER_REDUCED_MOTION", raising=False)
    view = _LiveView(StatusUpdate())

    row = view._pinned_todo_row(
        TodoDisplayItem(title="Implement pinned todos", status="in_progress"),
        is_first=True,
        width=100,
        elapsed_s=0.88,
    )

    assert _span_colors_for(row, "Implement pinned todos") >= {
        "#e6b450",
        "#ebc46e",
        "#f3d89a",
    }


def test_non_first_pinned_rows_indent_under_first_title() -> None:
    view = _LiveView(StatusUpdate())

    first = view._pinned_todo_row(
        TodoDisplayItem(title="Lead task", status="in_progress"),
        is_first=True,
        width=100,
        elapsed_s=0.0,
    )
    later = view._pinned_todo_row(
        TodoDisplayItem(title="Next task", status="pending"),
        is_first=False,
        width=100,
    )

    # First row carries the ⎿ gutter; later rows indent so their checkbox sits
    # under the first row's title (icons intentionally not aligned).
    assert first.plain.startswith("  ⎿  ◼ ")
    assert later.plain.startswith("       ◻ ")
    assert later.plain.index("◻") == first.plain.index("Lead task")


def test_successful_todo_tool_card_is_suppressed() -> None:
    view = _LiveView(StatusUpdate())
    view.dispatch_wire_message(TurnBegin(user_input="work"))
    view.dispatch_wire_message(_todo_call())
    assert len(view._tool_call_blocks) == 1

    view.dispatch_wire_message(_todo_result())

    assert view._tool_call_blocks == {}
    rendered = _render(Group(*view.compose_agent_output()))
    assert "Implement pinned todos" in rendered
    assert "SetTodoList" not in rendered


def test_completed_todo_row_is_muted_and_struck() -> None:
    view = _LiveView(StatusUpdate())

    row = view._pinned_todo_row(
        TodoDisplayItem(title="Finished task", status="done"), is_first=True, width=80
    )
    title_style = _style_for(row, "Finished task")

    assert title_style.strike is True
    assert title_style.color == tui_rich_style("muted").color


def test_toggle_pinned_todos_hides_todo_rows() -> None:
    view = _LiveView(StatusUpdate())
    view.dispatch_wire_message(TurnBegin(user_input="work"))
    view.dispatch_wire_message(_todo_call())
    view.dispatch_wire_message(_todo_result())

    assert view.toggle_pinned_todos() is False

    rendered = _render(view._working_indicator())
    assert "Implement pinned todos" not in rendered
    assert "…" in rendered
