"""Pythinker bash execution component.



Render bash as a compact Codex-style execution cell: a lifecycle bullet,
a ``$ <command>`` header, indented output, and small status/footer hints.
We model the same shape as a stateless Rich renderable factory so callers
(the bash tool renderer or future ``Shell`` history) can drive it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from rich.console import Group, RenderableType
from rich.style import Style as RichStyle
from rich.text import Text

from pythinker_code.ui.shell.components.render_utils import (
    sanitize_ansi,
    truncate_middle_to_visual_lines,
)
from pythinker_code.ui.shell.motion import reduced_motion_enabled
from pythinker_code.ui.theme import tui_rich_style

__all__ = [
    "BashExecutionState",
    "format_bash_command_for_header",
    "render_bash_execution",
    "render_bash_result_output",
]

PREVIEW_LINES = 5
MAX_COMMAND_DISPLAY_LINES = 2
MAX_COMMAND_DISPLAY_CHARS = 160

BashStatus = Literal["pending", "running", "complete", "error", "cancelled"]


@dataclass(frozen=True, slots=True)
class BashExecutionState:
    """Inputs for :func:`render_bash_execution`.

    Attributes:
        command: The shell command being executed.
        output: Combined stdout/stderr captured so far. Streaming-friendly —
            callers may pass partial output on every redraw.
        status: Lifecycle state. ``"pending"`` and ``"running"`` show the
            spinner placeholder line; ``"complete"`` / ``"error"`` /
            ``"cancelled"`` add a footer note.
        exit_code: Exit code for the finished process (only used in the
            ``"error"`` footer line).
        expanded: When ``True`` the full output is shown; otherwise the
            tail is truncated to ``PREVIEW_LINES`` lines.
        truncated: ``True`` when ``output`` was already byte-truncated
            upstream (for the LLM context cap). Drives the trailing hint.
        full_output_path: Optional spill-file path for very long output.
        exclude_from_context: ``!!`` prefix mode — render in dim instead of
            the bash-mode accent.
    """

    command: str
    output: str = ""
    status: BashStatus = "running"
    exit_code: int | None = None
    expanded: bool = False
    truncated: bool = False
    full_output_path: str | None = None
    exclude_from_context: bool = False
    header_suffix: str = ""
    """Muted metadata appended after the command (e.g. ``" (timeout 600s)"``)."""


def _accent_style(state: BashExecutionState) -> RichStyle:
    return tui_rich_style("muted" if state.exclude_from_context else "bash_mode")


def _command_strip_style(state: BashExecutionState) -> RichStyle:
    """Background tint for the ``$ cmd`` portion of the bash header.

    Mirrors the dark 256-color strip used by the reference renderer; on light
    themes we use the tool pending background so the strip still reads as a
    contiguous run rather than blending into the surrounding card.
    """
    accent = _accent_style(state)
    bg = tui_rich_style("tool_pending_bg")
    return accent + bg + RichStyle(bold=True)


def _output_lines(output: str) -> list[str]:
    cleaned = sanitize_ansi(output).replace("\r\n", "\n").replace("\r", "\n")
    if cleaned == "":
        return []
    return cleaned.split("\n")


def _pulsing_marker() -> Text:
    glyph = "●" if reduced_motion_enabled() or int(time.monotonic() / 0.8) % 2 == 0 else " "
    return Text(f"{glyph} ", style=tui_rich_style("muted"))


def _extract_comment_label(command: str) -> str | None:
    for line in command.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#!"):
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
        return None
    return None


def format_bash_command_for_header(command: str, *, expanded: bool) -> str:
    if expanded:
        return command

    label = _extract_comment_label(command)
    if label:
        command = label

    lines = command.splitlines()
    needs_line_truncation = len(lines) > MAX_COMMAND_DISPLAY_LINES
    needs_char_truncation = len(command) > MAX_COMMAND_DISPLAY_CHARS
    if not needs_line_truncation and not needs_char_truncation:
        return command

    truncated = "\n".join(lines[:MAX_COMMAND_DISPLAY_LINES]) if needs_line_truncation else command
    if len(truncated) > MAX_COMMAND_DISPLAY_CHARS:
        truncated = truncated[:MAX_COMMAND_DISPLAY_CHARS]
    return truncated.rstrip() + "…"


def _status_header(state: BashExecutionState) -> Text:
    if state.status in ("pending", "running"):
        header = _pulsing_marker()
        header.append("Running", style=tui_rich_style("muted") + RichStyle(bold=True))
    elif state.status == "error":
        header = Text("✘ ", style=tui_rich_style("error"))
        header.append("Ran", style=tui_rich_style("error") + RichStyle(bold=True))
    elif state.status == "cancelled":
        header = Text("● ", style=tui_rich_style("warning"))
        header.append("Cancelled", style=tui_rich_style("warning") + RichStyle(bold=True))
    else:
        header = Text("✔ ", style=tui_rich_style("success"))
        header.append("Ran", style=tui_rich_style("success") + RichStyle(bold=True))

    strip = _command_strip_style(state)
    header.append(" ")
    header.append("$ ", style=strip)
    header.append(
        format_bash_command_for_header(state.command, expanded=state.expanded),
        style=strip,
    )
    if state.header_suffix:
        header.append(state.header_suffix, style=tui_rich_style("muted"))
    return header


def _display_output_lines(state: BashExecutionState, *, width: int) -> tuple[list[str], int]:
    lines = _output_lines(state.output)
    if state.expanded:
        return lines, 0
    visual_width = max(1, width - 4)
    result = truncate_middle_to_visual_lines(
        "\n".join(lines),
        max_visual_lines=PREVIEW_LINES,
        width=visual_width,
        hint="ctrl+o to expand",
    )
    return result.visual_lines, result.skipped_count


def _output_block(display: list[str]) -> Text | None:
    if not display:
        return None
    body = Text(style=tui_rich_style("muted"))
    for index, line in enumerate(display):
        if index:
            body.append("\n")
        body.append("  ⎿ " if index == 0 else "    ")
        body.append(line)
    return body


def _result_output_block(display: list[str], *, status: BashStatus) -> Text | None:
    if not display:
        return None
    body_style = tui_rich_style("error") if status == "error" else tui_rich_style("muted")
    body = Text(style=body_style)
    for index, line in enumerate(display):
        if index:
            body.append("\n")
        body.append(line)
    return body


def _bash_footer_lines(
    state: BashExecutionState, *, hidden: int, total_output_lines: int
) -> list[Text]:
    footer_lines: list[Text] = []
    if hidden > 0 and state.expanded:
        footer_lines.append(Text("ctrl+o to collapse", style=tui_rich_style("muted")))
    if state.status == "cancelled":
        footer_lines.append(Text("cancelled", style=tui_rich_style("warning")))
    elif state.status == "error" and state.exit_code is not None:
        footer_lines.append(Text(f"exit {state.exit_code}", style=tui_rich_style("error")))
    elif state.status in ("pending", "running"):
        footer_lines.append(Text("esc to cancel", style=tui_rich_style("muted")))

    if state.truncated and state.full_output_path:
        footer_lines.append(
            Text(
                f"output truncated · full output: {state.full_output_path}",
                style=tui_rich_style("warning"),
            )
        )
    return footer_lines


def render_bash_result_output(state: BashExecutionState, *, width: int = 100) -> RenderableType:
    """Render only bash output/status for placement under a response gutter.

    The tool header is rendered by the caller, so this avoids the duplicate
    ``Ran $ ...`` line and avoids embedding another ``⎿`` gutter inside the
    shared ``MessageResponse`` gutter.
    """
    display, hidden = _display_output_lines(state, width=width)
    total_output_lines = len(_output_lines(state.output))
    children: list[RenderableType] = []
    output = _result_output_block(display, status=state.status)
    if output is not None:
        children.append(output)
    elif state.status not in ("pending", "running"):
        children.append(Text("(No output)", style=tui_rich_style("muted")))
    children.extend(_bash_footer_lines(state, hidden=hidden, total_output_lines=total_output_lines))
    return Group(*children) if len(children) > 1 else children[0]


def render_bash_execution(state: BashExecutionState, *, width: int = 100) -> RenderableType:
    """Build the standalone bash execution renderable for *state*."""
    display, hidden = _display_output_lines(state, width=width)
    total_output_lines = len(_output_lines(state.output))

    children: list[RenderableType] = [_status_header(state)]
    output = _output_block(display)
    if output is not None:
        children.append(output)
    for line in _bash_footer_lines(state, hidden=hidden, total_output_lines=total_output_lines):
        indented = Text("  ", style=line.style)
        indented.append_text(line)
        children.append(indented)
    return Group(*children)
