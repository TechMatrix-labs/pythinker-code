from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from pythinker_core.tooling import BriefDisplayBlock, DisplayBlock
from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style, StyleType
from rich.text import Text

from pythinker_code.tools.display import (
    BackgroundTaskDisplayBlock,
    DiffDisplayBlock,
    TodoDisplayBlock,
)
from pythinker_code.ui.shell.components.markdown import PythinkerMarkdown as Markdown
from pythinker_code.ui.shell.design_system import ShellTone, StatusName, shell_style, status_icon
from pythinker_code.ui.shell.motion import reduced_motion_enabled
from pythinker_code.ui.shell.spacing import WORKLOG_PANEL_PADDING
from pythinker_code.ui.theme import get_tui_tokens, tui_rich_style
from pythinker_code.utils.rich.columns import BulletColumns
from pythinker_code.utils.rich.diff_render import (
    collect_diff_hunks,
    render_diff_preview,
    render_diff_summary_panel,
)


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
    "Read": ToolStyle("Read", "->", "info"),
    "ReadFile": ToolStyle("Read", "->", "info"),
    "Grep": ToolStyle("Search", "*", "info"),
    "Glob": ToolStyle("Find", "*", "info"),
    "Edit": ToolStyle("Edit", "<-", "accent"),
    "Replace": ToolStyle("Edit", "<-", "accent"),
    "Write": ToolStyle("Write", "<-", "accent"),
    "WriteFile": ToolStyle("Write", "<-", "accent"),
    "ApplyPatch": ToolStyle("Patch", "◆", "accent"),
    "Bash": ToolStyle("Shell", "$", "success"),
    "Shell": ToolStyle("Shell", "$", "success"),
    "TodoWrite": ToolStyle("Todo", "☑", "warning"),
    "Agent": ToolStyle("Subagent", "●", "muted"),
    "Task": ToolStyle("Subagent", "●", "muted"),
    "AskUser": ToolStyle("Ask", "?", "warning"),
    "FetchURL": ToolStyle("Fetch", "%", "info"),
    "WebFetch": ToolStyle("Fetch", "%", "info"),
    "WebSearch": ToolStyle("Search", "◈", "info"),
    "Skill": ToolStyle("Skill", "◇", "info"),
}


_STATE_STYLE = {
    WorkLogState.RUNNING: shell_style(ShellTone.ACCENT),
    WorkLogState.COMPLETED: shell_style(ShellTone.MUTED),
    WorkLogState.FAILED: shell_style(ShellTone.ERROR),
    WorkLogState.DENIED: shell_style(ShellTone.MUTED) + Style(strike=True),
    WorkLogState.INTERRUPTED: shell_style(ShellTone.WARNING),
}

_STATE_ICON: dict[WorkLogState, StatusName] = {
    WorkLogState.RUNNING: "running",
    WorkLogState.COMPLETED: "completed",
    WorkLogState.FAILED: "failed",
    WorkLogState.DENIED: "denied",
    WorkLogState.INTERRUPTED: "interrupted",
}


def _state_icon(state: WorkLogState) -> Text:
    icon = status_icon(_STATE_ICON[state])
    if (
        state == WorkLogState.RUNNING
        and not reduced_motion_enabled()
        and int(time.monotonic() / 0.8) % 2 != 0
    ):
        return Text(" ", style=icon.style)
    return icon


def _tool_token_style(token_name: str) -> str:
    tokens = get_tui_tokens()
    return getattr(tokens, token_name, tokens.info)


def tool_style(name: str) -> ToolStyle:
    style = _TOOL_STYLES.get(name, ToolStyle(name, "⚙", "info"))
    return ToolStyle(style.label, style.icon, _tool_token_style(style.style))


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
    icon_style: str = "info",
    icon_renderable: RenderableType | None = None,
    children: list[RenderableType] | None = None,
) -> RenderableType:
    line = Text()
    if icon_renderable is None:
        line.append_text(_state_icon(state))
        line.append(" ")
    line.append(label, style="bold")
    if target:
        line.append(" ")
        line.append(target, style=tui_rich_style("muted"))
    line.append(" ")
    line.append(state.value, style=_STATE_STYLE[state])
    if detail:
        line.append(" · ", style=tui_rich_style("muted"))
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
    border_style: StyleType = "grey39",
) -> Panel:
    return Panel(
        body,
        title=title,
        title_align="left",
        subtitle=subtitle,
        subtitle_align="left",
        border_style=border_style,
        box=box.ROUNDED,
        padding=WORKLOG_PANEL_PADDING,
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
                preview_lines, _ = render_diff_preview(
                    path,
                    hunks,
                    added_total,
                    removed_total,
                    max_lines=8,
                )
                rendered.append(
                    render_worklog_card(
                        "Diff",
                        Group(*preview_lines),
                    )
                )
            continue
        if isinstance(block, BriefDisplayBlock):
            text = block.text.strip()
            if text:
                title = "Error" if is_error else "Report"
                style = tui_rich_style("error") if is_error else tui_rich_style("muted")
                if "\n" in text or len(text) > 100:
                    rendered.append(
                        render_worklog_card(
                            title,
                            Markdown(text, style=style),
                            border_style=tui_rich_style("error")
                            if is_error
                            else tui_rich_style("dim"),
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
            rendered.append(
                render_worklog_card("Todos", Text("\n".join(lines), style=tui_rich_style("muted")))
            )
            idx += 1
            continue
        if isinstance(block, BackgroundTaskDisplayBlock):
            rendered.append(
                render_worklog_card(
                    "Background task",
                    Text(
                        f"{block.task_id} [{block.status}] {block.kind}: {block.description}",
                        style=tui_rich_style("muted"),
                    ),
                )
            )
            idx += 1
            continue
        idx += 1
    return rendered
