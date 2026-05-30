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

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from markdown_it import MarkdownIt

from rich import box
from rich.console import Console, ConsoleOptions, RenderResult
from rich.panel import Panel
from rich.style import Style as RichStyle
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from pythinker_code.ui.shell.components.render_utils import sanitize_ansi
from pythinker_code.ui.shell.spacing import CODE_BLOCK_PADDING, blank_row
from pythinker_code.ui.theme import ThemeName, get_markdown_colors
from pythinker_code.utils.rich.markdown import CodeBlock, Markdown
from pythinker_code.utils.rich.syntax import PYTHINKER_ANSI_THEME_NAME

_MARKDOWN_ICON_REPLACEMENTS: dict[str, str] = {
    "⏺": "•",
    "✅": "✓",
    "☑️": "✓",
    "☑": "✓",
    "✔️": "✓",
    "✔": "✓",
    "❌": "×",
    "✖️": "×",
    "✖": "×",
    "🚫": "×",
    "⚠️": "!",
    "⚠": "!",
    "🔴": "●",
    "🟠": "●",
    "🟡": "●",
    "🟢": "●",
    "🔵": "●",
    "🟣": "●",
    "⚫": "●",
    "⚪": "○",
    "🔍": "⌕",
    "🔎": "⌕",
    "📋": "▣",
    "📝": "▣",
    "📌": "•",
}
_MARKDOWN_ICON_KEYS: tuple[str, ...] = tuple(
    sorted(_MARKDOWN_ICON_REPLACEMENTS, key=len, reverse=True)
)
_FENCE_RE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})")
_PRIORITY_MATRIX_ROW_RE = re.compile(
    r"^\s*(?P<id>[A-Z]{1,3}\d+)\s*(?:[─━—-]|\s){2,}\s*"
    r"(?P<severity>CRITICAL|HIGH|MEDIUM|LOW|INFO)\s*$",
    re.IGNORECASE,
)
_PRIORITY_MATRIX_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
# A GFM table delimiter run, e.g. ``|---|:--:|---|``. Two or more dashes per
# cell keeps stray inline ``|-|`` out of the match.
_DELIM_RUN_RE = re.compile(r"\|(?:\s*:?-{2,}:?\s*\|)+")
# A header line: optional prose prefix, then a trailing run of pipe cells.
_HEADER_RE = re.compile(r"^(?P<prefix>.*?)(?P<cells>(?:\|[^\n|]*)+\|)\s*$")


__all__ = [
    "PythinkerMarkdown",
    "PythinkerMarkdownStream",
    "pythinker_markdown",
]


def _priority_matrix_rows(code_text: str) -> list[tuple[str, str]] | None:
    rows: list[tuple[str, str]] = []
    meaningful_lines = 0
    for line in code_text.splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) <= {"─", "━", "—", "-", " "}:
            continue
        meaningful_lines += 1
        match = _PRIORITY_MATRIX_ROW_RE.match(stripped)
        if match is None:
            return None
        rows.append((match.group("id"), match.group("severity").upper()))
    if len(rows) < 3 or meaningful_lines != len(rows):
        return None
    return rows


def _render_priority_matrix(rows: list[tuple[str, str]]) -> Table:
    grouped: dict[str, list[str]] = {severity: [] for severity in _PRIORITY_MATRIX_SEVERITIES}
    for item_id, severity in rows:
        grouped.setdefault(severity, []).append(item_id)

    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", no_wrap=True)
    table.add_column(no_wrap=False)
    for severity in _PRIORITY_MATRIX_SEVERITIES:
        items = grouped.get(severity) or []
        if not items:
            continue
        table.add_row(Text(severity.title(), style="bold"), "  ".join(items))
    return table


def _is_table_separator_line(line: str) -> bool:
    return _TABLE_SEPARATOR_RE.match(line) is not None


def _is_table_header_fragment(fragment: str) -> bool:
    stripped = fragment.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    if _is_table_separator_line(stripped):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return len(cells) >= 2 and any(cells)


def _find_crammed_table_header_start(line: str) -> int | None:
    if line.lstrip().startswith("|"):
        return None
    for index, char in enumerate(line):
        if char != "|" or not line[:index].strip():
            continue
        if _is_table_header_fragment(line[index:]):
            return index
    return None


