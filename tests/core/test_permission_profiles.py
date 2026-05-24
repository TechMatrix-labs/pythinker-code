from __future__ import annotations

import json
import platform
import sys

import pytest
from pythinker_host.path import HostPath

from pythinker_code.soul.agent import Runtime
from pythinker_code.soul.approval import Approval, ApprovalResult
from pythinker_code.tools.agent import Agent as AgentTool
from pythinker_code.tools.file.write import Params as WriteParams
from pythinker_code.tools.file.write import WriteFile
from pythinker_code.tools.shell import Params as ShellParams
from pythinker_code.tools.shell import Shell
from pythinker_code.utils.environment import Environment
from tests.conftest import tool_call_context


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Shell mutation guard examples use POSIX"
)
async def test_explore_profile_denies_mutating_shell_before_approval(
    runtime: Runtime,
    environment: Environment,
    temp_work_dir: HostPath,
) -> None:
    runtime.role = "subagent"
    runtime.subagent_type = "explore"
    target = temp_work_dir / "should-not-exist.txt"

    with tool_call_context("Shell"):
        shell = Shell(Approval(yolo=True), environment, runtime)
        result = await shell(ShellParams(command=f"touch {target}"))

    assert result.is_error
    assert "permission profile blocks" in result.message
    assert not await target.exists()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Shell mutation guard examples use POSIX"
)
@pytest.mark.parametrize("subagent_type", ["review", "verifier"])
async def test_review_and_verifier_profiles_deny_mutating_shell(
    runtime: Runtime,
    environment: Environment,
    temp_work_dir: HostPath,
    subagent_type: str,
) -> None:
    runtime.role = "subagent"
    runtime.subagent_type = subagent_type
    target = temp_work_dir / f"{subagent_type}-should-not-exist.txt"

    with tool_call_context("Shell"):
        shell = Shell(Approval(yolo=True), environment, runtime)
        result = await shell(ShellParams(command=f"echo hi > {target}"))

    assert result.is_error
    assert "output redirection" in result.message
    assert not await target.exists()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Shell mutation guard examples use POSIX"
)
async def test_implementer_profile_allows_mutating_shell_with_approval(
    runtime: Runtime,
    environment: Environment,
    temp_work_dir: HostPath,
) -> None:
    runtime.role = "subagent"
    runtime.subagent_type = "implementer"
    target = temp_work_dir / "created-by-implementer.txt"

    with tool_call_context("Shell"):
        shell = Shell(Approval(yolo=True), environment, runtime)
        result = await shell(ShellParams(command=f"touch {target}"))

    assert not result.is_error
    assert await target.exists()


async def test_plan_only_execution_profile_denies_root_shell(
    runtime: Runtime,
    environment: Environment,
) -> None:
    runtime.config.agent_execution_profile = "plan_only"

    with tool_call_context("Shell"):
        shell = Shell(Approval(yolo=True), environment, runtime)
        result = await shell(ShellParams(command="echo hello"))

    assert result.is_error
    assert "Shell is denied by the active execution profile" in result.message


async def test_review_safe_execution_profile_denies_root_write(
    runtime: Runtime,
    temp_work_dir: HostPath,
) -> None:
    runtime.config.agent_execution_profile = "review_safe"
    target = temp_work_dir / "review-safe-denied.txt"

    with tool_call_context("WriteFile"):
        tool = WriteFile(runtime, Approval(yolo=True))
        result = await tool(WriteParams(path=str(target), content="nope"))

    assert result.is_error
    assert "permission profile blocks file mutations" in result.message
    assert not await target.exists()


async def test_plan_only_execution_profile_limits_subagent_types(runtime: Runtime) -> None:
    runtime.config.agent_execution_profile = "plan_only"

    with tool_call_context("Agent"):
        tool = AgentTool(runtime)
        denied = await tool(
            tool.params(description="implement fix", prompt="write code", subagent_type="coder")
        )

    assert denied.is_error
    assert "not allowed by the active execution profile" in denied.message
    assert tool.check_execution_policy("explore") is None


async def test_read_only_profile_denies_write_file_even_if_tool_is_present(
    runtime: Runtime,
    temp_work_dir: HostPath,
) -> None:
    runtime.role = "subagent"
    runtime.subagent_type = "explore"
    target = temp_work_dir / "write-denied.txt"

    with tool_call_context("WriteFile"):
        tool = WriteFile(runtime, Approval(yolo=True))
        result = await tool(WriteParams(path=str(target), content="nope"))

    assert result.is_error
    assert "permission profile blocks file mutations" in result.message
    assert not await target.exists()


async def test_unknown_subagent_type_defaults_to_read_only_profile(
    runtime: Runtime,
    temp_work_dir: HostPath,
) -> None:
    runtime.role = "subagent"
    runtime.subagent_type = "unknown-custom-agent"
    target = temp_work_dir / "write-denied-unknown.txt"

    with tool_call_context("WriteFile"):
        tool = WriteFile(runtime, Approval(yolo=True))
        result = await tool(WriteParams(path=str(target), content="nope"))

    assert result.is_error
    assert "permission profile blocks file mutations" in result.message
    assert not await target.exists()


