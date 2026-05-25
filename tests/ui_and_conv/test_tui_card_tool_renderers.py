"""Smoke tests for the Pythinker ported tool renderers.

These tests render each builtin through ``ToolExecutionComponent`` and assert
the human-readable output contains the expected fragments. They are not
pixel-snapshots: tweaking exact spacing/styling is fine, but the substantive
information (tool name, path, key args, result preview, expansion hint) must
remain visible.
"""

from __future__ import annotations

import pytest

from pythinker_code.tools.display import DiffDisplayBlock
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
from pythinker_code.ui.shell.tool_renderers._file_diff import preview_from_diff_blocks
from pythinker_code.ui.shell.tool_renderers.generic import generic_renderer


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


def _render_with_definition(
    tool: str,
    args: dict,
    *,
    output: str = "",
    is_error: bool = False,
    width: int = 100,
) -> str:
    comp = ToolExecutionComponent(tool, "tc-1", definition=generic_renderer(), cwd="/repo")
    comp.update_args(args)
    comp.set_args_complete()
    comp.mark_execution_started()
    comp.set_result(ToolResultPayload(text=output, is_error=is_error))
    return render_plain(comp.render(), width=width)


def _render_running(tool: str, args: dict, *, width: int = 100) -> str:
    defn = get_tool_renderer(tool)
    assert defn is not None, f"renderer not registered for {tool!r}"
    comp = ToolExecutionComponent(tool, "tc-1", definition=defn, cwd="/repo")
    comp.update_args(args)
    comp.set_args_complete()
    comp.mark_execution_started()
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
    assert "● Read(" in rendered
    assert "src/foo.py" in rendered
    assert ":10-39" in rendered
    assert "Read 2 lines" in rendered


def test_read_renders_negative_offset_as_tail():
    rendered = _render(
        "ReadFile",
        {"path": "/repo/src/foo.py", "line_offset": -100},
        output="line1",
    )
    assert "src/foo.py" in rendered
    assert ":tail 100" in rendered
    # The confusing forward-range form must not appear for tail reads.
    assert "--" not in rendered


def test_read_renders_negative_offset_with_limit():
    rendered = _render(
        "ReadFile",
        {"path": "/repo/src/foo.py", "line_offset": -100, "n_lines": 20},
        output="line1",
    )
    assert ":tail 100 · limit 20" in rendered


def test_read_result_matches_reference_summary_only():
    body = "\n".join(f"line {i}" for i in range(20))
    rendered = _render("ReadFile", {"path": "/repo/x.py"}, output=body)
    assert "Read 20 lines" in rendered
    assert "line 0" not in rendered
    assert "more lines" not in rendered


def test_read_error_prefers_structured_message():
    defn = get_tool_renderer("ReadFile")
    assert defn is not None
    comp = ToolExecutionComponent("ReadFile", "tc-1", definition=defn, cwd="/repo")
    comp.update_args({"path": "/repo/missing.py"})
    comp.mark_execution_started()
    comp.set_args_complete()
    comp.set_result(
        ToolResultPayload(
            text="",
            is_error=True,
            details={"message": "File does not exist: /repo/missing.py"},
        )
    )

    rendered = render_plain(comp.render(), width=100)
    assert "File not found" in rendered


def test_read_directory_result_says_listed_directory():
    defn = get_tool_renderer("ReadFile")
    assert defn is not None
    comp = ToolExecutionComponent("ReadFile", "tc-1", definition=defn, cwd="/repo")
    comp.update_args({"path": "/repo/.pythinker-review/security-scan/data/project"})
    comp.mark_execution_started()
    comp.set_args_complete()
    comp.set_result(
        ToolResultPayload(
            text="├── project.json\n└── runs/",
            is_error=False,
            details={
                "message": "Directory listing for `/repo/.pythinker-review/security-scan/data/project`. Use ReadFile on a file path to read file contents.",
                "output": "├── project.json\n└── runs/",
            },
        )
    )

    rendered = render_plain(comp.render(), width=100)
    assert "Listed directory" in rendered
    assert "Read 2 lines" not in rendered


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


def test_write_shows_path_and_content_preview():
    rendered = _render(
        "WriteFile",
        {"path": "/repo/new.py", "content": "def f():\n    return 1\n"},
        output="Successfully wrote",
    )
    assert "● Write(new.py)" in rendered
    assert "Wrote 2 lines to new.py" in rendered
    assert "1 def f():" in rendered


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
    assert "- 1 return 1" in rendered
    assert "+ 1 return 2" in rendered


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


