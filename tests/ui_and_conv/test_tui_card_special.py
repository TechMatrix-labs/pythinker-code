"""Tests for the small TUI components: visual_truncate + special messages."""

from __future__ import annotations

from pythinker_code.ui.shell.components import (
    BranchSummaryInput,
    CompactionSummaryInput,
    SkillInvocationInput,
    render_branch_summary,
    render_compaction_summary,
    render_plain,
    render_skill_invocation,
    truncate_to_visual_lines,
)

# ---------------------------------------------------------------------------
# truncate_to_visual_lines
# ---------------------------------------------------------------------------


def test_truncate_no_op_when_under_limit():
    res = truncate_to_visual_lines("a\nb", max_visual_lines=10, width=80)
    assert res.visual_lines == ["a", "b"]
    assert res.skipped_count == 0


def test_truncate_keeps_last_lines():
    res = truncate_to_visual_lines("a\nb\nc\nd\ne", max_visual_lines=2, width=80)
    assert res.visual_lines == ["d", "e"]
    assert res.skipped_count == 3


def test_truncate_wraps_long_lines_to_width():
    long = "x" * 25
    res = truncate_to_visual_lines(long, max_visual_lines=10, width=10)
    assert all(len(ln) <= 10 for ln in res.visual_lines)
    assert "".join(res.visual_lines) == long


def test_truncate_handles_empty_text():
    res = truncate_to_visual_lines("", max_visual_lines=5, width=80)
    assert res.visual_lines == []
    assert res.skipped_count == 0


def test_truncate_strips_ansi():
    res = truncate_to_visual_lines("\x1b[31mhello\x1b[0m", max_visual_lines=5, width=80)
    assert res.visual_lines == ["hello"]


# ---------------------------------------------------------------------------
# skill / compaction / branch
# ---------------------------------------------------------------------------


def test_skill_collapsed_shows_label_and_name():
    out = render_plain(
        render_skill_invocation(SkillInvocationInput(name="format", content="body")),
        width=60,
    )
    assert "[skill]" in out
    assert "format" in out
    assert "body" not in out  # collapsed


def test_skill_expanded_shows_body():
    out = render_plain(
        render_skill_invocation(
            SkillInvocationInput(name="format", content="full body here"),
            expanded=True,
        ),
        width=60,
    )
    assert "[skill]" in out
    assert "full body here" in out


def test_compaction_collapsed_includes_token_count():
    out = render_plain(
        render_compaction_summary(
            CompactionSummaryInput(tokens_before=12345, summary="post-compact"),
        ),
        width=60,
    )
    assert "[compaction]" in out
    assert "12,345" in out
    assert "post-compact" not in out


def test_compaction_expanded_shows_summary():
    out = render_plain(
        render_compaction_summary(
            CompactionSummaryInput(tokens_before=12345, summary="post-compact body"),
            expanded=True,
        ),
        width=60,
    )
    assert "post-compact body" in out


def test_branch_summary_collapsed_and_expanded():
    collapsed = render_plain(
        render_branch_summary(BranchSummaryInput(summary="branch body")), width=60
    )
    assert "[branch]" in collapsed
    assert "branch body" not in collapsed

    expanded = render_plain(
        render_branch_summary(BranchSummaryInput(summary="branch body"), expanded=True),
        width=60,
    )
    assert "branch body" in expanded
