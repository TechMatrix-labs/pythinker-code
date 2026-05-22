"""Smoke tests for the Pythinker ported tool renderers.

These tests render each builtin through ``ToolExecutionComponent`` and assert
the human-readable output contains the expected fragments. They are not
pixel-snapshots: tweaking exact spacing/styling is fine, but the substantive
information (tool name, path, key args, result preview, expansion hint) must
remain visible.
"""

from __future__ import annotations

import pytest

from pythinker_code.ui.shell.components import (
    ToolExecutionComponent,
    compute_edit_diff_string,
    render_diff,
    render_plain,
)
from pythinker_code.ui.shell.tool_renderers import (
    ToolResultPayload,
    clear_tool_renderers,
    get_tool_renderer,
    register_builtin_renderers,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    clear_tool_renderers()
    register_builtin_renderers()
    yield
    clear_tool_renderers()


def _render(
    tool: str,
    args: dict,
    *,
    output: str = "",
    is_error: bool = False,
    expanded: bool = False,
    width: int = 100,
) -> str:
    defn = get_tool_renderer(tool)
    assert defn is not None, f"renderer not registered for {tool!r}"
    comp = ToolExecutionComponent(tool, "tc-1", definition=defn, cwd="/repo")
    comp.update_args(args)
    comp.set_args_complete()
    comp.mark_execution_started()
    comp.set_result(ToolResultPayload(text=output, is_error=is_error))
    comp.set_expanded(expanded)
    return render_plain(comp.render(), width=width)


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_renders_path_and_range():
    rendered = _render(
        "ReadFile",
        {"path": "/repo/src/foo.py", "line_offset": 10, "n_lines": 30},
        output="line1\nline2",
    )
    assert "read" in rendered
    assert "src/foo.py" in rendered
    assert ":10-39" in rendered
    assert "Read 2 lines" in rendered


def test_read_collapses_long_output_with_hint():
    body = "\n".join(f"line {i}" for i in range(20))
    rendered = _render("ReadFile", {"path": "/repo/x.py"}, output=body)
    assert "Read 20 lines" in rendered
    assert "line 0" in rendered
    assert "more lines" in rendered  # collapse hint


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


def test_write_shows_path_and_content_preview():
    rendered = _render(
        "WriteFile",
        {"path": "/repo/new.py", "content": "def f():\n    return 1\n"},
        output="Successfully wrote",
    )
    assert "write" in rendered
    assert "new.py" in rendered
    assert "def f():" in rendered


def test_write_error_surfaced():
    rendered = _render(
        "WriteFile",
        {"path": "/repo/new.py", "content": "x"},
        output="Permission denied",
        is_error=True,
    )
    assert "Permission denied" in rendered


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


def test_edit_renders_inline_diff():
    rendered = _render(
        "StrReplaceFile",
        {"path": "/repo/foo.py", "edit": {"old": "return 1", "new": "return 2"}},
    )
    assert "Update" in rendered
    assert "foo.py" in rendered
    assert "Removed 1 line" in rendered
    assert "Added 1 line" in rendered
    assert "return 1" in rendered
    assert "return 2" in rendered
    assert "---" in rendered


def test_edit_multi_count_in_header():
    rendered = _render(
        "StrReplaceFile",
        {
            "path": "/repo/foo.py",
            "edit": [
                {"old": "a", "new": "b"},
                {"old": "c", "new": "d"},
            ],
        },
    )
    assert "(2 edits)" in rendered


# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------


def test_grep_renders_pattern_and_path():
    rendered = _render(
        "Grep",
        {"pattern": "def\\s+", "path": "/repo/src", "glob": "*.py"},
        output="src/foo.py:10: def hello():",
    )
    assert "grep" in rendered
    assert "/def\\s+/" in rendered
    assert "src" in rendered
    assert "(*.py)" in rendered


# ---------------------------------------------------------------------------
# find / glob
# ---------------------------------------------------------------------------


def test_glob_renders_pattern_and_directory():
    rendered = _render(
        "Glob",
        {"pattern": "**/*.py", "directory": "/repo/src"},
        output="src/a.py\nsrc/b.py",
    )
    assert "find" in rendered
    assert "**/*.py" in rendered


# ---------------------------------------------------------------------------
# bash / shell
# ---------------------------------------------------------------------------


def test_shell_renders_command_and_output():
    rendered = _render("Shell", {"command": "ls -la", "timeout": 60}, output="total 0")
    assert "$ ls -la" in rendered
    assert "total 0" in rendered


def test_shell_collapses_long_command_and_reports_output_lines():
    command = "\n".join(["echo first", "echo second", "echo third"])
    output = "\n".join(f"line {i}" for i in range(8))
    rendered = _render("Shell", {"command": command, "timeout": 60}, output=output)
    assert "echo first" in rendered
    assert "echo second" in rendered
    assert "echo third" not in rendered
    assert "8 lines · ctrl+e expand" in rendered


def test_shell_uses_comment_label_for_long_script():
    command = "# build assets\n" + "\n".join(f"echo {i}" for i in range(5))
    rendered = _render("Shell", {"command": command, "timeout": 60}, output="ok")
    assert "$ build assets" in rendered
    assert "echo 0" not in rendered


def test_shell_shows_timeout_only_when_nondefault():
    short = _render("Shell", {"command": "echo x", "timeout": 60}, output="x")
    assert "timeout" not in short
    long = _render("Shell", {"command": "echo x", "timeout": 600}, output="x")
    assert "timeout 600s" in long


def test_shell_background_marker():
    rendered = _render(
        "Shell",
        {"command": "sleep 100", "run_in_background": True, "description": "watch"},
        output="started",
    )
    assert "background: watch" in rendered


# ---------------------------------------------------------------------------
# diff component
# ---------------------------------------------------------------------------


def test_compute_edit_diff_string_basic():
    result = compute_edit_diff_string("a\nb\nc\n", "a\nB\nc\n")
    assert "-" in result.diff
    assert "+" in result.diff
    assert result.first_changed_line == 2


def test_render_diff_colorizes_added_removed():
    diff = compute_edit_diff_string("hello\n", "world\n").diff
    plain = render_plain(render_diff(diff), width=60)
    assert "hello" in plain
    assert "world" in plain


# ---------------------------------------------------------------------------
# Agent (subagent)
# ---------------------------------------------------------------------------


def test_agent_renders_type_description_and_prompt_preview():
    rendered = _render(
        "Agent",
        {
            "subagent_type": "code-architect",
            "description": "design auth flow",
            "prompt": "Design the OAuth flow with PKCE\nAdditional context...",
        },
        output="Plan ready",
    )
    assert "subagent" in rendered
    assert "code-architect" in rendered
    assert "design auth flow" in rendered
    assert "Design the OAuth flow with PKCE" in rendered


# ---------------------------------------------------------------------------
# AskUserQuestion
# ---------------------------------------------------------------------------


def test_ask_user_renders_question_and_options():
    rendered = _render(
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question": "Which auth method?",
                    "options": [
                        {"label": "OAuth"},
                        {"label": "API key"},
                    ],
                }
            ]
        },
    )
    assert "ask user" in rendered
    assert "Which auth method?" in rendered
    assert "OAuth" in rendered
    assert "API key" in rendered


