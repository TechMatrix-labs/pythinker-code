from __future__ import annotations

from rich.console import Console

from pythinker_code.ui.shell.console import console as shell_console
from pythinker_code.ui.shell.visualize import _live_view as live_view_module
from pythinker_code.ui.shell.visualize import _LiveView, _PromptLiveView
from pythinker_code.wire.types import Notification, StatusUpdate, TurnBegin


def _render(renderable) -> str:
    console = Console(width=100, record=True, highlight=False)
    console.print(renderable)
    return console.export_text()


def _notification(index: int = 1, *, source_kind: str = "background_task") -> Notification:
    return Notification(
        id=f"n{index:07d}",
        category="task",
        type="task.completed",
        source_kind=source_kind,
        source_id=f"b{index:07d}",
        title=f"Background task completed: build project {index}",
        body=(f"Task ID: b{index:07d}\nStatus: completed\nDescription: build project {index}"),
        severity="success",
        created_at=123.456,
        payload={"task_id": f"b{index:07d}"},
    )


def test_live_view_renders_notification_block():
    view = _LiveView(StatusUpdate())

    view.dispatch_wire_message(_notification())

    rendered = _render(view.compose())
    assert "Background task completed: build project 1" in rendered
    assert "Task ID: b0000001" in rendered
    assert "Status: completed" in rendered
    assert "..." in rendered


def test_working_indicator_uses_turn_elapsed_time(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(live_view_module.time, "monotonic", lambda: now)
    view = _LiveView(StatusUpdate())
    view.dispatch_wire_message(TurnBegin(user_input="scan"))

    now = 1012.0
    rendered = _render(view._working_indicator())

    assert "12s" in rendered
    assert "4h" not in rendered


def test_working_indicator_uses_rotating_thinking_words(monkeypatch):
    now = 90.0
    monkeypatch.setattr(live_view_module.time, "monotonic", lambda: now)
    view = _LiveView(StatusUpdate())
    view.dispatch_wire_message(TurnBegin(user_input="scan"))

    rendered = _render(view._working_indicator())

    assert "Accomplishing…" in rendered
    assert "Working" not in rendered


def test_working_indicator_rotates_thinking_words_every_ten_minutes(monkeypatch):
    now = 0.0
    monkeypatch.setattr(live_view_module.time, "monotonic", lambda: now)
    view = _LiveView(StatusUpdate())
    view.dispatch_wire_message(TurnBegin(user_input="scan"))

    first = _render(view._working_indicator())
    now = 599.9
    still_first = _render(view._working_indicator())
    now = 600.0
    second = _render(view._working_indicator())

    assert "Accomplishing…" in first
    assert "Accomplishing…" in still_first
    assert "Actioning…" in second


def test_prompt_live_view_suppresses_background_task_notifications(monkeypatch):
    view = object.__new__(_PromptLiveView)
    view._pending_local_steer_count = 0
    view._btw_spinner = None

    forwarded: list[Notification] = []
    monkeypatch.setattr(
        _LiveView, "dispatch_wire_message", lambda _self, msg: forwarded.append(msg)
    )

    view.dispatch_wire_message(_notification())

    assert forwarded == []


def test_prompt_live_view_keeps_non_background_task_notifications(monkeypatch):
    view = object.__new__(_PromptLiveView)
    view._pending_local_steer_count = 0
    view._btw_spinner = None

    forwarded: list[Notification] = []
    monkeypatch.setattr(
        _LiveView, "dispatch_wire_message", lambda _self, msg: forwarded.append(msg)
    )

    notification = _notification(source_kind="system")
    view.dispatch_wire_message(notification)

    assert forwarded == [notification]


def test_cleanup_flushes_notifications_to_terminal_history(monkeypatch):
    view = _LiveView(StatusUpdate())
    view.dispatch_wire_message(_notification())

    printed = []
    monkeypatch.setattr(shell_console, "print", lambda *args, **kwargs: printed.extend(args))

    view.cleanup(is_interrupt=False)

    assert not view._notification_blocks
    assert not view._live_notification_blocks
    assert printed
    rendered = _render(printed[0])
    assert "Background task completed: build project 1" in rendered
    assert "Task ID: b0000001" in rendered


def test_cleanup_flushes_all_notifications_even_when_live_view_shows_only_latest_four(monkeypatch):
    view = _LiveView(StatusUpdate())
    for index in range(1, 6):
        view.dispatch_wire_message(_notification(index))

    live_rendered = _render(view.compose())
    assert "Background task completed: build project 1" not in live_rendered
    for index in range(2, 6):
        assert f"Background task completed: build project {index}" in live_rendered

    printed = []
    monkeypatch.setattr(shell_console, "print", lambda *args, **kwargs: printed.extend(args))

    view.cleanup(is_interrupt=False)

    assert len(printed) == 5
    rendered = "\n".join(_render(item) for item in printed)
    for index in range(1, 6):
        assert f"Background task completed: build project {index}" in rendered
