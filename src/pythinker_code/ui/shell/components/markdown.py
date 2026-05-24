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

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.padding import Padding
from rich.style import Style as RichStyle
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme

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
            padding=(0, 1),
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


_FENCE_CHARS = ("`", "~")
_SENTENCE_END = (".", "!", "?", ";", ":")


@dataclass(slots=True)
class _FenceMarker:
    char: str
    length: int


def _parse_fence_opener(line: str) -> _FenceMarker | None:
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > 3 or not stripped:
        return None
    ch = stripped[0]
    if ch not in _FENCE_CHARS:
        return None
    length = 0
    for c in stripped:
        if c == ch:
            length += 1
        else:
            break
    if length < 3:
        return None
    info = stripped[length:]
    if ch == "`" and "`" in info:
        return None
    return _FenceMarker(char=ch, length=length)


def _line_closes_fence(line: str, opener: _FenceMarker) -> bool:
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > 3:
        return False
    length = 0
    for c in stripped:
        if c == opener.char:
            length += 1
        else:
            break
    if length < opener.length:
        return False
    rest = stripped[length:]
    return all(c in " \t" for c in rest)


def _find_stream_safe_boundary(text: str) -> int | None:
    """Return an index in ``text`` that is safe to flush, or ``None``.

    Safe boundaries are blank lines outside any open code fence, or — to avoid
    the well-known long-paragraph stall — the end of a non-fenced line that
    ends in sentence-final punctuation.
    """
    open_fence: _FenceMarker | None = None
    last_boundary: int | None = None
    cursor = 0
    for line in text.splitlines(keepends=True):
        line_end = cursor + len(line)
        content = line.rstrip("\n")
        if open_fence is not None:
            if _line_closes_fence(content, open_fence):
                open_fence = None
                last_boundary = line_end
            cursor = line_end
            continue
        opener = _parse_fence_opener(content)
        if opener is not None:
            open_fence = opener
            cursor = line_end
            continue
        if not content.strip() or content.rstrip().endswith(_SENTENCE_END):
            last_boundary = line_end
        cursor = line_end
    return last_boundary


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
