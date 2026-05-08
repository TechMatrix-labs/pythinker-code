"""Pythinker TUI component foundation.

This package provides reusable rendering primitives modeled after the
internal component system. Components are pure
data-to-Rich-renderable adapters with no event-loop knowledge.
"""

from __future__ import annotations

from pythinker_code.ui.shell.components.base import TuiComponent
from pythinker_code.ui.shell.components.bash_execution import (
    BashExecutionState,
    render_bash_execution,
)
from pythinker_code.ui.shell.components.diff import (
    EditDiffResult,
    compute_edit_diff_string,
    render_diff,
)
from pythinker_code.ui.shell.components.footer import (
    FooterState,
    FooterUsage,
    format_tokens,
    render_footer,
)
from pythinker_code.ui.shell.components.key_hints import key_hint, raw_key_hint
from pythinker_code.ui.shell.components.messages import (
    AssistantContent,
    CustomMessageInput,
    render_assistant_message,
    render_custom_message,
    render_user_message,
)
from pythinker_code.ui.shell.components.render_utils import (
    VisualTruncateResult,
    cell_width,
    dim,
    render_plain,
    sanitize_ansi,
    truncate_to_visual_lines,
    truncate_to_width,
)
from pythinker_code.ui.shell.components.special_messages import (
    BranchSummaryInput,
    CompactionSummaryInput,
    SkillInvocationInput,
    render_branch_summary,
    render_compaction_summary,
    render_skill_invocation,
)
from pythinker_code.ui.shell.components.tool_execution import (
    ToolExecutionComponent,
    ToolExecutionStatus,
)

__all__ = [
    "AssistantContent",
    "BashExecutionState",
    "BranchSummaryInput",
    "CompactionSummaryInput",
    "CustomMessageInput",
    "EditDiffResult",
    "FooterState",
    "FooterUsage",
    "SkillInvocationInput",
    "ToolExecutionComponent",
    "ToolExecutionStatus",
    "TuiComponent",
    "VisualTruncateResult",
    "cell_width",
    "compute_edit_diff_string",
    "dim",
    "format_tokens",
    "key_hint",
    "raw_key_hint",
    "render_assistant_message",
    "render_bash_execution",
    "render_branch_summary",
    "render_compaction_summary",
    "render_custom_message",
    "render_diff",
    "render_footer",
    "render_plain",
    "render_skill_invocation",
    "render_user_message",
    "sanitize_ansi",
    "truncate_to_visual_lines",
    "truncate_to_width",
]
