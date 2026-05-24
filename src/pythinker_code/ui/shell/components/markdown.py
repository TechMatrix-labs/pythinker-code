"""Pythinker markdown renderer with bordered code blocks and themed accents.

Wraps Rich's ``Markdown`` element with three changes:

1. Fenced code blocks are framed by ``╭─ {lang}`` / ``╰─`` rules in the
   markdown palette's ``code_block_border`` color and tinted with the
   ``code_block_bg`` background.
2. Inline elements (headings, strong, emphasis, links, inline code, block
   quotes) resolve against ``pythinker_code.ui.theme.get_markdown_colors``
   so dark/light themes share the same renderer.
3. A small streaming helper, :class:`PythinkerMarkdownStream`, buffers
   incoming deltas and flushes when a safe boundary appears — either a
   blank line *or* a sentence-final character outside of any open fence,
   so long paragraphs no longer stall the visible stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_it import MarkdownIt

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.padding import Padding
from rich.style import Style as RichStyle
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme

from pythinker_code.ui.shell.spacing import CODE_BLOCK_PADDING
from pythinker_code.ui.theme import ThemeName, get_markdown_colors
from pythinker_code.utils.rich.markdown import CodeBlock, Markdown

__all__ = [
    "PythinkerMarkdown",
    "PythinkerMarkdownStream",
    "pythinker_markdown",
]


class _BorderedCodeBlock(CodeBlock):
    """Code block with ``╭─ lang`` / ``╰─`` border rules and background tint."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        colors = get_markdown_colors()
        border_style = RichStyle(color=colors.code_block_border, bold=True)
        bg_style = RichStyle(bgcolor=colors.code_block_bg) if colors.code_block_bg else RichStyle()

        label = self.lexer_name.strip() or "code"
        opener_text = f"╭─ {label} "
        opener = Text(
            opener_text + "─" * max(0, options.max_width - cell_len(opener_text)),
            style=border_style,
        )
        code_text = str(self.text).rstrip("\n")
        body: RenderableType = Syntax(
            code_text,
            self.lexer_name,
            theme=self.theme,
            word_wrap=True,
            padding=CODE_BLOCK_PADDING,
            background_color=colors.code_block_bg or None,
        )
        if bg_style:
            body = Padding(body, (0, 0), style=bg_style)
        closer = Text("╰" + "─" * max(0, options.max_width - 1), style=border_style)
        yield opener
        yield body
        yield closer


def _markdown_style_overrides(theme: ThemeName | None = None) -> dict[str, RichStyle]:
    """Translate the active markdown palette into Rich style names."""
    colors = get_markdown_colors(theme)
    return {
        "markdown.h1": RichStyle(color=colors.heading, bold=True),
        "markdown.h1.border": RichStyle(color=colors.heading),
        "markdown.h1.underline": RichStyle(color=colors.heading),
        "markdown.h2": RichStyle(bold=True, underline=True),
        "markdown.h3": RichStyle(color=colors.heading, bold=True),
        "markdown.h4": RichStyle(color=colors.heading, bold=True, dim=True),
        "markdown.strong": RichStyle(color=colors.strong, bold=True),
        "markdown.em": RichStyle(color=colors.emphasis, italic=True),
        "markdown.emph": RichStyle(color=colors.emphasis, italic=True),
        "markdown.code": RichStyle(color=colors.inline_code, bold=True),
        "markdown.link": RichStyle(color=colors.link, underline=True),
        "markdown.link_url": RichStyle(color=colors.link, underline=True),
        "markdown.block_quote": RichStyle(color=colors.quote, italic=True),
        "markdown.hr": RichStyle(color=colors.code_block_border),
        "markdown.code_block": RichStyle(color=colors.inline_code),
        "markdown.code_block.border": RichStyle(color=colors.code_block_border, bold=True),
        "markdown.item.bullet": RichStyle(color=colors.strong, bold=True),
        "markdown.item.number": RichStyle(color=colors.strong, bold=True),
    }


class PythinkerMarkdown(Markdown):
    """Drop-in replacement for ``rich.markdown.Markdown`` with the Pythinker palette."""

    elements = {**Markdown.elements, "fence": _BorderedCodeBlock, "code_block": _BorderedCodeBlock}

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        overrides = _markdown_style_overrides()
        with console.use_theme(Theme(overrides, inherit=True)):
            yield from super().__rich_console__(console, options)


def pythinker_markdown(text: str, *, code_theme: str = "monokai") -> PythinkerMarkdown:
    """Build a :class:`PythinkerMarkdown` with the palette pre-wired."""
    return PythinkerMarkdown(text, code_theme=code_theme)


# ---------------------------------------------------------------------------
# Streaming boundary helper
# ---------------------------------------------------------------------------


_SENTENCE_END = (".", "!", "?", ";", ":")
_SELF_CLOSING_BLOCKS = frozenset(("fence", "code_block", "hr", "html_block"))

# Lazy-initialized markdown-it parser for incremental token commitment.
_md_parser: MarkdownIt | None = None


def _get_md_parser() -> MarkdownIt:
    global _md_parser
    if _md_parser is None:
        from markdown_it import MarkdownIt

        # Match the extensions used by the rendering path
        # (pythinker_code.utils.rich.markdown.Markdown) so that block
        # boundaries are detected consistently.
        _md_parser = MarkdownIt().enable("strikethrough").enable("table")
    return _md_parser


def markdown_commit_boundary(text: str) -> int | None:
    """Return the offset up to which streamed markdown can be committed.

    The last top-level block is treated as still mutable, so callers only
    permanently print completed blocks. Nested tokens (list items, blockquote
    children, table rows) stay with their parent block.
    """
    md = _get_md_parser()
    tokens = md.parse(text)

    block_maps: list[list[int]] = []
    depth = 0
    for token in tokens:
        if token.nesting == 1:
            if depth == 0 and token.map is not None:
                block_maps.append(token.map)
            depth += 1
        elif token.nesting == -1:
            depth -= 1
        elif depth == 0 and token.type in _SELF_CLOSING_BLOCKS and token.map is not None:
            block_maps.append(token.map)

    if len(block_maps) < 2:
        return None

    target_line = block_maps[-2][1]
    offset = 0
    for _ in range(target_line):
        offset = text.index("\n", offset) + 1
    return offset


def _find_stream_safe_boundary(text: str) -> int | None:
    """Return an index in ``text`` that is safe to flush, or ``None``.

    Parser-backed block commitment handles multi-line markdown constructs such
    as tables, lists, and fenced code. A sentence-final fallback is kept only
    for single-line prose so long plain paragraphs still become visible without
    waiting for a blank line or a second markdown block.
    """
    boundary = markdown_commit_boundary(text)
    if boundary is not None:
        return boundary

    if "\n" in text:
        return None
    stripped = text.rstrip()
    if stripped.endswith(_SENTENCE_END):
        return len(text)
    return None


@dataclass(slots=True)
class PythinkerMarkdownStream:
    """Buffer streamed markdown deltas and yield safe-to-render slices."""

    pending: str = field(default="")

    def push(self, delta: str) -> str | None:
        """Append ``delta`` and return the next ready slice, or ``None``."""
        self.pending += delta
        cut = _find_stream_safe_boundary(self.pending)
        if cut is None or cut == 0:
            return None
        ready = self.pending[:cut]
        self.pending = self.pending[cut:]
        return ready

    def flush(self) -> str | None:
        """Return any remaining buffered markdown, clearing the buffer."""
        if not self.pending.strip():
            self.pending = ""
            return None
        pending = self.pending
        self.pending = ""
        return pending
