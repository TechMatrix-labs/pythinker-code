from __future__ import annotations

import re
import shlex
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pythinker_core.tooling import ToolError

if TYPE_CHECKING:
    from pythinker_code.soul.agent import Runtime


PermissionProfileName = Literal["read_only", "plan", "ask", "implement", "review", "verify"]


@dataclass(frozen=True, slots=True)
class PermissionProfile:
    name: PermissionProfileName
    description: str
    allow_file_mutation: bool
    allow_shell_mutation: bool
    allow_plan_file_mutation: bool = False


_PERMISSION_PROFILES: dict[PermissionProfileName, PermissionProfile] = {
    "read_only": PermissionProfile(
        name="read_only",
        description="read-only exploration",
        allow_file_mutation=False,
        allow_shell_mutation=False,
    ),
    "plan": PermissionProfile(
        name="plan",
        description="plan mode",
        allow_file_mutation=False,
        allow_shell_mutation=False,
        allow_plan_file_mutation=True,
    ),
    "ask": PermissionProfile(
        name="ask",
        description="ask-only mode",
        allow_file_mutation=False,
        allow_shell_mutation=False,
    ),
    "implement": PermissionProfile(
        name="implement",
        description="implementation mode",
        allow_file_mutation=True,
        allow_shell_mutation=True,
    ),
    "review": PermissionProfile(
        name="review",
        description="review mode",
        allow_file_mutation=False,
        allow_shell_mutation=False,
    ),
    "verify": PermissionProfile(
        name="verify",
        description="verification mode",
        allow_file_mutation=False,
        allow_shell_mutation=False,
    ),
}

_SUBAGENT_PROFILES: dict[str, PermissionProfileName] = {
    "explore": "read_only",
    "plan": "plan",
    "review": "review",
    "verifier": "verify",
    "coder": "implement",
    "implementer": "implement",
}

_STEP_PERMISSION_PROFILE: ContextVar[PermissionProfile | None] = ContextVar(
    "pythinker_step_permission_profile", default=None
)

_SHELL_SEGMENT_SEPARATORS = {";", "&&", "||", "|"}
_WRITING_REDIRECTION_RE = re.compile(r"(?:^|\s)(?:[0-9]*>>?|&>)\s*(\S+)")
_MUTATING_COMMANDS = {
    "chmod",
    "chown",
    "cp",
    "install",
    "ln",
    "mkdir",
    "mktemp",
    "mv",
    "patch",
    "rm",
    "rmdir",
    "rsync",
    "tee",
    "touch",
    "truncate",
    "unlink",
}
_PACKAGE_MANAGER_COMMANDS = {
    "apt",
    "apt-get",
    "brew",
    "cargo",
    "dnf",
    "gem",
    "go",
    "npm",
    "pnpm",
    "pip",
    "pip3",
    "poetry",
    "uv",
    "yarn",
}
_PACKAGE_MANAGER_MUTATIONS = {
    "add",
    "build",
    "compile",
    "install",
    "publish",
    "remove",
    "sync",
    "uninstall",
    "update",
    "upgrade",
}
_GIT_MUTATIONS = {
    "add",
    "am",
    "apply",
    "bisect",
    "branch",
    "checkout",
    "cherry-pick",
    "clean",
    "commit",
    "merge",
    "mv",
    "pull",
    "push",
    "rebase",
    "reset",
    "restore",
    "revert",
    "rm",
    "stash",
    "switch",
    "tag",
}
_WRAPPER_COMMANDS = {"command", "env", "nohup", "sudo", "time"}


def permission_profile_for_runtime(runtime: Runtime) -> PermissionProfile:
    """Return the hard permission profile currently enforced for a runtime."""
    if runtime.role == "subagent" and runtime.subagent_type:
        profile_name = _SUBAGENT_PROFILES.get(runtime.subagent_type, "implement")
    elif runtime.session.state.plan_mode:
        profile_name = "plan"
    else:
        profile_name = "implement"
    return _PERMISSION_PROFILES[profile_name]


def active_permission_profile(runtime: Runtime) -> PermissionProfile:
    """Return the effective profile for this task.

    A single LLM step snapshots the profile before tool calls start. Tool tasks inherit that
    ContextVar value, so plan/read-only checks cannot race with an ExitPlanMode tool call from the
    same assistant response.
    """
    return _STEP_PERMISSION_PROFILE.get() or permission_profile_for_runtime(runtime)


def set_step_permission_profile(profile: PermissionProfile) -> Token[PermissionProfile | None]:
    """Freeze permission checks for all tool tasks spawned in the current context."""
    return _STEP_PERMISSION_PROFILE.set(profile)


def reset_step_permission_profile(token: Token[PermissionProfile | None]) -> None:
    _STEP_PERMISSION_PROFILE.reset(token)