def _repair_crammed_markdown_tables(markup: str) -> str:
    """Split report headings accidentally glued to a following Markdown table.

    Streaming model output occasionally drops the newline between a section
    title and a table header, producing text such as ``Medium| # | File |``.
    Markdown then treats the whole table as a paragraph and renders dense report
    rows as crammed prose. Repair only this narrow, table-separator-confirmed
    shape, and never touch fenced code.
    """
    if "|" not in markup:
        return markup

    lines = markup.splitlines(keepends=True)
    if len(lines) < 2:
        return markup

    repaired: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        eol = line[len(body) :]
        match = _FENCE_RE.match(body)
        if in_fence:
            repaired.append(line)
            if match is not None:
                fence = match.group("fence")
                if fence.startswith(fence_char) and len(fence) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            continue
        if match is not None:
            fence = match.group("fence")
            in_fence = True
            fence_char = fence[0]
            fence_len = len(fence)
            repaired.append(line)
            continue

        split_at: int | None = None
        if index + 1 < len(lines):
            next_body = lines[index + 1].rstrip("\r\n")
            if _is_table_separator_line(next_body):
                split_at = _find_crammed_table_header_start(body)
        if split_at is None:
            repaired.append(line)
            continue

        prefix = body[:split_at].rstrip()
        header = body[split_at:].lstrip()
        if prefix:
            repaired.append(f"{prefix}\n")
        repaired.append(f"{header}{eol}")

    return "".join(repaired)


