from rich.console import Console

from pythinker_code.ui.shell.components.markdown import PythinkerMarkdown
from pythinker_code.ui.shell.components.special_messages import (
    SkillInvocationInput,
    render_skill_invocation,
)


def _render_text(renderable: object, *, width: int = 72) -> str:
    console = Console(width=width, record=True, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_shell_markdown_uses_pythinker_code_block_frame() -> None:
    output = _render_text(
        PythinkerMarkdown(
            "## Example\n\n```python\ndef review_target() -> str:\n    return 'ok'\n```\n"
        )
    )

    assert "python" in output
    assert "def review_target" in output
    assert "╭" in output
    assert "╰" in output


def test_shell_markdown_keeps_rich_fork_table_records() -> None:
    output = _render_text(
        PythinkerMarkdown(
            "| Area | Issue | Why it matters | Suggested improvement | Priority | Effort |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| Accessibility | Search input relies on placeholder text only. | "
            "Placeholder-only labels are weak for screen readers. | Add an aria-label. | "
            "High | XS |\n"
        )
    )

    assert "1. Accessibility" in output
    assert "Issue:" in output
    assert "Why it matters:" in output
    assert "Suggested improvement:" in output
    assert "Priority: High" in output
    assert "Effort: XS" in output


def test_expanded_special_messages_use_shell_markdown_renderer() -> None:
    output = _render_text(
        render_skill_invocation(
            SkillInvocationInput("demo", "```python\nprint('themed')\n```"),
            expanded=True,
        )
    )

    assert "[skill]" in output
    assert "python" in output
    assert "print('themed')" in output
    assert "╭" in output
    assert "╰" in output