def check_file_mutation_allowed(
    runtime: Runtime, *, is_plan_artifact: bool = False
) -> ToolError | None:
    profile = active_permission_profile(runtime)
    if profile.allow_file_mutation:
        return None
    if is_plan_artifact and profile.allow_plan_file_mutation:
        return None
    return ToolError(
        message=(
            f"The active {profile.description} permission profile blocks file mutations. "
            "Switch to an implementation/coder profile before editing files."
        ),
        brief="Permission profile restriction",
    )


def check_shell_command_allowed(runtime: Runtime, command: str) -> ToolError | None:
    profile = active_permission_profile(runtime)
    if profile.allow_shell_mutation:
        return None
    reason = shell_mutation_reason(command)
    if reason is None:
        return None
    return ToolError(
        message=(
            f"The active {profile.description} permission profile blocks this shell command "
            f"because it appears to mutate the workspace or environment ({reason}). "
            "Use a read-only command or switch to an implementation/coder profile."
        ),
        brief="Permission profile restriction",
    )


def check_external_tool_allowed(runtime: Runtime, tool_name: str) -> ToolError | None:
    """Fail closed for tools whose side effects are not classified by built-in guards."""
    profile = active_permission_profile(runtime)
    if profile.allow_file_mutation and profile.allow_shell_mutation:
        return None
    return ToolError(
        message=(
            f"The active {profile.description} permission profile blocks external tool "
            f"`{tool_name}` because its side effects are not known to be read-only. "
            "Switch to an implementation/coder profile before using external tools."
        ),
        brief="Permission profile restriction",
    )


def check_tool_call_allowed(
    runtime: Runtime, tool_name: str, arguments: dict[str, Any], *, tool: object | None = None
) -> ToolError | None:
    """Central permission guard for tool adapters that can bypass per-tool checks."""
    if tool_name == "Shell" and isinstance(arguments.get("command"), str):
        return check_shell_command_allowed(runtime, arguments["command"])

    tool_type = type(tool)
    module = getattr(tool_type, "__module__", "")
    qualname = getattr(tool_type, "__qualname__", "")
    if module == "pythinker_code.plugin.tool" and qualname.endswith("PluginTool"):
        return check_external_tool_allowed(runtime, tool_name)
    if module == "pythinker_code.soul.toolset" and qualname in {"MCPTool", "WireExternalTool"}:
        return check_external_tool_allowed(runtime, tool_name)
    return None


def shell_mutation_reason(command: str) -> str | None:
    """Best-effort guard for obviously mutating shell commands.

    This is intentionally conservative for common destructive/write forms. It is not a shell
    sandbox; it prevents accidental tool-level bypasses of read-only/plan/review/verify profiles.
    """
    for match in _WRITING_REDIRECTION_RE.finditer(command):
        target = match.group(1)
        if target.startswith("&") or target in {"/dev/null", "NUL"}:
            continue
        return "output redirection"

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return "unparsable shell command"

    segment: list[str] = []
    for token in [*tokens, ";"]:
        if token in _SHELL_SEGMENT_SEPARATORS:
            reason = _segment_mutation_reason(segment)
            if reason is not None:
                return reason
            segment = []
        else:
            segment.append(token)
    return None


def _segment_mutation_reason(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    command, args = _unwrap_command(tokens)
    if command is None:
        return None
    base = command.rsplit("/", 1)[-1]

    if base in _MUTATING_COMMANDS:
        return f"{base} command"
    if base == "sed" and any(arg == "-i" or arg.startswith("-i") for arg in args):
        return "sed in-place edit"
    if base == "perl" and any(arg == "-i" or arg.startswith("-i") for arg in args):
        return "perl in-place edit"
    if base == "git":
        subcommand = _git_subcommand(args)
        if subcommand in _GIT_MUTATIONS:
            return f"git {subcommand}"
    if base in _PACKAGE_MANAGER_COMMANDS:
        subcommand = _first_non_option(args)
        if subcommand in _PACKAGE_MANAGER_MUTATIONS:
            return f"{base} {subcommand}"
    return None


def _unwrap_command(tokens: list[str]) -> tuple[str | None, list[str]]:
    remaining = list(tokens)
    while remaining:
        command = remaining.pop(0)
        base = command.rsplit("/", 1)[-1]
        if "=" in command and not command.startswith("=") and command.split("=", 1)[0]:
            continue
        if base not in _WRAPPER_COMMANDS:
            return command, remaining
        if base in {"sudo", "time", "nohup", "command"}:
            while remaining and remaining[0].startswith("-"):
                remaining.pop(0)
        elif base == "env":
            while remaining and (remaining[0].startswith("-") or "=" in remaining[0]):
                remaining.pop(0)
    return None, []


def _git_subcommand(args: list[str]) -> str | None:
    remaining = list(args)
    while remaining:
        arg = remaining.pop(0)
        if arg == "-C" and remaining:
            remaining.pop(0)
            continue
        if arg.startswith("--git-dir=") or arg.startswith("--work-tree="):
            continue
        if arg.startswith("-"):
            continue
        return arg
    return None


def _first_non_option(args: list[str]) -> str | None:
    for arg in args:
        if not arg.startswith("-"):
            return arg
    return None
