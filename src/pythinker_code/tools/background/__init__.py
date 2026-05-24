import re
import time
from pathlib import Path
from typing import override

from pydantic import BaseModel, Field
from pythinker_core.tooling import CallableTool2, ToolError, ToolReturnValue

from pythinker_code.background import TaskView, format_task, format_task_list, list_task_views
from pythinker_code.soul.agent import Runtime
from pythinker_code.soul.approval import Approval
from pythinker_code.tools.display import BackgroundTaskDisplayBlock
from pythinker_code.tools.utils import ToolResultStatus, load_desc, tool_error, tool_status_line

TASK_OUTPUT_PREVIEW_BYTES = 32 << 10
TASK_OUTPUT_READ_HINT_LINES = 300
SECRET_LIKE_RE = re.compile(
    r"(?i)(api[_-]?key|auth|bearer|credential|passwd|password|secret|token)"
)


def _ensure_root(runtime: Runtime) -> ToolError | None:
    if runtime.role != "root":
        return ToolError(
            message="Background tasks can only be managed by the root agent.",
            brief="Background task unavailable",
        )
    return None


def _task_display(runtime: Runtime, task_id: str) -> BackgroundTaskDisplayBlock:
    view = runtime.background_tasks.store.merged_view(task_id)
    return BackgroundTaskDisplayBlock(
        task_id=view.spec.id,
        kind=view.spec.kind,
        status=view.runtime.status,
        description=view.spec.description,
    )


def _tool_status_for_view(view: TaskView) -> ToolResultStatus:
    if view.runtime.status in {"starting", "running"}:
        return ToolResultStatus.long_running_snapshot
    if view.runtime.status == "completed":
        return ToolResultStatus.success
    if view.runtime.status == "killed":
        return ToolResultStatus.cancelled
    if view.runtime.status in {"failed", "lost"}:
        return ToolResultStatus.failure
    return ToolResultStatus.error


def _format_task_output(
    view: TaskView,
    *,
    tool_status: ToolResultStatus,
    retrieval_status: str,
    output: str,
    output_path: Path,
    full_output_available: bool,
    output_size_bytes: int,
    output_preview_bytes: int,
    output_truncated: bool,
    offset: int,
    next_offset: int,
    eof: bool,
) -> str:
    terminal_reason = "timed_out" if view.runtime.timed_out else view.runtime.status
    output_path_str = str(output_path.resolve())
    lines = [
        tool_status_line(tool_status),
        f"retrieval_status: {retrieval_status}",
        f"task_id: {view.spec.id}",
        f"kind: {view.spec.kind}",
        f"status: {view.runtime.status}",
        f"description: {view.spec.description}",
    ]
    if view.spec.kind == "agent" and view.spec.kind_payload:
        if agent_id := view.spec.kind_payload.get("agent_id"):
            lines.append(f"agent_id: {agent_id}")
        if subagent_type := view.spec.kind_payload.get("subagent_type"):
            lines.append(f"subagent_type: {subagent_type}")
    if view.spec.command:
        lines.append(f"command: {view.spec.command}")
    lines.extend(
        [
            f"interrupted: {str(view.runtime.interrupted).lower()}",
            f"timed_out: {str(view.runtime.timed_out).lower()}",
            f"terminal_reason: {terminal_reason}",
        ]
    )
    if view.runtime.exit_code is not None:
        lines.append(f"exit_code: {view.runtime.exit_code}")
    if view.runtime.failure_reason:
        lines.append(f"reason: {view.runtime.failure_reason}")
    full_output_hint = (
        (
            "full_output_hint: "
            f'Use ReadFile(path="{output_path_str}", line_offset=1, '
            f"n_lines={TASK_OUTPUT_READ_HINT_LINES}) to inspect the full log. "
            "Increase line_offset to continue paging through the file."
        )
        if full_output_available
        else "full_output_hint: No output file is currently available for this task."
    )
    lines.extend(
        [
            "",
            f"output_path: {output_path_str}",
            f"output_size_bytes: {output_size_bytes}",
            f"output_preview_bytes: {output_preview_bytes}",
            f"output_truncated: {str(output_truncated).lower()}",
            f"offset: {offset}",
            f"next_offset: {next_offset}",
            f"eof: {str(eof).lower()}",
            "",
            f"full_output_available: {str(full_output_available).lower()}",
            "full_output_tool: ReadFile",
            full_output_hint,
        ]
    )
    rendered_output = output or "[no output available]"
    if output_truncated:
        rendered_output = f"[Truncated. Full output: {output_path_str}]\n\n{rendered_output}"
    return "\n".join(
        lines
        + [
            "",
            "[output]",
            rendered_output,
        ]
    )


