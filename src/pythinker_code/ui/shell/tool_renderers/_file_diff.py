"""Helpers for Blackbox-style file diff tool renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pythinker_core.tooling import DisplayBlock
from rich.console import RenderableType
from rich.text import Text

from pythinker_code.tools.display import DiffDisplayBlock
from pythinker_code.ui.shell.components import compute_edit_diff_string, render_diff
from pythinker_code.ui.shell.tool_renderers import ToolResultPayload
from pythinker_code.ui.shell.tool_renderers._render_utils import fg


@dataclass(frozen=True, slots=True)
class DiffPreview:
    diff_text: str
    added: int
    removed: int
    summary_only: bool = False


def display_blocks_from_result(result: ToolResultPayload) -> list[DisplayBlock]:
    display_raw = result.details.get("display")
    if not isinstance(display_raw, list):
        return []
    display = cast("list[object]", display_raw)
    return [block for block in display if isinstance(block, DisplayBlock)]


def diff_blocks_from_result(result: ToolResultPayload) -> list[DiffDisplayBlock]:
    return [
        block for block in display_blocks_from_result(result) if isinstance(block, DiffDisplayBlock)
    ]


def _diff_counts(diff_text: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _prefix_diff_summary_lines(prefix: str, text: str) -> str:
    lines = text.splitlines() or [""]
    return "\n".join(f"{prefix} {line}" for line in lines)


def preview_from_diff_blocks(blocks: list[DiffDisplayBlock]) -> DiffPreview | None:
    if not blocks:
        return None

    chunks: list[str] = []
    summary_only = False
    for block in blocks:
        if block.is_summary:
            summary_only = True
            chunks.append(
                "\n".join(
                    [
                        _prefix_diff_summary_lines("-", block.old_text),
                        _prefix_diff_summary_lines("+", block.new_text),
                    ]
                )
            )
            continue
        diff = compute_edit_diff_string(
            block.old_text,
            block.new_text,
            old_start=block.old_start,
            new_start=block.new_start,
        ).diff
        if diff:
            chunks.append(diff)

    diff_text = "\n ...\n".join(chunks)
    if not diff_text:
        return None
    added, removed = _diff_counts(diff_text)
    return DiffPreview(diff_text=diff_text, added=added, removed=removed, summary_only=summary_only)


def preview_from_result(result: ToolResultPayload) -> DiffPreview | None:
    return preview_from_diff_blocks(diff_blocks_from_result(result))


def change_summary_text(added: int, removed: int) -> Text:
    parts: list[Text | str] = []
    if added:
        text = Text("Added ")
        text.append(str(added), style="bold")
        text.append(f" line{'s' if added != 1 else ''}")
        parts.append(text)
    if removed:
        text = Text("Removed ")
        text.append(str(removed), style="bold")
        text.append(f" line{'s' if removed != 1 else ''}")
        parts.append(text)
    if not parts:
        return fg("tool_output", "No line changes")

    out = Text()
    for index, part in enumerate(parts):
        if index:
            out.append(", ")
        if isinstance(part, Text):
            out.append_text(part)
        else:
            out.append(part)
    return fg("tool_output", out)


def diff_frame(diff_text: str, *, width: int) -> RenderableType:
    """Render the Blackbox-style inline diff body.

    The reference terminal transcript shows the summary line immediately
    followed by numbered +/- rows, without an ASCII box or dashed rails.
    """
    _ = width
    return render_diff(diff_text)
