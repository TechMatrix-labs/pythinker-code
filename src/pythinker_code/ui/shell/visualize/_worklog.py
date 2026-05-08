from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pythinker_core.tooling import BriefDisplayBlock, DisplayBlock
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from pythinker_code.tools.display import (
    BackgroundTaskDisplayBlock,
    DiffDisplayBlock,
    TodoDisplayBlock,
)
from pythinker_code.utils.rich.columns import BulletColumns
from pythinker_code.utils.rich.diff_render import (
    collect_diff_hunks,
    render_diff_panel,
    render_diff_summary_panel,
)
from pythinker_code.utils.rich.markdown import Markdown


class WorkLogState(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class ToolStyle:
    label: str
    icon: str
    style: str


_TOOL_STYLES: dict[str, ToolStyle] = {
    "Read": ToolStyle("Read", "->", "cyan"),
    "ReadFile": ToolStyle("Read", "->", "cyan"),
    "Grep": ToolStyle("Search", "*", "blue"),
    "Glob": ToolStyle("Find", "*", "blue"),
    "Edit": ToolStyle("Edit", "<-", "magenta"),
    "Replace": ToolStyle("Edit", "<-", "magenta"),
    "Write": ToolStyle("Write", "<-", "magenta"),
    "WriteFile": ToolStyle("Write", "<-", "magenta"),
    "ApplyPatch": ToolStyle("Patch", "◆", "magenta"),
    "Bash": ToolStyle("Shell", "$", "green"),
    "Shell": ToolStyle("Shell", "$", "green"),
    "TodoWrite": ToolStyle("Todo", "☑", "yellow"),
    "Agent": ToolStyle("Subagent", "|", "cyan"),
    "Task": ToolStyle("Subagent", "|", "cyan"),
    "AskUser": ToolStyle("Ask", "?", "yellow"),
    "FetchURL": ToolStyle("Fetch", "%", "blue"),
    "WebFetch": ToolStyle("Fetch", "%", "blue"),
    "WebSearch": ToolStyle("Search", "◈", "blue"),
    "Skill": ToolStyle("Skill", "◇", "cyan"),
}


_STATE_STYLE = {
    WorkLogState.RUNNING: "bright_white",
    WorkLogState.COMPLETED: "grey50",
    WorkLogState.FAILED: "red",
    WorkLogState.DENIED: "grey50 strike",
    WorkLogState.INTERRUPTED: "yellow",
}


def tool_style(name: str) -> ToolStyle:
    return _TOOL_STYLES.get(name, ToolStyle(name, "⚙", "blue"))


def denied_error(message: str) -> bool:
    lowered = message.lower().strip()
    if lowered == "denied" or lowered.startswith("denied:"):
        return True
    return any(
        needle in lowered
        for needle in (
            "questionrejectederror",
            "rejected permission",
            "specified a rule",
            "user dismissed",
            "tool calls are disabled",
        )
    )


def render_worklog_entry(
    *,
    label: str,
    target: str | None = None,
    state: WorkLogState,
    detail: str | None = None,
    icon: str = "•",
    icon_style: str = "blue",
    icon_renderable: RenderableType | None = None,
    children: list[RenderableType] | None = None,
) -> RenderableType:
    line = Text()
    if icon_renderable is None:
        line.append(icon, style=icon_style)
        line.append(" ")
    line.append(label, style="bold")
    if target:
        line.append(" ")
        line.append(target, style="grey70")
    line.append(" ")
    line.append(state.value, style=_STATE_STYLE[state])
    if detail:
        line.append(" · ", style="grey50")
        line.append(detail, style=_STATE_STYLE[state])
    if icon_renderable is not None:
        return BulletColumns(
            line if not children else Group(line, *children),
            bullet=icon_renderable,
        )
    if not children:
        return line
    return Group(line, *children)


def render_worklog_card(
    title: str,
    body: RenderableType,
    *,
    subtitle: str | None = None,
    border_style: str = "grey39",
) -> Panel:
    return Panel(
        body,
        title=title,
        title_align="left",
        subtitle=subtitle,
        subtitle_align="left",
        border_style=border_style,
        padding=(0, 1),
        expand=False,
    )


def render_display_blocks(
    display: list[DisplayBlock], *, is_error: bool = False
) -> list[RenderableType]:
    rendered: list[RenderableType] = []
    idx = 0
    while idx < len(display):
        block = display[idx]
        if isinstance(block, DiffDisplayBlock):
            path = block.path
            diff_blocks: list[DiffDisplayBlock] = []
            while idx < len(display):
                candidate = display[idx]
                if not isinstance(candidate, DiffDisplayBlock) or candidate.path != path:
                    break
                diff_blocks.append(candidate)
                idx += 1
            if any(item.is_summary for item in diff_blocks):
                rendered.append(
                    render_worklog_card(
                        "Diff", render_diff_summary_panel(path, diff_blocks), subtitle=path
                    )
                )
                continue
            hunks, added_total, removed_total = collect_diff_hunks(diff_blocks)
            if hunks:
                rendered.append(
                    render_worklog_card(
                        f"Diff +{added_total} -{removed_total}",
                        render_diff_panel(path, hunks, added_total, removed_total),
                        subtitle=path,
                    )
                )
            continue
        if isinstance(block, BriefDisplayBlock):
            text = block.text.strip()
            if text:
                title = "Error" if is_error else "Report"
                style = "red" if is_error else "grey70"
                if "\n" in text or len(text) > 100:
                    rendered.append(
                        render_worklog_card(
                            title,
                            Markdown(text, style=style),
                            border_style="red" if is_error else "grey39",
                        )
                    )
                else:
                    rendered.append(Markdown(text, style=style))
            idx += 1
            continue
        if isinstance(block, TodoDisplayBlock):
            lines: list[str] = []
            for todo in block.items:
                match todo.status:
                    case "done":
                        marker = "✓"
                    case "in_progress":
                        marker = "→"
                    case _:
                        marker = "·"
                lines.append(f"{marker} {todo.title}")
            rendered.append(render_worklog_card("Todos", Text("\n".join(lines), style="grey70")))
            idx += 1
            continue
        if isinstance(block, BackgroundTaskDisplayBlock):
            rendered.append(
                render_worklog_card(
                    "Background task",
                    Text(
                        f"{block.task_id} [{block.status}] {block.kind}: {block.description}",
                        style="grey70",
                    ),
                )
            )
            idx += 1
            continue
        idx += 1
    return rendered