def test_edit_prefers_structured_result_diff_blocks():
    defn = get_tool_renderer("StrReplaceFile")
    assert defn is not None
    comp = ToolExecutionComponent("StrReplaceFile", "tc-1", definition=defn, cwd="/repo")
    comp.update_args({"path": "/repo/foo.py", "edit": {"old": "old", "new": "new"}})
    comp.mark_execution_started()
    comp.set_args_complete()
    comp.set_result(
        ToolResultPayload(
            text="File successfully edited.",
            details={
                "display": [
                    DiffDisplayBlock(
                        path="/repo/foo.py",
                        old_text="keep\nold",
                        new_text="keep\nnew",
                        old_start=40,
                        new_start=40,
                    )
                ]
            },
        )
    )

    rendered = render_plain(comp.render(), width=100)
    assert "Removed 1 line" in rendered
    assert "Added 1 line" in rendered
    assert "-41 old" in rendered
    assert "+41 new" in rendered


def test_summary_diff_blocks_count_each_line():
    preview = preview_from_diff_blocks(
        [
            DiffDisplayBlock(
                path="/repo/large.py",
                old_text="line1\nline2\nline3",
                new_text="new1\nnew2",
                is_summary=True,
            )
        ]
    )

    assert preview is not None
    assert preview.summary_only is True
    assert preview.removed == 3
    assert preview.added == 2
    assert "- line2" in preview.diff_text
    assert "+ new2" in preview.diff_text


# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------


def test_grep_renders_pattern_and_path():
    rendered = _render(
        "Grep",
        {"pattern": "def\\s+", "path": "/repo/src", "glob": "*.py"},
        output="src/foo.py:10: def hello():",
    )
    assert "● Search(" in rendered
    assert "/def\\s+/" in rendered
    assert "src" in rendered
    assert "*.py" in rendered
    assert "Found 1 file" in rendered


def test_grep_content_counts_paths_with_punctuation():
    rendered = _render(
        "Grep",
        {"pattern": "needle", "path": "/repo", "output_mode": "content"},
        output="src/a-b.py:10:needle\nsrc/a-b.py-11-context\nsrc/colon:name.py:3:needle",
    )
    assert "Found 3 lines across 2 files" in rendered


def test_invalid_empty_grep_call_names_missing_pattern():
    rendered = _render(
        "Grep",
        {},
        output=(
            "Error validating JSON arguments: 1 validation error for Params\n"
            "pattern\n  Field required"
        ),
        is_error=True,
    )
    assert "● Search(<missing pattern> in .)" in rendered
    assert "Error searching files" in rendered
    assert "Search(... in .)" not in rendered


# ---------------------------------------------------------------------------
# find / glob
# ---------------------------------------------------------------------------


def test_glob_renders_pattern_and_directory():
    rendered = _render(
        "Glob",
        {"pattern": "**/*.py", "directory": "/repo/src"},
        output="src/a.py\nsrc/b.py",
    )
    assert "● Find(" in rendered
    assert "**/*.py" in rendered
    assert "Found 2 files" in rendered


# ---------------------------------------------------------------------------
# bash / shell
# ---------------------------------------------------------------------------


def test_shell_renders_command_and_output_under_response_gutter():
    rendered = _render("Shell", {"command": "ls -la", "timeout": 60}, output="total 0")
    assert "● Bash(ls -la)" in rendered
    assert "total 0" in rendered
    assert "⎿" in rendered


def test_shell_collapses_long_command_and_reports_output_lines():
    command = "\n".join(["echo first", "echo second", "echo third"])
    output = "\n".join(f"line {i}" for i in range(8))
    rendered = _render("Shell", {"command": command, "timeout": 60}, output=output)
    assert "echo first" in rendered
    assert "echo second" in rendered
    assert "echo third" not in rendered
    assert "… +4 lines (ctrl+o to expand)" in rendered


def test_shell_component_can_toggle_expansion_when_renderer_suppresses_generic_hint():
    defn = get_tool_renderer("Shell")
    assert defn is not None
    comp = ToolExecutionComponent("Shell", "tc-1", definition=defn, cwd="/repo")
    comp.update_args({"command": "pytest", "timeout": 60})
    comp.set_args_complete()
    comp.mark_execution_started()
    comp.set_result(ToolResultPayload(text="\n".join(f"line {i}" for i in range(8))))

    collapsed = render_plain(comp.render(), width=100)
    assert "line 3" not in collapsed
    assert comp.can_expand

    comp.toggle_expanded()
    expanded = render_plain(comp.render(), width=100)
    assert "line 3" in expanded


def test_shell_wraps_substantial_output_in_response_gutter():
    rendered = _render("Shell", {"command": "pytest"}, output="failed\nexit code 1")
    assert "⎿" in rendered
    assert "⎿    ⎿" not in rendered
    assert "failed" in rendered
    assert "exit code 1" in rendered


