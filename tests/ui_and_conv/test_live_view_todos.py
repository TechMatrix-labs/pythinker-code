from __future__ import annotations

import importlib

from pythinker_core.message import ToolCall
from pythinker_core.tooling import ToolResult, ToolReturnValue
from rich.console import Console, Group

from pythinker_code.tools.display import TodoDisplayBlock, TodoDisplayItem
from pythinker_code.ui.shell.visualize import _LiveView
from pythinker_code.wire.types import StatusUpdate, TurnBegin

_live_view_module = importlib.import_module("pythinker_code.ui.shell.visualize._live_view")


def _render(renderable) -> str:
    console = Console(width=100, record=True, highlight=False)
    console.print(renderable)
    return console.export_text()


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
    view = _LiveView(StatusUpdate())
    view.dispatch_wire_message(TurnBegin(user_input="work"))
    view.dispatch_wire_message(_todo_call())
    view.dispatch_wire_message(_todo_result())

    rendered = _render(view._working_indicator())

    assert "✽ Implement pinned todos…" in rendered
    assert "⎿  ◼ Implement pinned todos" in rendered
    assert "✔ Explore UI" in rendered
    assert "✔ Write tests" in rendered
    assert "… +1 completed" in rendered
    assert "todos(" not in rendered
    assert "Accomplishing" not in rendered


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


def test_toggle_pinned_todos_hides_todo_rows() -> None:
    view = _LiveView(StatusUpdate())
    view.dispatch_wire_message(TurnBegin(user_input="work"))
    view.dispatch_wire_message(_todo_call())
    view.dispatch_wire_message(_todo_result())

    assert view.toggle_pinned_todos() is False

    rendered = _render(view._working_indicator())
    assert "Implement pinned todos" not in rendered
    assert "…" in rendered
