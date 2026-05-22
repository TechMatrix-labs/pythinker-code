"""Pythinker assistant/user/custom message components.

Mirrors:

* ``modes/interactive/components/assistant-message.ts``
* ``modes/interactive/components/user-message.ts``
* ``modes/interactive/components/custom-message.ts``

Each function takes a tagged content payload and returns a Rich renderable
(no event-loop dependency). Callers render whatever shape they have —
Pythinker's ``_blocks.py`` already classifies content; it can hand off to
these for the card-style visual treatment when ``tui.style == "card"``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.style import Style as RichStyle
from rich.text import Text

from pythinker_code.ui.theme import tui_rich_style

__all__ = [
    "AssistantContent",
    "CustomMessageInput",
    "render_assistant_message",
    "render_custom_message",
    "render_user_message",
]


@dataclass(frozen=True, slots=True)
class AssistantContent:
    """One content block from an assistant message.

    ``kind="text"`` is plain Markdown content. ``kind="thinking"`` is the
    model's reasoning trace — rendered italic in muted color, or replaced
    with a static label when ``hide_thinking`` is set.
    """

    kind: Literal["text", "thinking"]
    text: str


@dataclass(frozen=True, slots=True)
class CustomMessageInput:
    """Input for :func:`render_custom_message`."""

    custom_type: str
    text: str


def render_user_message(text: str) -> RenderableType:
    """User message — compact tinted prompt block.

    Mirrors the reference ``UserPromptMessage`` shape: the caller owns
    inter-message spacing, while the message itself gets a subtle background
    and one cell of right padding. Avoid vertical padding so submitted prompts
    do not look like standalone panels.
    """
    md = Markdown(text)
    bg = tui_rich_style("user_message_bg")
    fg = tui_rich_style("user_message_text")
    style = bg + fg if fg else bg
    return Padding(md, (0, 1, 0, 0), style=style)


def render_assistant_message(
    content: Iterable[AssistantContent],
    *,
    hide_thinking: bool = False,
    hidden_thinking_label: str = "Thinking...",
    stop_reason: str | None = None,
    error_message: str | None = None,
) -> RenderableType | None:
    """Assistant message — markdown segments separated by spacer lines.

    Returns ``None`` when the message has no visible body and no error.
    Tool-call blocks are *not* rendered here — the host is expected to
    interleave tool execution cards itself (matching the same behavior).
    """
    blocks: list[RenderableType] = []
    items = [
        c
        for c in content
        if (c.kind == "text" and c.text.strip()) or (c.kind == "thinking" and c.text.strip())
    ]
    thinking_style = tui_rich_style("thinking_text") + RichStyle(italic=True)

    for i, item in enumerate(items):
        next_visible = i + 1 < len(items)
        if item.kind == "text":
            blocks.append(Markdown(item.text.strip()))
        elif item.kind == "thinking":
            if hide_thinking:
                blocks.append(Text(hidden_thinking_label, style=thinking_style))
            else:
                # Render as plain styled text — Markdown styling per-line is
                # awkward in Rich; the muted italic is what the eye expects.
                body = Text(item.text.strip(), style=thinking_style)
                blocks.append(body)
        if next_visible:
            blocks.append(Text(""))

    error: Text | None = None
    if stop_reason == "aborted":
        msg = (
            error_message
            if error_message and error_message != "Request was aborted"
            else "Operation aborted"
        )
        error = Text(msg, style=tui_rich_style("error"))
    elif stop_reason == "error":
        msg = error_message or "Unknown error"
        error = Text(f"Error: {msg}", style=tui_rich_style("error"))

    if not blocks and error is None:
        return None
    if error is not None:
        if blocks:
            blocks.append(Text(""))
        blocks.append(error)
    return Group(*blocks) if len(blocks) > 1 else blocks[0]


def render_custom_message(message: CustomMessageInput) -> RenderableType:
    """Custom message block — purple-tinted background with type label.

    Used by extensions to surface non-conversation messages (skill
    invocations, branch summaries, compaction notes) without making them
    look like user/assistant content.
    """
    label_style = tui_rich_style("custom_message_label") + RichStyle(bold=True)
    text_style = tui_rich_style("custom_message_text")
    bg_style = tui_rich_style("custom_message_bg")

    label = Text(f"[{message.custom_type}]", style=label_style)
    body = Markdown(message.text) if message.text.strip() else Text("")

    if isinstance(body, Markdown):
        block = Group(label, Text(""), body)
    elif text_style:
        block = Group(label, Text(""), Text(message.text, style=text_style))
    else:
        block = Group(label, Text(""), Text(message.text))
    return Padding(block, (0, 1), style=bg_style)