def test_shell_error_with_empty_output_shows_message():
    defn = get_tool_renderer("Shell")
    assert defn is not None
    comp = ToolExecutionComponent("Shell", "tc-1", definition=defn, cwd="/repo")
    comp.update_args({"command": "printf rejected > reject.txt"})
    comp.mark_execution_started()
    comp.set_args_complete()
    comp.set_result(
        ToolResultPayload(
            text="The tool call is rejected by the user.",
            is_error=True,
            details={"output": "", "message": "The tool call is rejected by the user."},
        )
    )

    rendered = render_plain(comp.render(), width=100)
    assert "The tool call is rejected by the user" in rendered
    assert "exit 1" not in rendered


def test_shell_error_uses_structured_exit_code_when_available():
    defn = get_tool_renderer("Shell")
    assert defn is not None
    comp = ToolExecutionComponent("Shell", "tc-1", definition=defn, cwd="/repo")
    comp.update_args({"command": "python -c 'raise SystemExit(2)'"})
    comp.mark_execution_started()
    comp.set_args_complete()
    comp.set_result(
        ToolResultPayload(
            text="Command failed with exit code: 2.",
            is_error=True,
            details={
                "output": "",
                "message": "Command failed with exit code: 2.",
                "extras": {"status": "failure", "exit_code": 2},
            },
        )
    )

    rendered = render_plain(comp.render(), width=100)
    assert "Command failed with exit code: 2" in rendered
    assert "exit 2" in rendered


def test_shell_uses_comment_label_for_long_script():
    command = "# build assets\n" + "\n".join(f"echo {i}" for i in range(5))
    rendered = _render("Shell", {"command": command, "timeout": 60}, output="ok")
    assert "● Bash(build assets)" in rendered
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


def test_running_tool_headers_do_not_duplicate_status_bullets():
    cases = [
        ("Shell", {"command": "ls packages/pythinker-review/AGENTS.md"}, "Bash("),
        ("ReadFile", {"path": "/repo/src/foo.py"}, "Read("),
        ("WriteFile", {"path": "/repo/src/foo.py", "content": "x"}, "Write("),
        (
            "StrReplaceFile",
            {"path": "/repo/src/foo.py", "edit": {"old": "a", "new": "b"}},
            "Update(",
        ),
        ("Grep", {"pattern": "needle", "path": "/repo"}, "Search("),
        ("Glob", {"pattern": "**/*.py", "directory": "/repo"}, "Find("),
        ("FetchURL", {"url": "https://example.com"}, "Fetch("),
        ("SearchWeb", {"query": "python"}, "WebSearch("),
        (
            "Agent",
            {"description": "audit", "prompt": "check", "subagent_type": "explore"},
            "Agent(",
        ),
        ("AskUserQuestion", {"questions": [{"question": "Continue?"}]}, "Ask("),
        ("Think", {"thought": "check"}, "Think"),
        ("TaskList", {"active_only": True}, "Tasks("),
        ("TaskOutput", {"task_id": "abc"}, "TaskOutput("),
        ("TaskStop", {"task_id": "abc"}, "TaskStop("),
        ("EnterPlanMode", {}, "Plan("),
        ("ExitPlanMode", {"options": [{"label": "Continue"}]}, "Plan("),
    ]
    for tool, args, label in cases:
        rendered = _render_running(tool, args, width=64)
        assert label in rendered
        assert "● ●" not in rendered
        assert "• ●" not in rendered


def test_invalid_empty_shell_call_names_missing_command():
    rendered = _render(
        "Shell",
        {},
        output=(
            "Error validating JSON arguments: 1 validation error for Params\n"
            "command\n  Field required"
        ),
        is_error=True,
    )
    assert "● Bash(<missing command>)" in rendered
    assert "$ ..." not in rendered


def test_task_output_header_shows_description_not_id():
    from pythinker_code.tools.display import BackgroundTaskDisplayBlock

    defn = get_tool_renderer("TaskOutput")
    assert defn is not None
    comp = ToolExecutionComponent("TaskOutput", "tc-1", definition=defn, cwd="/repo")
    comp.update_args({"task_id": "agent-pyl4xz6a", "block": True})
    comp.set_args_complete()
    comp.mark_execution_started()
    comp.set_result(
        ToolResultPayload(
            text="status: completed",
            details={
                "display": [
                    BackgroundTaskDisplayBlock(
                        task_id="agent-pyl4xz6a",
                        kind="agent",
                        status="completed",
                        description="Shell TUI mapping",
                    )
                ]
            },
        )
    )
    rendered = render_plain(comp.render(), width=80)
    # Friendly description is the primary label; raw id kept as a dim suffix.
    assert "Shell TUI mapping" in rendered
    assert rendered.index("Shell TUI mapping") < rendered.index("agent-pyl4xz6a")


