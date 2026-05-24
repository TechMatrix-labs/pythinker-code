from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pythinker_code.config import AgentExecutionProfile

PolicyMode = Literal["deny", "ask", "allow"]


class ExecutionPolicy(BaseModel):
    shell: PolicyMode
    write: PolicyMode
    subagents: PolicyMode
    network: PolicyMode
    max_background_tasks: int | None = None
    allowed_subagent_types: set[str] | None = Field(default=None)


def resolve_execution_policy(
    profile: AgentExecutionProfile, *, yolo: bool = False
) -> ExecutionPolicy:
    match profile:
        case "review_safe":
            return ExecutionPolicy(
                shell="ask",
                write="deny",
                subagents="allow",
                network="ask",
                allowed_subagent_types={
                    "explore",
                    "plan",
                    "review",
                    "code-reviewer",
                    "security-reviewer",
                    "debugger",
                },
            )
        case "plan_only":
            return ExecutionPolicy(
                shell="deny",
                write="deny",
                subagents="allow",
                network="deny",
                allowed_subagent_types={"explore", "plan"},
            )
        case "autonomous_coding":
            mode: PolicyMode = "allow" if yolo else "ask"
            return ExecutionPolicy(
                shell=mode,
                write=mode,
                subagents="allow",
                network="ask",
            )
        case "ci_fixer":
            return ExecutionPolicy(
                shell="allow",
                write="ask",
                subagents="allow",
                network="ask",
                allowed_subagent_types={
                    "explore",
                    "plan",
                    "coder",
                    "implementer",
                    "verifier",
                    "debugger",
                },
            )
        case "default":
            return ExecutionPolicy(
                shell="ask",
                write="ask",
                subagents="allow",
                network="ask",
            )
