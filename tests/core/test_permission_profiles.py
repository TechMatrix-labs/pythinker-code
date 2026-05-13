from __future__ import annotations

import json
import platform
import sys

import pytest
from pythinker_host.path import HostPath

from pythinker_code.soul.agent import Runtime
from pythinker_code.soul.approval import Approval
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
