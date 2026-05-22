from __future__ import annotations

import json

import pytest
from pythinker_core.message import ToolCall
from pythinker_core.tooling import ToolError, ToolOk
from rich.console import Console

from pythinker_code.ui.shell.visualize import _ToolCallBlock, _worklog
from pythinker_code.wire.types import ToolResult


@pytest.fixture(autouse=True)
def _legacy_tui_style(monkeypatch):
    monkeypatch.setenv("PYTHINKER_TUI_STYLE", "pythinker")


def _plain(renderable) -> str:
    console = Console(record=True, width=120, color_system=None)
    console.print(renderable)
    return console.export_text()


def _tool_call(name: str, arguments: str = "{}") -> ToolCall:
    return ToolCall(id=f"tc-{name}", function=ToolCall.FunctionBody(name=name, arguments=arguments))


def _tool_call_with_id(call_id: str, name: str, arguments: str = "{}") -> ToolCall:
    return ToolCall(id=call_id, function=ToolCall.FunctionBody(name=name, arguments=arguments))


class TestExtractFullUrl:
    """Tests for _ToolCallBlock._extract_full_url static method."""

    def test_fetchurl_normal_url(self):
        url = _ToolCallBlock._extract_full_url(
            '{"url": "https://example.com/very/long/path"}', "FetchURL"
        )
        assert url == "https://example.com/very/long/path"

    def test_fetchurl_short_url(self):
        url = _ToolCallBlock._extract_full_url('{"url": "https://x.co"}', "FetchURL")
        assert url == "https://x.co"

    def test_non_fetchurl_tool(self):
        url = _ToolCallBlock._extract_full_url('{"url": "https://example.com"}', "ReadFile")
        assert url is None

    def test_arguments_none(self):
        url = _ToolCallBlock._extract_full_url(None, "FetchURL")
        assert url is None

    def test_invalid_json(self):
        url = _ToolCallBlock._extract_full_url("not json", "FetchURL")
        assert url is None

    def test_missing_url_field(self):
        url = _ToolCallBlock._extract_full_url('{"query": "hello"}', "FetchURL")
        assert url is None

    def test_empty_string(self):
        url = _ToolCallBlock._extract_full_url("", "FetchURL")
        assert url is None


def test_tool_call_block_renders_running_worklog_entry():
    block = _ToolCallBlock(_tool_call("ReadFile", '{"file_path":"src/app.py"}'))
    output = _plain(block.compose())

    assert "Read" in output
    assert "src/app.py" in output
    assert "running" in output.lower()


def test_tool_call_block_renders_running_subagent_with_solid_circle(monkeypatch):
    monkeypatch.setattr(_worklog.time, "monotonic", lambda: 0.0)
    block = _ToolCallBlock(_tool_call("Agent", '{"description":"Audit UI"}'))
    output = _plain(block.compose())

    assert "●" in output
    assert not any(frame in output for frame in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
    assert "Subagent" in output
    assert "Audit UI" in output
    assert "running" in output.lower()


def test_tool_call_block_renders_completed_worklog_entry():
    block = _ToolCallBlock(_tool_call("Grep", '{"pattern":"FIXME"}'))
    block.finish(ToolOk(output=""))
    output = _plain(block.compose())

    assert "Search" in output
    assert "FIXME" in output
    assert "completed" in output.lower()


def test_tool_call_block_renders_failed_worklog_entry():
    block = _ToolCallBlock(_tool_call("Bash", '{"command":"pytest"}'))
    block.finish(ToolError(message="exit code 1", brief="failed"))
    output = _plain(block.compose())

    assert "Shell" in output
    assert "pytest" in output
    assert "failed" in output.lower()
    assert "exit code 1" in output


def test_card_result_text_includes_error_message_before_output():
    result = ToolError(
        message="Pattern `**/*.py` starts with '**' which is not allowed.",
        output="src/\npackages/",
        brief="Unsafe pattern",
    )

    text = _ToolCallBlock._card_result_text(result)

    assert text.startswith("Pattern `**/*.py` starts")
    assert "src/" in text


def test_tool_call_block_truncates_long_shell_command_target():
    command = "python - <<'PY'\n" + "print('x')\n" * 20 + "PY"
    block = _ToolCallBlock(_tool_call("Bash", json.dumps({"command": command})))
    output = _plain(block.compose())

    assert "python - <<'PY'" in output
    assert "print('x')" in output
    assert command not in output
    assert "..." in output


def test_tool_call_block_renders_denied_as_denied_not_failed():
    block = _ToolCallBlock(_tool_call("Bash", '{"command":"rm -rf /"}'))
    block.finish(ToolError(message="user dismissed permission", brief="denied"))
    output = _plain(block.compose())

    assert "Shell" in output
    assert "denied" in output.lower()
    assert "failed" not in output.lower()


def test_tool_call_block_renders_display_cards_under_completed_entry():
    block = _ToolCallBlock(_tool_call("Bash", '{"command":"pytest"}'))
    block.finish(ToolOk(output="", brief="Tests passed\n\nAll clear"))
    output = _plain(block.compose())

    assert "Shell" in output
    assert "Report" in output
    assert "Tests passed" in output


def test_completed_subagent_renders_compact_summary():
    block = _ToolCallBlock(_tool_call("Agent", '{"description":"Audit UI"}'))
    block.set_subagent_metadata("a143aa989", "explore")
    for index in range(7):
        call = _tool_call_with_id(
            f"sub-{index}",
            "ReadFile",
            json.dumps({"path": f"web/src/components/file-{index}.tsx"}),
        )
        block.append_sub_tool_call(call)
        block.finish_sub_tool_call(ToolResult(tool_call_id=call.id, return_value=ToolOk(output="")))

    block.finish(ToolOk(output=""))
    output = _plain(block.compose())

    assert "Subagent" in output
    assert "completed" in output.lower()
    assert "7 tool calls" in output
    assert output.count("Used ReadFile") <= 3
    assert "more tool" not in output.lower()
