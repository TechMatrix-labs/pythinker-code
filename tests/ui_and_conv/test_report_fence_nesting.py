# tests/ui_and_conv/test_report_fence_nesting.py
"""H1: a ```report block shown INSIDE an outer documentation fence must not be
promoted to a report. The flat _REPORT_FENCE_RE regex cannot see fence nesting;
an AST walk over top-level fence tokens structurally can.
"""

from __future__ import annotations

from pythinker_code.ui.shell.components.report import has_report_block, render_agent_body
from tests.ui_and_conv._md_contract_helpers import render_plain

# A 4-backtick outer fence whose body is a literal ```report example. markdown-it
# parses the outer fence as ONE token, so the inner block is documentation text,
# not a real report.
_NESTED = (
    "Here is how to emit a report:\n\n"
    "````markdown\n"
    "```report\n"
    '{"title": "Example", "findings": [{"title": "x", "severity": "high"}]}\n'
    "```\n"
    "````\n"
)


def test_nested_report_fence_is_not_detected():
    assert has_report_block(_NESTED) is False


def test_nested_report_fence_renders_as_documentation_not_report():
    out = render_plain(render_agent_body(_NESTED))
    # The inner block stays verbatim documentation; it is NOT promoted to the
    # report renderer (which would drop the JSON and print a tally).
    assert '"title": "Example"' in out
    assert "1 high" not in out  # no report tally emitted


def test_top_level_report_fence_still_promoted():
    """Regression guard: the real top-level case must keep working."""
    text = (
        "Intro.\n\n```report\n"
        '{"title": "Real", "findings": [{"title": "bug", "severity": "medium"}]}\n'
        "```\n"
    )
    out = render_plain(render_agent_body(text))
    assert "Real" in out
    assert "1 medium" in out
    assert '"severity"' not in out  # rendered as a report, not raw JSON


def test_report_fence_with_exotic_line_separator_does_not_leak_delimiter():
    """Regression: a non-newline Unicode line separator (here U+0085 NEL) in the
    prose before a valid top-level report must not desync the line slicing.

    markdown-it's ``token.map`` counts only ``\\n``; ``render_agent_body`` must
    split on ``\\n`` only. ``str.splitlines`` also breaks on \\f \\v \\x85   ,
    which would shift indices and leak the closing ``` fence into the trailing
    prose, rendering as a spurious empty bordered code block under the report.
    """
    text = (
        "intro\x85more\n\n```report\n"
        '{"title": "Real", "findings": [{"title": "bug", "severity": "medium"}]}\n'
        "```\n"
    )
    out = render_plain(render_agent_body(text))
    assert "Real" in out
    assert "1 medium" in out
    # No leaked closing fence -> no spurious bordered code block under the report.
    assert "```" not in out
    assert "╭" not in out and "╰" not in out
