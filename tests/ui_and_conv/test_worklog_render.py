from __future__ import annotations

from pythinker_core.tooling import BriefDisplayBlock
from rich.console import Console

from pythinker_code.tools.display import (
    BackgroundTaskDisplayBlock,
    DiffDisplayBlock,
    TodoDisplayBlock,
    TodoDisplayItem,
)
from pythinker_code.ui.shell.visualize._worklog import (
    WorkLogState,
    denied_error,
    render_display_blocks,
    render_worklog_entry,
    tool_style,
)


def _plain(renderable) -> str:
    console = Console(record=True, width=120, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_tool_style_maps_common_tools_to_professional_labels():
    assert tool_style("ReadFile").label == "Read"
    assert tool_style("Grep").label == "Search"
    assert tool_style("Edit").label == "Edit"
    assert tool_style("ApplyPatch").label == "Patch"
    assert tool_style("Bash").label == "Shell"
    assert tool_style("TodoWrite").label == "Todo"
    assert tool_style("Agent").label == "Subagent"
    assert tool_style("Agent").icon == "●"
    from pythinker_code.ui.theme import get_tui_tokens, set_active_theme

    set_active_theme("dark")
    assert tool_style("Agent").style == get_tui_tokens("dark").muted
    assert tool_style("AskUser").label == "Ask"
    assert tool_style("UnknownTool").label == "UnknownTool"


def test_running_entry_shows_state_label_tool_and_target():
    output = _plain(
        render_worklog_entry(
            label="Read",
            target="src/app.py",
            state=WorkLogState.RUNNING,
        )
    )

    assert "Read" in output
    assert "src/app.py" in output
    assert "running" in output.lower()


def test_failed_entry_renders_only_explicit_target_and_detail():
    output = _plain(
        render_worklog_entry(
            label="Shell",
            target="pytest tests/unit",
            state=WorkLogState.FAILED,
            detail="Command failed with exit code 1",
        )
    )

    assert "Shell" in output
    assert "pytest tests/unit" in output
    assert "failed" in output.lower()
    assert "Command failed with exit code 1" in output


def test_worklog_entry_uses_shared_status_language():
    from pythinker_code.ui.shell.components.render_utils import render_plain
    from pythinker_code.ui.shell.visualize._worklog import WorkLogState, render_worklog_entry

    output = render_plain(
        render_worklog_entry(
            label="Shell",
            target="pytest",
            state=WorkLogState.FAILED,
            detail="exit code 1",
        ),
        width=100,
    )
    assert "Shell" in output
    assert "pytest" in output
    assert "failed" in output.lower()
    assert "exit code 1" in output


def test_denied_error_detects_user_denials_without_matching_regular_failures():
    assert denied_error("user dismissed permission")
    assert denied_error("QuestionRejectedError: rejected")
    assert denied_error("rejected permission")
    assert denied_error("specified a rule")
    assert denied_error("denied")
    assert denied_error("denied: blocked by user")
    assert denied_error("Tool calls are disabled")
    assert not denied_error("command failed with exit code 1")
    assert not denied_error("Permission denied while opening file")


def test_todo_display_block_renders_statuses_as_card():
    output = _plain(
        render_display_blocks(
            [
                TodoDisplayBlock(
                    items=[
                        TodoDisplayItem(title="Inspect UI", status="done"),
                        TodoDisplayItem(title="Polish tools", status="in_progress"),
                        TodoDisplayItem(title="Run checks", status="pending"),
                    ]
                )
            ]
        )[0]
    )

    assert "Todos" in output
    assert "Inspect UI" in output
    assert "Polish tools" in output
    assert "Run checks" in output
    assert "✓" in output
    assert "→" in output
    assert "·" in output


def test_background_task_display_block_renders_compact_card():
    output = _plain(
        render_display_blocks(
            [
                BackgroundTaskDisplayBlock(
                    task_id="task-1",
                    kind="test",
                    status="running",
                    description="Run focused tests",
                )
            ]
        )[0]
    )

    assert "Background task" in output
    assert "task-1" in output
    assert "running" in output
    assert "Run focused tests" in output


def test_brief_display_block_renders_report_card_when_multiline():
    output = _plain(render_display_blocks([BriefDisplayBlock(text="Line one\n\nLine two")])[0])

    assert "Report" in output
    assert "Line one" in output
    assert "Line two" in output


def test_consecutive_diff_blocks_for_same_file_render_one_card():
    cards = render_display_blocks(
        [
            DiffDisplayBlock(path="src/app.py", old_text="a", new_text="b"),
            DiffDisplayBlock(path="src/app.py", old_text="x", new_text="x\ny"),
        ]
    )
    output = _plain(cards[0])

    assert len(cards) == 1
    assert "src/app.py" in output
    assert "+" in output
    assert "-" in output


def test_diff_blocks_render_compact_summary_first_card():
    cards = render_display_blocks(
        [
            DiffDisplayBlock(path="src/app.py", old_text="a\nb", new_text="a\nb\nc"),
            DiffDisplayBlock(path="src/app.py", old_text="x", new_text="y"),
        ]
    )
    output = _plain(cards[0])

    assert len(cards) == 1
    assert "src/app.py" in output
    assert "+2" in output
    assert "-1" in output
    assert "Diff +" not in output