# ---------------------------------------------------------------------------
# Think
# ---------------------------------------------------------------------------


def test_think_renders_thought_body():
    rendered = _render("Think", {"thought": "First, check the file layout.\nThen draft a fix."})
    assert "think" in rendered
    assert "First, check the file layout." in rendered


# ---------------------------------------------------------------------------
# SetTodoList
# ---------------------------------------------------------------------------


def test_todo_renders_status_icons_and_counts():
    rendered = _render(
        "SetTodoList",
        {
            "todos": [
                {"title": "Write spec", "status": "done"},
                {"title": "Implement", "status": "in_progress"},
                {"title": "Test", "status": "pending"},
            ]
        },
    )
    assert "todos" in rendered
    assert "1/3 done" in rendered
    assert "1 active" in rendered
    assert "1 pending" in rendered
    assert "├─" in rendered
    assert "└─" in rendered
    assert "Write spec" in rendered
    assert "Implement" in rendered
    assert "Test" in rendered


def test_todo_infers_nested_items_from_leading_spaces():
    rendered = _render(
        "SetTodoList",
        {
            "todos": [
                {"title": "Parent", "status": "in_progress"},
                {"title": "  Child", "status": "pending"},
            ]
        },
    )
    assert "├─" in rendered
    assert "  └─" in rendered
    assert "Child" in rendered


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


