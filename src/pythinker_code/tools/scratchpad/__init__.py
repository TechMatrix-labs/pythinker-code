from pathlib import Path
from typing import Literal, override

from pydantic import BaseModel, Field
from pythinker_core.tooling import CallableTool2, ToolError, ToolOk, ToolReturnValue

from pythinker_code.memory.sanitize import strip_private_spans
from pythinker_code.project_memory import scan_memory_content
from pythinker_code.scratchpad import append_scratch_note
from pythinker_code.soul.agent import Runtime
from pythinker_code.tools.utils import load_desc


class Params(BaseModel):
    action: Literal["add"] = Field(default="add", description="The scratchpad operation.")
    kind: Literal["decision", "evidence", "blocker", "next", "note"] = Field(
        default="note", description="What kind of working-memory note this is."
    )
    content: str = Field(description="The note text (a few sentences).")


class Scratchpad(CallableTool2[Params]):
    name: str = "Scratchpad"
    description: str = load_desc(Path(__file__).parent / "scratchpad_tool.md", {})
    params: type[Params] = Params

    def __init__(self, runtime: Runtime) -> None:
        super().__init__()
        self._runtime = runtime

    @override
    async def __call__(self, params: Params) -> ToolReturnValue:
        if self._runtime.role != "root":
            return ToolError(
                message="Scratchpad is only available to the root agent.",
                brief="scratchpad: subagent",
            )
        cleaned = strip_private_spans(params.content or "").strip()
        if not cleaned:
            return ToolError(
                message="Note content is empty after stripping.", brief="scratchpad: empty"
            )
        blocked = scan_memory_content(cleaned)
        if blocked:
            return ToolError(message=blocked, brief="scratchpad: rejected")

        session = self._runtime.session
        result = await append_scratch_note(
            session.work_dir,
            kind=params.kind,
            content=cleaned,
            session_id=getattr(session, "id", None),
            session_title=getattr(session, "title", None),
        )
        if not result.appended:
            return ToolError(
                message=f"Scratchpad note not written ({result.reason}).",
                brief=f"scratchpad: {result.reason}",
            )
        rearm = getattr(self._runtime, "rearm_injection", None)
        if rearm is not None:
            rearm("project_memory")
        return ToolOk(
            output=f"Note recorded ({params.kind}).", message="Note recorded.", brief=params.kind
        )
