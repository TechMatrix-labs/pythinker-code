"""Custom message components for skill invocations, compaction, and branches.

Each helper takes a small input dataclass and returns a Rich renderable. The
collapsed form is a single labelled line with an inline ``ctrl+e to expand``
hint; the expanded form shows the full body with a Markdown rendering for
the long-form fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.style import Style as RichStyle
from rich.text import Text

from pythinker_code.ui.shell.keymap import key_text
from pythinker_code.ui.theme import tui_rich_style

__all__ = [
    "BranchSummaryInput",
    "CompactionSummaryInput",
    "SkillInvocationInput",
    "render_branch_summary",
    "render_compaction_summary",
    "render_skill_invocation",
]


@dataclass(frozen=True, slots=True)
class SkillInvocationInput:
    """Input for :func:`render_skill_invocation`."""

    name: str
    content: str = ""


@dataclass(frozen=True, slots=True)
class CompactionSummaryInput:
    """Input for :func:`render_compaction_summary`."""

    tokens_before: int
    summary: str = ""


@dataclass(frozen=True, slots=True)
class BranchSummaryInput:
    """Input for :func:`render_branch_summary`."""

    summary: str = ""


def _label(text: str) -> Text:
    return Text(
        f"[{text}]",
        style=tui_rich_style("custom_message_label") + RichStyle(bold=True),
    )


def _hint(prefix_text: str, suffix_text: str) -> Text:
    """Produce ``"<prefix> <ctrl+e> <suffix>"`` styled as a hint line."""
    out = Text()
    out.append(prefix_text, style=tui_rich_style("custom_message_text"))
    expand = key_text("app.tools.expand")
    if expand:
        out.append(expand, style=tui_rich_style("dim"))
        out.append(" ", style=tui_rich_style("dim"))
    out.append(suffix_text, style=tui_rich_style("custom_message_text"))
    return out


def _frame(body: RenderableType) -> RenderableType:
    return Padding(body, (0, 1), style=tui_rich_style("custom_message_bg"))


def render_skill_invocation(
    skill: SkillInvocationInput, *, expanded: bool = False
) -> RenderableType:
    """Render a skill invocation block (collapsed by default)."""
    label = _label("skill")
    if expanded and skill.content.strip():
        header = f"**{skill.name}**\n\n"
        body = Markdown(header + skill.content)
        return _frame(Group(label, Text(""), body))
    line = Text()
    line.append_text(label)
    line.append(" ")
    line.append(skill.name, style=tui_rich_style("custom_message_text"))
    expand = key_text("app.tools.expand")
    if expand and skill.content.strip():
        line.append(f" ({expand} to expand)", style=tui_rich_style("dim"))
    return _frame(line)


def render_compaction_summary(
    compaction: CompactionSummaryInput, *, expanded: bool = False
) -> RenderableType:
    """Render a compaction summary message."""
    label = _label("compaction")
    token_str = f"{compaction.tokens_before:,}"
    if expanded and compaction.summary.strip():
        header = f"**Compacted from {token_str} tokens**\n\n"
        body = Markdown(header + compaction.summary)
        return _frame(Group(label, Text(""), body))
    body_text = _hint(
        f"Compacted from {token_str} tokens (",
        " to expand)" if compaction.summary.strip() else ")",
    )
    return _frame(Group(label, Text(""), body_text))


def render_branch_summary(branch: BranchSummaryInput, *, expanded: bool = False) -> RenderableType:
    """Render a session-branch summary."""
    label = _label("branch")
    if expanded and branch.summary.strip():
        header = "**Branch Summary**\n\n"
        body = Markdown(header + branch.summary)
        return _frame(Group(label, Text(""), body))
    body_text = _hint(
        "Branch summary (",
        " to expand)" if branch.summary.strip() else ")",
    )
    return _frame(Group(label, Text(""), body_text))