def test_fetch_renders_url():
    rendered = _render("FetchURL", {"url": "https://example.com/page"}, output="<html>...")
    assert "fetch" in rendered
    assert "example.com" in rendered


def test_search_renders_query_and_extras():
    rendered = _render(
        "SearchWeb",
        {"query": "python typing", "limit": 10, "include_content": True},
        output="result 1",
    )
    assert "search" in rendered
    assert "python typing" in rendered
    assert "limit 10" in rendered
    assert "with content" in rendered


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


def test_task_list_renders_active_flag():
    rendered = _render("TaskList", {"active_only": True}, output="task-1: running")
    assert "tasks" in rendered
    assert "(active)" in rendered


def test_task_output_renders_id_and_block_flag():
    rendered = _render(
        "TaskOutput",
        {"task_id": "abc-123", "block": True, "timeout": 60},
        output="logs...",
    )
    assert "task output" in rendered
    assert "abc-123" in rendered
    assert "block" in rendered


def test_task_stop_renders_id():
    rendered = _render("TaskStop", {"task_id": "abc-123", "reason": "user requested"})
    assert "task stop" in rendered
    assert "abc-123" in rendered


# ---------------------------------------------------------------------------
# Plan tools
# ---------------------------------------------------------------------------


def test_enter_plan_mode_renders():
    rendered = _render("EnterPlanMode", {})
    assert "plan mode" in rendered
    assert "entering" in rendered


def test_exit_plan_mode_renders_options():
    rendered = _render(
        "ExitPlanMode",
        {
            "options": [
                {"label": "Refactor first"},
                {"label": "Add tests first"},
            ]
        },
    )
    assert "plan mode" in rendered
    assert "Refactor first" in rendered
    assert "Add tests first" in rendered


# ---------------------------------------------------------------------------
# spacing
# ---------------------------------------------------------------------------


def test_card_renders_compact_without_outer_padding():
    """Compact tool cards should start at the title and avoid extra outer padding."""
    rendered = _render("Glob", {"pattern": "*.py", "directory": "/repo"}, output="foo.py")
    lines = [line.strip() for line in rendered.splitlines()]
    assert lines[0] == "find *.py in /repo"
    assert lines[-1] == "⎿  foo.py"


def test_card_places_result_immediately_under_response_gutter():
    """Tool output should follow the header immediately under the response gutter."""
    rendered = _render("Glob", {"pattern": "*.py", "directory": "/repo"}, output="foo.py\nbar.py")
    lines = [line.strip() for line in rendered.splitlines()]
    header_idx = next(
        (i for i, line in enumerate(lines) if "find" in line and "*.py" in line), None
    )
    assert header_idx is not None, "header line not found in rendered output"
    assert lines[header_idx + 1].startswith("⎿  foo.py"), (
        f"expected response gutter after header at index {header_idx}, "
        f"got {lines[header_idx + 1]!r}"
    )
    assert any("bar.py" in line for line in lines[header_idx + 2 :])