class TaskOutputParams(BaseModel):
    task_id: str = Field(description="The background task ID to inspect.")
    offset: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Byte offset to read from. Omit to return the default tail preview for compatibility."
        ),
    )
    max_bytes: int = Field(
        default=TASK_OUTPUT_PREVIEW_BYTES,
        ge=1,
        le=1024 * 1024,
        description="Maximum bytes to read from the task output log.",
    )
    block: bool = Field(
        default=False,
        description="Whether to wait for the task to finish before returning.",
    )
    timeout: int = Field(
        default=30,
        ge=0,
        le=3600,
        description="Maximum number of seconds to wait when block=true.",
    )


class TaskHandoffParams(BaseModel):
    task_id: str = Field(description="The background task ID to hand off to the user.")


class TaskInputParams(BaseModel):
    task_id: str = Field(description="The running background shell task ID to write to.")
    text: str = Field(
        min_length=1,
        max_length=32_000,
        description="Text to send to the process stdin.",
    )
    newline: bool = Field(
        default=True,
        description="Whether to append a newline after the text.",
    )


class TaskStopParams(BaseModel):
    task_id: str = Field(description="The background task ID to stop.")
    reason: str = Field(
        default="Stopped by TaskStop",
        description="Short reason recorded when the task is stopped.",
    )


class TaskListParams(BaseModel):
    active_only: bool = Field(
        default=True,
        description="Whether to list only non-terminal background tasks.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of tasks to return.",
    )


class TaskList(CallableTool2[TaskListParams]):
    name: str = "TaskList"
    description: str = load_desc(Path(__file__).parent / "list.md")
    params: type[TaskListParams] = TaskListParams

    def __init__(self, runtime: Runtime):
        super().__init__()
        self._runtime = runtime

    @override
    async def __call__(self, params: TaskListParams) -> ToolReturnValue:
        if err := _ensure_root(self._runtime):
            return err

        views = list_task_views(
            self._runtime.background_tasks,
            active_only=params.active_only,
            limit=params.limit,
        )
        display = [
            BackgroundTaskDisplayBlock(
                task_id=view.spec.id,
                kind=view.spec.kind,
                status=view.runtime.status,
                description=view.spec.description,
            )
            for view in views
        ]
        return ToolReturnValue(
            is_error=False,
            output=format_task_list(views, active_only=params.active_only),
            message="Task list retrieved.",
            display=list(display),
            extras={"status": ToolResultStatus.success.value},
        )


