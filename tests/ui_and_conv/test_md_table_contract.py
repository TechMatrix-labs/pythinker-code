# tests/ui_and_conv/test_md_table_contract.py
"""Tier-1 contract tests for Markdown table rendering (spec area 3).

Each test names the bug class it guards. These assert the EXISTING stack
(pythinker_markdown over markdown-it + Rich) already meets the contract; a
failure is a real regression to surface, not to silence.
"""

from __future__ import annotations

from pythinker_code.ui.shell.components.markdown import (
    _escape_code_span_pipes,
    pythinker_markdown,
)
from tests.ui_and_conv._md_contract_helpers import render_plain


def test_table_with_piped_inline_code_keeps_columns():
    """Bug class: 'tables breaking on piped inline code'."""
    md = "| Expr | Meaning |\n| --- | --- |\n| `a | b` | bitwise or |\n| plain | text |\n"
    out = render_plain(pythinker_markdown(md), width=80)
    # Both data rows survive as a table (cell contents present, not collapsed
    # into a single prose paragraph).
    assert "bitwise or" in out
    assert "plain" in out
    assert "text" in out


def test_table_with_escaped_pipes_keeps_literal_pipe():
    """Bug class: escaped pipe must render as a literal '|', not split a cell."""
    md = "| Col |\n| --- |\n| a \\| b |\n"
    out = render_plain(pythinker_markdown(md), width=80)
    assert "a | b" in out or "a \\| b" not in out  # literal pipe preserved
    assert "Col" in out


def test_escape_code_span_pipes_standard_case():
    # raw pipe inside a single-backtick code span gets escaped; outer table pipes untouched
    assert _escape_code_span_pipes("| `a | b` | bitwise or |") == "| `a \\| b` | bitwise or |"


def test_escape_code_span_pipes_double_backticks():
    assert _escape_code_span_pipes("| ``a | b`` | target |") == "| ``a \\| b`` | target |"


def test_escape_code_span_pipes_already_escaped_is_idempotent():
    # must NOT double-escape an existing \| -> \\|
    assert _escape_code_span_pipes("| `a \\| b` | target |") == "| `a \\| b` | target |"


def test_escape_code_span_pipes_no_code_span_unchanged():
    assert _escape_code_span_pipes("| regular | cell |") == "| regular | cell |"


def test_escape_code_span_pipes_leaves_lone_backtick_delimiters_alone():
    # A single unbalanced backtick is not a code span, so the real '|' delimiters
    # must be preserved (no closing run -> no match -> no escaping).
    assert _escape_code_span_pipes("| a ` b | c |") == "| a ` b | c |"


def test_prose_inline_code_pipe_is_not_corrupted_with_backslash():
    """Scope guarantee: the escaper only runs on table rows. Inline code in plain
    prose must render its pipe literally, never gain a stray backslash (which a
    CommonMark code span would show verbatim)."""
    out = render_plain(pythinker_markdown("Use `a | b` for bitwise or.\n"), width=80)
    assert "a | b" in out
    assert "\\|" not in out
