"""Pythinker diff component.


plus the diff-string generator from ``edit-diff.ts``.

Two entry points:

* :func:`compute_edit_diff_string` — given ``old_text`` / ``new_text``,
  produce Pythinker's per-line diff format (``+123 content``, ``-123 content``,
  `` 123 content``, with `` ... `` skip markers).
* :func:`render_diff` — colorize a Pythinker-format diff string into a Rich
  ``Text`` (red removed, green added, dim context, with intra-line word
  highlighting on single-line edits).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from rich.style import Style as RichStyle
from rich.text import Text

from pythinker_code.ui.theme import get_diff_colors, tui_rich_style

__all__ = [
    "EditDiffResult",
    "compute_edit_diff_string",
    "render_diff",
]

_DEFAULT_CONTEXT_LINES = 3
_TAB_REPLACEMENT = "   "
_DIFF_LINE_RE = re.compile(r"^([+\-\s])(\s*\d*)\s(.*)$")


@dataclass(frozen=True, slots=True)
class EditDiffResult:
    """Output of :func:`compute_edit_diff_string`."""

    diff: str
    first_changed_line: int | None


def _replace_tabs(text: str) -> str:
    return text.replace("\t", _TAB_REPLACEMENT)


def compute_edit_diff_string(
    old_text: str,
    new_text: str,
    *,
    context_lines: int = _DEFAULT_CONTEXT_LINES,
    old_start: int = 1,
    new_start: int = 1,
) -> EditDiffResult:
    """Build Pythinker's custom diff format from ``old_text``/``new_text``.

    Format per line:

    * ``+<n> <content>`` — added line at new file line ``n``
    * ``-<n> <content>`` — removed line at old file line ``n``
    * `` <n> <content>`` — context line
    * `` <pad> ...``   — collapsed-context marker

    ``old_start`` / ``new_start`` let callers render bounded diff hunks with
    the real source-file line numbers, matching the structured diff display in
    the reference UI. Defaults preserve the old tool-input-only behavior.

    Returns ``("", None)`` when the texts are identical.
    """
    if old_text == new_text:
        return EditDiffResult(diff="", first_changed_line=None)

    old_lines = old_text.split("\n")
    new_lines = new_text.split("\n")
    last_old = old_start + max(0, len(old_lines) - 1)
    last_new = new_start + max(0, len(new_lines) - 1)
    line_num_width = max(2, len(str(max(last_old, last_new))))

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    output: list[str] = []
    old_lineno = old_start
    new_lineno = new_start
    first_changed: int | None = None
    last_was_change = False
    opcodes = matcher.get_opcodes()

    def _pad(n: int) -> str:
        return str(n).rjust(line_num_width)

    def _blank_pad() -> str:
        return " " * line_num_width

    for idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag in ("replace", "delete", "insert"):
            if first_changed is None:
                first_changed = new_lineno
            for line in old_lines[i1:i2] if tag != "insert" else []:
                output.append(f"-{_pad(old_lineno)} {line}")
                old_lineno += 1
            for line in new_lines[j1:j2] if tag != "delete" else []:
                output.append(f"+{_pad(new_lineno)} {line}")
                new_lineno += 1
            last_was_change = True
            continue

        # tag == "equal" — context block.
        block = old_lines[i1:i2]
        next_change = idx < len(opcodes) - 1 and opcodes[idx + 1][0] != "equal"
        leading = last_was_change
        trailing = next_change

        if leading and trailing:
            if len(block) <= context_lines * 2:
                for line in block:
                    output.append(f" {_pad(old_lineno)} {line}")
                    old_lineno += 1
                    new_lineno += 1
            else:
                head = block[:context_lines]
                tail = block[-context_lines:]
                skipped = len(block) - len(head) - len(tail)
                for line in head:
                    output.append(f" {_pad(old_lineno)} {line}")
                    old_lineno += 1
                    new_lineno += 1
                output.append(f" {_blank_pad()} ...")
                old_lineno += skipped
                new_lineno += skipped
                for line in tail:
                    output.append(f" {_pad(old_lineno)} {line}")
                    old_lineno += 1
                    new_lineno += 1
        elif leading:
            shown = block[:context_lines]
            skipped = len(block) - len(shown)
            for line in shown:
                output.append(f" {_pad(old_lineno)} {line}")
                old_lineno += 1
                new_lineno += 1
            if skipped > 0:
                output.append(f" {_blank_pad()} ...")
                old_lineno += skipped
                new_lineno += skipped
        elif trailing:
            skipped = max(0, len(block) - context_lines)
            if skipped > 0:
                output.append(f" {_blank_pad()} ...")
                old_lineno += skipped
                new_lineno += skipped
            for line in block[skipped:]:
                output.append(f" {_pad(old_lineno)} {line}")
                old_lineno += 1
                new_lineno += 1
        else:
            old_lineno += len(block)
            new_lineno += len(block)

        last_was_change = False

    return EditDiffResult(diff="\n".join(output), first_changed_line=first_changed)


def _parse_diff_line(line: str) -> tuple[str, str, str] | None:
    match = _DIFF_LINE_RE.match(line)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def _intra_line_diff(old_content: str, new_content: str) -> tuple[Text, Text]:
    """Word-level inverse highlighting on changed tokens (the same behavior).

    Returns ``(removed_text, added_text)`` already styled (with the inverse
    bit set on tokens that differ), but *not* yet wrapped in red/green —
    callers add the row-level style.
    """
    inverse = RichStyle(reverse=True)

    def _tokenize(s: str) -> list[str]:
        return re.findall(r"\s+|\S+", s)

    old_tokens = _tokenize(old_content)
    new_tokens = _tokenize(new_content)
    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    removed = Text()
    added = Text()
    first_removed = True
    first_added = True
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            piece = "".join(old_tokens[i1:i2])
            removed.append(piece)
            added.append(piece)
            if piece.strip():
                first_removed = False
                first_added = False
            continue
        # delete / insert / replace
        if tag in ("delete", "replace"):
            piece = "".join(old_tokens[i1:i2])
            if first_removed:
                stripped = piece.lstrip()
                leading = piece[: len(piece) - len(stripped)]
                if leading:
                    removed.append(leading)
                if stripped:
                    removed.append(stripped, style=inverse)
                if stripped:
                    first_removed = False
            else:
                removed.append(piece, style=inverse)
        if tag in ("insert", "replace"):
            piece = "".join(new_tokens[j1:j2])
            if first_added:
                stripped = piece.lstrip()
                leading = piece[: len(piece) - len(stripped)]
                if leading:
                    added.append(leading)
                if stripped:
                    added.append(stripped, style=inverse)
                if stripped:
                    first_added = False
            else:
                added.append(piece, style=inverse)
    return removed, added


def render_diff(diff_text: str) -> Text:
    """Colorize a Pythinker-format diff string.

    ``diff_text`` is whatever :func:`compute_edit_diff_string` produced (or
    any string in the same format). Lines that don't match the prefix
    pattern are rendered as dim context.
    """
    if not diff_text:
        return Text("")

    colors = get_diff_colors()
    added_style = tui_rich_style("tool_diff_added") + colors.add_bg
    removed_style = tui_rich_style("tool_diff_removed") + colors.del_bg
    context_style = tui_rich_style("tool_diff_context")

    out = Text()
    lines = diff_text.split("\n")
    i = 0
    first = True

    def _newline() -> None:
        nonlocal first
        if not first:
            out.append("\n")
        first = False

    while i < len(lines):
        line = lines[i]
        parsed = _parse_diff_line(line)
        if parsed is None:
            _newline()
            out.append(line, style=context_style)
            i += 1
            continue
        prefix, line_num, content = parsed

        if prefix == "-":
            removed_block: list[tuple[str, str]] = []
            while i < len(lines):
                p = _parse_diff_line(lines[i])
                if p is None or p[0] != "-":
                    break
                removed_block.append((p[1], p[2]))
                i += 1
            added_block: list[tuple[str, str]] = []
            while i < len(lines):
                p = _parse_diff_line(lines[i])
                if p is None or p[0] != "+":
                    break
                added_block.append((p[1], p[2]))
                i += 1

            if len(removed_block) == 1 and len(added_block) == 1:
                rln, rcontent = removed_block[0]
                aln, acontent = added_block[0]
                rem_inner, add_inner = _intra_line_diff(
                    _replace_tabs(rcontent),
                    _replace_tabs(acontent),
                )
                _newline()
                row = Text(f"-{rln} ", style=removed_style)
                row.append_text(rem_inner)
                row.stylize(removed_style)
                out.append_text(row)
                _newline()
                row = Text(f"+{aln} ", style=added_style)
                row.append_text(add_inner)
                row.stylize(added_style)
                out.append_text(row)
            else:
                for ln, content in removed_block:
                    _newline()
                    out.append(f"-{ln} {_replace_tabs(content)}", style=removed_style)
                for ln, content in added_block:
                    _newline()
                    out.append(f"+{ln} {_replace_tabs(content)}", style=added_style)
        elif prefix == "+":
            _newline()
            out.append(f"+{line_num} {_replace_tabs(content)}", style=added_style)
            i += 1
        else:
            _newline()
            out.append(f" {line_num} {_replace_tabs(content)}", style=context_style)
            i += 1

    return out