class TaskOutput(CallableTool2[TaskOutputParams]):
    name: str = "TaskOutput"
    description: str = load_desc(Path(__file__).parent / "output.md")
    params: type[TaskOutputParams] = TaskOutputParams

    def __init__(self, runtime: Runtime):
        super().__init__()
        self._runtime = runtime

    def _missing_task_error(self, task_id: str) -> ToolReturnValue:
        return tool_error(
            message=f"Task not found: {task_id}",
            brief="Task not found",
            status=ToolResultStatus.error,
        )

    def _render_output_preview(
        self,
        task_id: str,
        *,
        offset: int | None,
        max_bytes: int,
    ) -> tuple[str, bool, int, int, bool, Path, int, int, bool]:
        manager = self._runtime.background_tasks
        output_path = manager.resolve_output_path(task_id)
        try:
            output_size = output_path.stat().st_size if output_path.exists() else 0
        except OSError:
            output_size = 0
        read_offset = max(0, output_size - max_bytes) if offset is None else offset
        chunk = manager.read_output(
            task_id,
            offset=read_offset,
            max_bytes=max_bytes,
        )
        return (
            chunk.text.rstrip("\n"),
            output_size > 0,
            output_size,
            chunk.next_offset - chunk.offset,
            offset is None and read_offset > 0,
            output_path,
            chunk.offset,
            chunk.next_offset,
            chunk.eof,
        )

    @override
    async def __call__(self, params: TaskOutputParams) -> ToolReturnValue:
        if err := _ensure_root(self._runtime):
            return err

        view = self._runtime.background_tasks.get_task(params.task_id)
        if view is None:
            return self._missing_task_error(params.task_id)

        if params.block:
            view = await self._runtime.background_tasks.wait(
                params.task_id,
                timeout_s=params.timeout,
            )
            retrieval_status = (
                "success"
                if view.runtime.status in {"completed", "failed", "killed", "lost"}
                else "timeout"
            )
        else:
            retrieval_status = (
                "success"
                if view.runtime.status in {"completed", "failed", "killed", "lost"}
                else "not_ready"
            )

        (
            output,
            full_output_available,
            output_size,
            output_preview_bytes,
            output_truncated,
            output_path,
            offset,
            next_offset,
            eof,
        ) = self._render_output_preview(
            params.task_id,
            offset=params.offset,
            max_bytes=params.max_bytes,
        )
        consumer = view.consumer.model_copy(
            update={
                "last_seen_output_size": output_size,
                "last_viewed_at": time.time(),
            }
        )
        self._runtime.background_tasks.store.write_consumer(params.task_id, consumer)

        tool_status = _tool_status_for_view(view)
        return ToolReturnValue(
            is_error=False,
            output=_format_task_output(
                view,
                tool_status=tool_status,
                retrieval_status=retrieval_status,
                output=output,
                output_path=output_path,
                full_output_available=full_output_available,
                output_size_bytes=output_size,
                output_preview_bytes=output_preview_bytes,
                output_truncated=output_truncated,
                offset=offset,
                next_offset=next_offset,
                eof=eof,
            ),
            message=(
                "Task snapshot retrieved."
                if tool_status == ToolResultStatus.long_running_snapshot
                else "Task output retrieved."
            ),
            display=[_task_display(self._runtime, params.task_id)],
            extras={"status": tool_status.value},
        )


def _is_control_heavy(text: str) -> bool:
    if "\x00" in text:
        return True
    control_chars = sum(1 for char in text if ord(char) < 32 and char not in {"\n", "\r", "\t"})
    return control_chars > 0 and control_chars / max(len(text), 1) > 0.1


def _redact_input_for_display(text: str) -> str:
    if SECRET_LIKE_RE.search(text):
        return "[redacted: input looks secret-like]"
    single_line = " ".join(text.splitlines())
    if len(single_line) > 120:
        return single_line[:117] + "..."
    return single_line


class TaskHandoff(CallableTool2[TaskHandoffParams]):
    name: str = "TaskHandoff"
    description: str = load_desc(Path(__file__).parent / "handoff.md")
    params: type[TaskHandoffParams] = TaskHandoffParams

    def __init__(self, runtime: Runtime):
        super().__init__()
        self._runtime = runtime

    @override
    async def __call__(self, params: TaskHandoffParams) -> ToolReturnValue:
        if err := _ensure_root(self._runtime):
            return err
        view = self._runtime.background_tasks.get_task(params.task_id)
        if view is None:
            return tool_error(
                message=f"Task not found: {params.task_id}",
                brief="Task not found",
                status=ToolResultStatus.error,
            )
        output_path = self._runtime.background_tasks.resolve_output_path(params.task_id).resolve()
        lines = [
            tool_status_line(_tool_status_for_view(view)),
            f"task_id: {view.spec.id}",
            f"kind: {view.spec.kind}",
            f"status: {view.runtime.status}",
            f"description: {view.spec.description}",
            f"command: {view.spec.command or '[not a shell task]'}",
            f"cwd: {view.spec.cwd or '[not available]'}",
            f"output_path: {output_path}",
            "stop_hint: Use TaskStop with this task_id to request cancellation.",
            (
                "reattach_warning: Live terminal reattachment is not available for this "
                "task; use TaskOutput or read output_path for logs."
            ),
        ]
        return ToolReturnValue(
            is_error=False,
            output="\n".join(lines),
            message="Task handoff details retrieved.",
            display=[_task_display(self._runtime, params.task_id)],
            extras={"status": _tool_status_for_view(view).value},
        )


