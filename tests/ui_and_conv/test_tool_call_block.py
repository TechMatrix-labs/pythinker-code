from __future__ import annotations

import json

from pythinker_core.message import ToolCall
from pythinker_core.tooling import ToolError, ToolOk
from rich.console import Console

from pythinker_code.ui.shell.visualize import _ToolCallBlock


def _plain(renderable) -> str:
    console = Console(record=True, width=120, color_system=None)
    console.print(renderable)
    return console.export_text()


def _tool_call(name: str, arguments: str = "{}") -> ToolCall:
    return ToolCall(id=f"tc-{name}", function=ToolCall.FunctionBody(name=name, arguments=arguments))


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


def test_tool_call_block_renders_running_subagent_with_dots_particle():
    block = _ToolCallBlock(_tool_call("Agent", '{"description":"Audit UI"}'))
    output = _plain(block.compose())

    assert any(frame in output for frame in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
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