class _BorderedCodeBlock(CodeBlock):
    """Code block with an aligned rounded frame and calm report styling."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code_text = str(self.text).rstrip("\n")
        if self.lexer_name.strip().lower() in {"", "text", "plain", "markdown"}:
            matrix_rows = _priority_matrix_rows(code_text)
            if matrix_rows is not None:
                yield blank_row()
                yield _render_priority_matrix(matrix_rows)
                yield blank_row()
                return

        colors = get_markdown_colors()
        border_style = RichStyle(color=colors.code_block_border, bold=True)
        panel_style = (
            RichStyle(bgcolor=colors.code_block_bg) if colors.code_block_bg else RichStyle()
        )

        syntax = Syntax(
            code_text,
            self.lexer_name,
            theme=self.theme,
            word_wrap=True,
            padding=0,
            background_color=None,
        )
        highlighted = syntax.highlight(code_text)
        highlighted.rstrip()
        lexer_name = self.lexer_name.strip()
        title = lexer_name if lexer_name and lexer_name != "text" else None
        # Frame the code block with a blank row above and below so it reads as a
        # distinct section instead of crowding the surrounding prose. Canonical
        # ``blank_row()`` (an empty ``Text``) never picks up the panel's tint.
        yield blank_row()
        yield Panel(
            highlighted,
            title=title,
            title_align="left",
            box=box.ROUNDED,
            border_style=border_style,
            padding=CODE_BLOCK_PADDING,
            expand=True,
            style=panel_style,
        )
        yield blank_row()


def _markdown_style_overrides(theme: ThemeName | None = None) -> dict[str, RichStyle]:
    """Translate the active markdown palette into Rich style names."""
    colors = get_markdown_colors(theme)
    return {
        "markdown.h1": RichStyle(color=colors.heading, bold=True),
        "markdown.h1.border": RichStyle(color=colors.heading),
        "markdown.h1.underline": RichStyle(color=colors.heading),
        "markdown.h2": RichStyle(color=colors.heading, bold=True, underline=True),
        "markdown.h3": RichStyle(color=colors.heading, bold=True),
        "markdown.h4": RichStyle(color=colors.heading, bold=True, dim=True),
        "markdown.strong": RichStyle(color=colors.strong, bold=True),
        "markdown.em": RichStyle(color=colors.emphasis, italic=True),
        "markdown.emph": RichStyle(color=colors.emphasis, italic=True),
        "markdown.code": RichStyle(color=colors.inline_code, bold=True),
        "markdown.link": RichStyle(color=colors.link, underline=True),
        # The bracketed URL reads as secondary to the link text.
        "markdown.link_url": RichStyle(color=colors.link, underline=True, dim=True),
        "markdown.block_quote": RichStyle(color=colors.quote, italic=True),
        "markdown.hr": RichStyle(color=colors.code_block_border),
        "markdown.code_block": RichStyle(color=colors.inline_code),
        "markdown.code_block.border": RichStyle(color=colors.code_block_border, bold=True),
        # Bullets/numbers are structural, not "important words" — keep them muted
        # so the accent is reserved for headings and bold text.
        "markdown.item.bullet": RichStyle(color=colors.quote, bold=True),
        "markdown.item.number": RichStyle(color=colors.quote, bold=True),
    }


def _replace_report_icons(text: str) -> str:
    """Replace large/color emoji status icons with compact monochrome glyphs."""
    if not any(icon in text for icon in _MARKDOWN_ICON_KEYS):
        return text
    out: list[str] = []
    i = 0
    inline_code_ticks = 0
    while i < len(text):
        if text[i] == "`":
            j = i
            while j < len(text) and text[j] == "`":
                j += 1
            tick_count = j - i
            out.append(text[i:j])
            if inline_code_ticks == 0:
                inline_code_ticks = tick_count
            elif inline_code_ticks == tick_count:
                inline_code_ticks = 0
            i = j
            continue
        if inline_code_ticks:
            out.append(text[i])
            i += 1
            continue
        for icon in _MARKDOWN_ICON_KEYS:
            if text.startswith(icon, i):
                out.append(_MARKDOWN_ICON_REPLACEMENTS[icon])
                i += len(icon)
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _simplify_markdown_report_icons(markup: str) -> str:
    """Simplify report/status emoji outside fenced code blocks."""
    if not any(icon in markup for icon in _MARKDOWN_ICON_KEYS):
        return markup

    lines: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for line in markup.splitlines(keepends=True):
        match = _FENCE_RE.match(line)
        if in_fence:
            lines.append(line)
            if match is not None:
                fence = match.group("fence")
                if fence.startswith(fence_char) and len(fence) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            continue
        if match is not None:
            fence = match.group("fence")
            in_fence = True
            fence_char = fence[0]
            fence_len = len(fence)
            lines.append(line)
            continue
        lines.append(_replace_report_icons(line))
    return "".join(lines)


# Inline code spans: a run of N backticks, lazily-matched body, a closing run of
# exactly N backticks (GFM balanced-backtick rule, single-line scope — table rows).
_CODE_SPAN_RE = re.compile(r"(?P<ticks>`+)(?P<body>.*?)(?P=ticks)")


def _escape_code_span_pipes(text: str) -> str:
    r"""Escape raw ``|`` inside inline code spans as ``\|`` so GFM keeps the table
    cell intact (LLMs frequently emit unescaped pipes inside code spans). Only the
    code-span interior is touched; table-delimiter pipes outside spans are left
    alone, and an already-escaped ``\|`` is not double-escaped. Call only on
    table-row text (see :func:`_normalize_table_block`); applying it to prose
    inline-code would leave a literal backslash in the rendered span.
    """

    def _repl(match: re.Match[str]) -> str:
        ticks = match.group("ticks")
        body = re.sub(r"(?<!\\)\|", r"\\|", match.group("body"))
        return f"{ticks}{body}{ticks}"

    return _CODE_SPAN_RE.sub(_repl, text)


def _split_pipe_cells(segment: str) -> list[str]:
    """Split a ``| a | b |`` run into stripped inner cells (drops the frame)."""
    parts = re.split(r"(?<!\\)\|", segment)
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [part.strip() for part in parts]


def _is_pipe_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _delimiter_markers(run: str) -> list[str]:
    """Return per-column alignment markers (``---``, ``:---``, ``---:``, ``:---:``)."""
    markers: list[str] = []
    for cell in _split_pipe_cells(run):
        left = cell.startswith(":")
        right = cell.endswith(":")
        if left and right:
            markers.append(":---:")
        elif right:
            markers.append("---:")
        elif left:
            markers.append(":---")
        else:
            markers.append("---")
    return markers


def _normalize_table_block(text: str) -> str:
    """Repair malformed GFM tables in a fence-free block of markdown.

    Models occasionally glue a table header onto preceding prose, drop the
    newline between the header and the ``|---|`` delimiter, or cram data rows
    onto the delimiter line — markdown-it then renders the whole thing as raw
    text. Anchored on the delimiter run, this rebuilds each region it is
    *confident* is a table (delimiter at line start, header and data cell counts
    both equal to the delimiter's column count) and passes everything else
    through untouched. Well-formed tables are rebuilt to identical-rendering
    markdown, so the pass is safe to apply unconditionally.
    """
    out = ""
    while True:
        match = _DELIM_RUN_RE.search(text)
        if match is None:
            return out + text
        markers = _delimiter_markers(match.group(0))
        n_cols = len(markers)
        head = text[: match.start()]
        tail = text[match.end() :]

        # The delimiter must start its own line — guards against inline ``|-|``.
        # Any leading whitespace is the table's indentation (e.g. nested under a
        # list item); preserve it when re-emitting so we never promote an
        # indented table to top level.
        indent = head[head.rfind("\n") + 1 :]
        if n_cols < 2 or indent.strip() != "":
            out += text[: match.end()]
            text = tail
            continue

        head_lines = head.split("\n")
        while head_lines and head_lines[-1] == "":
            head_lines.pop()
        header_match = _HEADER_RE.match(head_lines[-1]) if head_lines else None
        header_cells = (
            _split_pipe_cells(_escape_code_span_pipes(header_match.group("cells")))
            if header_match
            else []
        )
        if header_match is None or len(header_cells) != n_cols:
            out += text[: match.end()]
            text = tail
            continue

        # Data rows: the same-line remainder after the delimiter plus any
        # following pipe rows, re-chunked into rows of ``n_cols`` cells.
        tail_lines = tail.split("\n")
        data_segments = [tail_lines[0]] if tail_lines[0].strip() else []
        consumed = 1
        for line in tail_lines[1:]:
            if _is_pipe_row(line):
                data_segments.append(line)
                consumed += 1
            else:
                break
        data_rows: list[list[str]] = []
        bail = False
        for segment in data_segments:
            cells = _split_pipe_cells(_escape_code_span_pipes(segment))
            if not cells:
                continue
            if len(cells) % n_cols != 0:
                bail = True  # ambiguous (e.g. glued rows with empty cells) — leave as-is
                break
            for i in range(0, len(cells), n_cols):
                data_rows.append(cells[i : i + n_cols])
        if bail:
            out += text[: match.end()]
            text = tail
            continue

        preamble = head_lines[:-1]
        prose = header_match.group("prefix").rstrip()
        if preamble:
            out += "\n".join(preamble) + "\n"
        if prose:
            out += prose + "\n"
        # A GFM table must be preceded by a blank line (it cannot interrupt a
        # paragraph), so ensure one before emitting the header.
        if out and not out.endswith("\n\n"):
            out += "\n" if out.endswith("\n") else "\n\n"
        out += f"{indent}| " + " | ".join(header_cells) + " |\n"
        out += f"{indent}| " + " | ".join(markers) + " |\n"
        for row in data_rows:
            out += f"{indent}| " + " | ".join(row) + " |\n"

        remainder = "\n".join(tail_lines[consumed:])
        if not remainder.strip():
            return out
        text = remainder if remainder.startswith("\n") else "\n" + remainder


def _normalize_markdown_tables(markup: str) -> str:
    """Apply :func:`_normalize_table_block` to every fence-free span of markup."""
    if "|" not in markup or "-" not in markup:
        return markup

    out: list[str] = []
    buffer: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    def flush() -> None:
        if buffer:
            out.append(_normalize_table_block("\n".join(buffer)))
            buffer.clear()

    for line in markup.splitlines():
        match = _FENCE_RE.match(line)
        if in_fence:
            fence = match.group("fence") if match else ""
            if fence and fence[0] == fence_char and len(fence) >= fence_len:
                in_fence = False
            out.append(line)
            continue
        if match:
            flush()
            in_fence = True
            fence_char = match.group("fence")[0]
            fence_len = len(match.group("fence"))
            out.append(line)
            continue
        buffer.append(line)
    flush()

    result = "\n".join(out)
    if markup.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


class PythinkerMarkdown(Markdown):
    """Drop-in replacement for ``rich.markdown.Markdown`` with the Pythinker palette.

    Markup is run through :func:`sanitize_ansi` first so terminal control
    sequences embedded in model/user/custom text cannot reach the terminal
    (cursor moves, color leaks) when rendered as Markdown. Large emoji status
    icons are then normalized to compact monochrome glyphs for calmer reports.
    """

    elements = {**Markdown.elements, "fence": _BorderedCodeBlock, "code_block": _BorderedCodeBlock}

    def __init__(self, markup: str, *args: Any, **kwargs: Any) -> None:
        safe_markup = sanitize_ansi(markup)
        repaired_markup = _repair_crammed_markdown_tables(safe_markup)
        normalized_markup = _normalize_markdown_tables(repaired_markup)
        super().__init__(_simplify_markdown_report_icons(normalized_markup), *args, **kwargs)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        overrides = _markdown_style_overrides()
        with console.use_theme(Theme(overrides, inherit=True)):
            yield from super().__rich_console__(console, options)


def pythinker_markdown(
    text: str, *, code_theme: str = PYTHINKER_ANSI_THEME_NAME
) -> PythinkerMarkdown:
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
