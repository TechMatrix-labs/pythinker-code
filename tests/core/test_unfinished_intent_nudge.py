from __future__ import annotations

import pytest

from pythinker_code.soul.pythinkersoul import _looks_like_unfinished_intent


@pytest.mark.parametrize(
    "text",
    [
        # The exact message that ended the deep-scan turn with no report.
        "All 4 agents completed. Let me synthesize the findings into a unified report.",
        "Let me synthesize the findings into a unified report.",
        "I'll now write the full report.",
        "Let me cross-check the most critical findings before presenting the report.",
        "Next, I'll compile the results into a summary.",
        "Now let me gather the remaining details.",
    ],
)
def test_detects_unfinished_intent(text: str) -> None:
    assert _looks_like_unfinished_intent(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        # Closing offer, not a promise of work this turn.
        "Let me know if you need anything else.",
        # No intent lead in the final sentence.
        "Done. The bug is fixed and all tests pass.",
        "The report is ready above.",
        # A question hands control back to the user.
        "Should I proceed with the refactor, or wait?",
        # Intent lead but no action verb tied to producing work.
        "I'll keep that in mind.",
        # A real, substantive answer is long enough not to be a bare preamble.
        "Let me explain the architecture. " + ("The system has many layers. " * 20),
    ],
)
def test_ignores_non_intent_or_substantive(text: str) -> None:
    assert _looks_like_unfinished_intent(text) is False