class TaskInput(CallableTool2[TaskInputParams]):
    name: str = "TaskInput"
    description: str = load_desc(Path(__file__).parent / "input.md")
    params: type[TaskInputParams] = TaskInputParams

    def __init__(self, runtime: Runtime, approval: Approval):
        super().__init__()
        self._runtime = runtime
        self._approval = approval

    @override
    async def __call__(self, params: TaskInputParams) -> ToolReturnValue:
        if err := _ensure_root(self._runtime):
            return err
        if self._runtime.session.state.plan_mode:
            return tool_error(
                message="TaskInput is not available in plan mode.",
                brief="Blocked in plan mode",
                status=ToolResultStatus.denied,
            )
        if _is_control_heavy(params.text):
            return tool_error(
                message="TaskInput rejected binary/control-heavy input.",
                brief="Unsafe input",
                status=ToolResultStatus.error,
            )

        view = self._runtime.background_tasks.get_task(params.task_id)
        if view is None:
            return tool_error(
                message=f"Task not found: {params.task_id}",
                brief="Task not found",
                status=ToolResultStatus.error,
            )
        if view.spec.kind != "bash":
            return tool_error(
                message="TaskInput is only supported for shell background tasks.",
                brief="Unsupported task kind",
                status=ToolResultStatus.error,
            )

        display_text = _redact_input_for_display(params.text)
        result = await self._approval.request(
            self.name,
            "write to background task stdin",
            f"Write input to background task `{params.task_id}`: {display_text}",
            display=[_task_display(self._runtime, params.task_id)],
        )
        if not result:
            return result.rejection_error()

        try:
            event = self._runtime.background_tasks.write_input(
                params.task_id,
                text=params.text,
                newline=params.newline,
            )
        except RuntimeError as exc:
            return tool_error(
                message=str(exc),
                brief="Input rejected",
                status=ToolResultStatus.error,
            )

        lines = [
            tool_status_line(ToolResultStatus.success),
            f"task_id: {params.task_id}",
            f"input_event_id: {event.id}",
            f"newline: {str(event.newline).lower()}",
            "input: " + display_text,
        ]
        return ToolReturnValue(
            is_error=False,
            output="\n".join(lines),
            message="Task input queued.",
            display=[_task_display(self._runtime, params.task_id)],
            extras={"status": ToolResultStatus.success.value},
        )


class TaskStop(CallableTool2[TaskStopParams]):
    name: str = "TaskStop"
    description: str = load_desc(Path(__file__).parent / "stop.md")
    params: type[TaskStopParams] = TaskStopParams

    def __init__(self, runtime: Runtime, approval: Approval):
        super().__init__()
        self._runtime = runtime
        self._approval = approval

    @override
    async def __call__(self, params: TaskStopParams) -> ToolReturnValue:
        if err := _ensure_root(self._runtime):
            return err
        if self._runtime.session.state.plan_mode:
            return ToolError(
                message="TaskStop is not available in plan mode.",
                brief="Blocked in plan mode",
            )

        view = self._runtime.background_tasks.get_task(params.task_id)
        if view is None:
            return tool_error(
                message=f"Task not found: {params.task_id}",
                brief="Task not found",
                status=ToolResultStatus.error,
            )

        result = await self._approval.request(
            self.name,
            "stop background task",
            f"Stop background task `{params.task_id}`",
            display=[_task_display(self._runtime, params.task_id)],
        )
        if not result:
            return result.rejection_error()

        view = self._runtime.background_tasks.kill(
            params.task_id,
            reason=params.reason.strip() or "Stopped by TaskStop",
        )
        return ToolReturnValue(
            is_error=False,
            output="\n".join(
                [
                    tool_status_line(ToolResultStatus.cancelled),
                    format_task(view, include_command=True),
                ]
            ),
            message="Task stop requested.",
            display=[_task_display(self._runtime, params.task_id)],
            extras={"status": ToolResultStatus.cancelled.value},
        )
