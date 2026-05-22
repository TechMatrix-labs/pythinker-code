from rich.console import Console

from pythinker_code.utils.rich.markdown import Markdown


def test_markdown_html_block_renders_without_stack_error() -> None:
    console = Console(width=80, record=True)
    markdown = Markdown("<analysis>\nHello\n</analysis>\n")
    segments = list(console.render(markdown))
    rendered = "".join(segment.text for segment in segments)
    assert "<analysis>" in rendered


def test_wide_markdown_table_renders_as_readable_records() -> None:
    console = Console(width=72, record=True, color_system=None)
    markdown = Markdown(
        "| Area | Issue | Why it matters | Suggested improvement | Priority | Effort |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| Accessibility | Search input in `web/src/components/sessions.tsx` relies on "
        "placeholder text only. | Placeholder-only labels are weak for screen readers and "
        'disappear during typing. | Add `aria-label="Search sessions"` or a visually '
        "hidden label. | High | XS |\n"
    )

    console.print(markdown)
    output = console.export_text()

    assert "1. Accessibility" in output
    assert "Issue:" in output
    assert "Why it matters:" in output
    assert "Suggested improvement:" in output
    assert "Priority: High" in output
    assert "Effort: XS" in output


def test_fenced_code_block_renders_as_labeled_report_panel() -> None:
    console = Console(width=72, record=True, color_system=None)
    markdown = Markdown(
        "## Example\n\n```python\ndef review_target() -> str:\n    return 'ok'\n```\n"
    )

    console.print(markdown)
    output = console.export_text()

    assert "python" in output
    assert "def review_target" in output
    assert "╭" in output
    assert "╰" in output