async def test_toolset_denies_plugin_tool_in_read_only_profile(
    runtime: Runtime,
    tmp_path,
) -> None:
    from pythinker_code.plugin import PluginToolSpec
    from pythinker_code.plugin.tool import PluginTool
    from pythinker_code.soul.toolset import PythinkerToolset
    from pythinker_code.wire.types import ToolCall, ToolResult

    runtime.role = "subagent"
    runtime.subagent_type = "explore"
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    toolset = PythinkerToolset(runtime)
    toolset.add(
        PluginTool(
            PluginToolSpec(
                name="plugin_tool",
                description="test",
                command=[sys.executable, "-c", "print('should not run')"],
            ),
            plugin_dir=plugin_dir,
            inject={},
            config=runtime.config,
        )
    )

    handle_result = toolset.handle(
        ToolCall(
            id="plugin-call",
            function=ToolCall.FunctionBody(name="plugin_tool", arguments=json.dumps({})),
        )
    )
    result = handle_result if isinstance(handle_result, ToolResult) else await handle_result

    assert result.return_value.is_error
    assert "permission profile blocks external tool" in result.return_value.message


async def test_step_permission_profile_snapshot_blocks_same_step_plan_exit_race(
    runtime: Runtime,
    environment: Environment,
    temp_work_dir: HostPath,
) -> None:
    from pythinker_code.soul.permission import (
        permission_profile_for_runtime,
        reset_step_permission_profile,
        set_step_permission_profile,
    )

    runtime.session.state.plan_mode = True
    token = set_step_permission_profile(permission_profile_for_runtime(runtime))
    try:
        runtime.session.state.plan_mode = False
        target = temp_work_dir / "same-step-race.txt"
        with tool_call_context("Shell"):
            shell = Shell(Approval(yolo=True), environment, runtime)
            result = await shell(ShellParams(command=f"touch {target}"))
    finally:
        reset_step_permission_profile(token)

    assert result.is_error
    assert "permission profile blocks" in result.message
    assert not await target.exists()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Shell mutation guard examples use POSIX"
)
@pytest.mark.parametrize("subagent_type", ["review", "verifier", "explore", "coder"])
async def test_read_only_shell_in_subagent_requests_approval(
    runtime: Runtime,
    environment: Environment,
    subagent_type: str,
) -> None:
    """Subagent shell commands still require approval; mutation parsing is only best-effort."""
    approval_requested: list[str] = []

    class TrackingApproval(Approval):
        async def request(self, sender, action, description, display=None):  # type: ignore[override]
            approval_requested.append(action)
            return ApprovalResult(approved=True)

    runtime.role = "subagent"
    runtime.subagent_type = subagent_type
    tracking = TrackingApproval(yolo=False)

    with tool_call_context("Shell"):
        shell = Shell(tracking, environment, runtime)
        result = await shell(ShellParams(command="echo hello"))

    assert not result.is_error
    assert "run command" in approval_requested


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Shell mutation guard examples use POSIX"
)
async def test_subagent_shell_python_runtime_blocked_by_profile(
    runtime: Runtime,
    environment: Environment,
    temp_work_dir: HostPath,
) -> None:
    """Script runtimes (python/node/etc.) are classified as mutating and fail closed
    in read-only subagent profiles — they never reach the approval prompt."""
    approval_requested: list[str] = []
    target = temp_work_dir / "hidden-write.txt"

    class TrackingApproval(Approval):
        async def request(self, sender, action, description, display=None):  # type: ignore[override]
            approval_requested.append(action)
            return ApprovalResult(approved=True)

    runtime.role = "subagent"
    runtime.subagent_type = "explore"

    with tool_call_context("Shell"):
        shell = Shell(TrackingApproval(yolo=False), environment, runtime)
        result = await shell(
            ShellParams(
                command=(
                    f"{sys.executable} -c "
                    f"'from pathlib import Path; Path({str(target)!r}).write_text(\"x\")'"
                )
            )
        )

    assert result.is_error
    assert "permission profile blocks" in result.message
    assert approval_requested == []
    assert not await target.exists()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Shell mutation guard examples use POSIX"
)
async def test_read_only_shell_in_root_agent_still_requests_approval(
    runtime: Runtime,
    environment: Environment,
) -> None:
    """In the root (non-subagent) context, even read-only commands still go through approval."""
    approval_requested: list[str] = []

    class TrackingApproval(Approval):
        async def request(self, sender, action, description, display=None):  # type: ignore[override]
            approval_requested.append(action)
            return await super().request(sender, action, description, display)

    runtime.role = "root"
    tracking = TrackingApproval(yolo=True)  # yolo so the approval auto-passes

    with tool_call_context("Shell"):
        shell = Shell(tracking, environment, runtime)
        result = await shell(ShellParams(command="echo hello"))

    assert not result.is_error
    assert "run command" in approval_requested, "root agent should still request approval"