def test_task_output_header_resolves_name_while_running():
    """With a registered resolver the friendly name shows even while the task is
    still running (no result yet) — not just after a result arrives."""
    from pythinker_code.ui.shell.tool_renderers.background import set_task_label_resolver

    set_task_label_resolver(lambda tid: "src-mapper" if tid == "agent-7ofm18ub" else None)
    try:
        rendered = _render_running(
            "TaskOutput", {"task_id": "agent-7ofm18ub", "block": True}, width=80
        )
    finally:
        set_task_label_resolver(None)
    assert "src-mapper" in rendered
    assert rendered.index("src-mapper") < rendered.index("agent-7ofm18ub")


def test_generic_substantial_output_uses_single_response_gutter():
    rendered = _render_with_definition(
        "UnknownTool",
        {"path": "x"},
        output="line1\nline2",
    )
    assert "⎿  line1" in rendered
    assert "⎿    ⎿" not in rendered


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
    assert "● Agent(" in rendered
    assert "code-architect" in rendered
    assert "design auth flow" in rendered
    assert "Prompt: Design the OAuth flow with PKCE" in rendered


def test_invalid_empty_agent_call_names_missing_required_fields():
    rendered = _render(
        "Agent",
        {},
        output=(
            "Error validating JSON arguments: 2 validation errors for Params\n"
            "description\n  Field required\n"
            "prompt\n  Field required"
        ),
        is_error=True,
    )
    assert "<missing description>" in rendered
    assert "<missing prompt>" in rendered


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
    assert "● Ask(1 question)" in rendered
    assert "Which auth method?" in rendered
    assert "OAuth" in rendered
    assert "API key" in rendered


# ---------------------------------------------------------------------------
# Think
# ---------------------------------------------------------------------------


def test_think_renders_thought_body():
    rendered = _render("Think", {"thought": "First, check the file layout.\nThen draft a fix."})
    assert "● Think" in rendered
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
    assert "● Fetch(" in rendered
    assert "example.com" in rendered
    assert "Received 9 bytes" in rendered


def test_search_renders_query_and_extras():
    rendered = _render(
        "SearchWeb",
        {"query": "python typing", "limit": 10, "include_content": True},
        output="result 1",
    )
    assert "● WebSearch(" in rendered
    assert "python typing" in rendered
    assert "limit 10" in rendered
    assert "with content" in rendered
    assert "Found 1 result" in rendered


def test_search_counts_structured_result_blocks():
    rendered = _render(
        "SearchWeb",
        {"query": "python"},
        output=(
            "Title: One\nDate: \nURL: https://example.com/1\nSummary: A\n\n"
            "---\n\n"
            "Title: Two\nDate: \nURL: https://example.com/2\nSummary: B\n\n"
        ),
    )
    assert "Found 2 results" in rendered


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


def test_task_list_renders_active_flag():
    rendered = _render("TaskList", {"active_only": True}, output="task-1: running")
    assert "● Tasks(active)" in rendered


def test_task_output_renders_id_and_block_flag():
    rendered = _render(
        "TaskOutput",
        {"task_id": "abc-123", "block": True, "timeout": 60},
        output="logs...",
    )
    assert "● TaskOutput(" in rendered
    assert "abc-123" in rendered
    assert "block" in rendered


def test_task_stop_renders_id():
    rendered = _render("TaskStop", {"task_id": "abc-123", "reason": "user requested"})
    assert "● TaskStop(" in rendered
    assert "abc-123" in rendered


# ---------------------------------------------------------------------------
# Plan tools
# ---------------------------------------------------------------------------


def test_enter_plan_mode_renders():
    rendered = _render("EnterPlanMode", {})
    assert "● Plan(entering)" in rendered


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
    assert "● Plan(exiting)" in rendered
    assert "Refactor first" in rendered
    assert "Add tests first" in rendered


# ---------------------------------------------------------------------------
# spacing
# ---------------------------------------------------------------------------


def test_card_renders_compact_without_outer_padding():
    """Compact tool cards should start at the title and avoid extra outer padding."""
    rendered = _render("Glob", {"pattern": "*.py", "directory": "/repo"}, output="foo.py")
    lines = [line.strip() for line in rendered.splitlines()]
    assert lines[0] == "● Find(*.py in /repo)"
    assert lines[-1] == "⎿  Found 1 file ctrl+o expand"


def test_card_places_result_immediately_under_response_gutter():
    """Tool output should follow the header immediately under the response gutter."""
    rendered = _render("Glob", {"pattern": "*.py", "directory": "/repo"}, output="foo.py\nbar.py")
    lines = [line.strip() for line in rendered.splitlines()]
    header_idx = next(
        (i for i, line in enumerate(lines) if "Find" in line and "*.py" in line), None
    )
    assert header_idx is not None, "header line not found in rendered output"
    assert lines[header_idx + 1].startswith("⎿  Found 2 files"), (
        f"expected response gutter after header at index {header_idx}, "
        f"got {lines[header_idx + 1]!r}"
    )
