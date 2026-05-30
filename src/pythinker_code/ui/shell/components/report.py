"""Standardized report renderer.

One structured shape and one muted, roomy rendering for every report Pythinker
produces (code review, verify, security review, …). Reports reach the shell two
ways:

* Python callers build a :class:`Report` and call :func:`render_report`.
* Skills/agents emit a ```` ```report ```` fenced block of JSON; the shell
  splits it out of the surrounding markdown via :func:`render_agent_body` and
  renders it through the same path. A malformed block is never swallowed — it
  falls back to ordinary markdown (shown as a code block).

Styling reuses the existing theme tokens (:func:`tui_rich_style`), so the
"clear, not bright" palette and dark/light support come for free.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

if TYPE_CHECKING:
    from markdown_it import MarkdownIt

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.rule import Rule
from rich.style import Style as RichStyle
from rich.text import Text

from pythinker_code.ui.shell.components.markdown import pythinker_markdown
from pythinker_code.ui.theme import ThemeName, tui_rich_style

_log = logging.getLogger(__name__)

__all__ = [
    "Report",
    "ReportFinding",
    "Severity",
    "has_report_block",
    "parse_report_block",
    "render_agent_body",
    "render_report",
]

Severity = Literal["critical", "high", "medium", "low", "info"]

# Most-severe first — drives both grouping order and the summary tally.
_SEVERITY_ORDER: tuple[Severity, ...] = get_args(Severity)
_SEVERITY_SET = frozenset(_SEVERITY_ORDER)

# severity -> (token name, bold). Muted theme tokens only; critical is the one
# emphasis (bold) so the eye lands on it without a brighter colour.
_SEVERITY_TOKEN: dict[Severity, tuple[str, bool]] = {
    "critical": ("error", True),
    "high": ("error", False),
    "medium": ("warning", False),
    "low": ("accent", False),
    "info": ("muted", False),
}

_DOT = "●"


# A markdown-it parser is reused so report-fence extraction is fence-aware: a
# ```report block nested inside an outer fence is part of that outer fence's
# content and is therefore NOT a top-level fence token (Principle #5: parse,
# don't pattern-match).
_md_parser: MarkdownIt | None = None


def _get_report_parser() -> MarkdownIt:
    global _md_parser
    if _md_parser is None:
        from markdown_it import MarkdownIt

        _md_parser = MarkdownIt()
    return _md_parser


def _iter_report_payloads(text: str) -> list[tuple[int, int, str]]:
    """Yield (start_line, end_line, payload) for each TOP-LEVEL ```report fence.

    Line indices are 0-based half-open ([start, end)) into ``text``'s lines,
    matching markdown-it ``token.map``. Nested fences never appear as top-level
    ``fence`` tokens, so they are structurally excluded.
    """
    md = _get_report_parser()
    blocks: list[tuple[int, int, str]] = []
    for token in md.parse(text):
        if (
            token.type == "fence"
            and token.level == 0
            and token.map is not None
            and token.info.strip() == "report"
        ):
            blocks.append((token.map[0], token.map[1], token.content))
    return blocks


@dataclass(frozen=True, slots=True)
class ReportFinding:
    """One finding in a report."""

    title: str
    severity: Severity
    location: str | None = None  # e.g. "src/foo.py:42-58"
    body: str = ""  # markdown prose


@dataclass(frozen=True, slots=True)
class Report:
    """A standardized report. The summary tally is derived, never supplied."""

    title: str
    scope: str | None = None
    findings: tuple[ReportFinding, ...] = ()
    note: str | None = None  # closing "most actionable" line


def _counts(findings: tuple[ReportFinding, ...]) -> dict[Severity, int]:
    counts: dict[Severity, int] = dict.fromkeys(_SEVERITY_ORDER, 0)
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def _severity_style(severity: Severity, theme: ThemeName | None) -> RichStyle:
    token, bold = _SEVERITY_TOKEN[severity]
    style = tui_rich_style(token, theme=theme)
    return style + RichStyle(bold=True) if bold else style


def _summary_line(counts: dict[Severity, int], theme: ThemeName | None) -> Text:
    line = Text()
    first = True
    for severity in _SEVERITY_ORDER:
        count = counts[severity]
        if not count:
            continue
        if not first:
            line.append("   ")
        first = False
        line.append(f"{_DOT} ", style=_severity_style(severity, theme))
        line.append(f"{count} {severity}", style=tui_rich_style("text", theme=theme))
    if not counts["critical"] and not counts["high"]:
        prefix = "   " if not first else ""
        line.append(f"{prefix}no critical or high", style=tui_rich_style("muted", theme=theme))
    return line


def _render_finding(finding: ReportFinding, theme: ThemeName | None) -> RenderableType:
    rows: list[RenderableType] = []

    title = Text()
    title.append(f"{_DOT} ", style=_severity_style(finding.severity, theme))
    title.append(finding.title, style=tui_rich_style("text", theme=theme) + RichStyle(bold=True))
    rows.append(title)

    if finding.location:
        rows.append(Text(f"  {finding.location}", style=tui_rich_style("dim", theme=theme)))

    if finding.body.strip():
        rows.append(Padding(pythinker_markdown(finding.body.strip()), (0, 0, 0, 2)))

    return Group(*rows)


def render_report(report: Report, *, theme: ThemeName | None = None) -> RenderableType:
    """Render *report* as a muted, roomy Rich renderable (no outer box)."""
    counts = _counts(report.findings)
    border = tui_rich_style("border_muted", theme=theme)
    blank = Text("")

    rows: list[RenderableType] = [
        Text(report.title, style=tui_rich_style("text", theme=theme) + RichStyle(bold=True)),
    ]
    if report.scope:
        rows += [blank, Text(report.scope, style=tui_rich_style("dim", theme=theme))]
    rows += [blank, _summary_line(counts, theme)]

    for severity in _SEVERITY_ORDER:
        group = [f for f in report.findings if f.severity == severity]
        if not group:
            continue
        rows.append(blank)
        rows.append(Rule(f" {severity.capitalize()} ", align="left", style=border, characters="─"))
        for finding in group:
            rows.append(blank)
            rows.append(_render_finding(finding, theme))

    if report.note:
        rows += [
            blank,
            Rule(style=border, characters="─"),
            Text(report.note, style=tui_rich_style("muted", theme=theme)),
        ]

    # One column of left breathing room; vertical roominess comes from the
    # blank rows between sections and findings.
    return Padding(Group(*rows), (0, 0, 0, 1))


def parse_report_block(payload: str) -> Report | None:
    """Deserialize a ```` ```report ```` block's JSON into a :class:`Report`.

    Returns ``None`` on any malformed payload so callers can fall back to
    rendering the raw text — a bad block must never be swallowed.
    """
    try:
        parsed = json.loads(payload)
    except (ValueError, TypeError) as exc:
        _log.debug(
            "parse_report_block: JSON decode failed (type=%s len=%d)",
            type(payload).__name__,
            len(payload),
            exc_info=exc,
        )
        return None
    if not isinstance(parsed, dict):
        return None
    data = cast(dict[str, Any], parsed)

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    scope = data.get("scope")
    scope = scope if isinstance(scope, str) and scope.strip() else None
    note = data.get("note")
    note = note if isinstance(note, str) and note.strip() else None

    raw_findings = data.get("findings")
    if raw_findings is not None and not isinstance(raw_findings, list):
        return None

    findings: list[ReportFinding] = []
    for raw in cast("list[Any]", raw_findings or []):
        if not isinstance(raw, dict):
            return None
        entry = cast(dict[str, Any], raw)
        f_title = entry.get("title")
        severity = entry.get("severity")
        if not isinstance(f_title, str) or not f_title.strip():
            return None
        if severity not in _SEVERITY_SET:
            return None
        location = entry.get("location")
        location = location if isinstance(location, str) and location.strip() else None
        body = entry.get("body")
        body = body if isinstance(body, str) else ""
        findings.append(
            ReportFinding(title=f_title, severity=severity, location=location, body=body)
        )

    return Report(title=title, scope=scope, findings=tuple(findings), note=note)


def has_report_block(text: str) -> bool:
    """Whether *text* contains at least one well-formed top-level ` ```report ` block.

    Used by output surfaces (e.g. the headless final-text printer) to decide
    whether to route through :func:`render_agent_body` instead of emitting the
    raw text. Only matches blocks that actually parse, so a malformed fence
    leaves output unchanged. A ` ```report ` example nested inside an outer
    documentation fence is not a top-level fence token, so it is not matched.
    """
    return any(
        parse_report_block(payload) is not None for _, _, payload in _iter_report_payloads(text)
    )


def render_agent_body(text: str, *, theme: ThemeName | None = None) -> RenderableType:
    """Render assistant text, promoting top-level ` ```report ` blocks to reports.

    Non-report text renders via :func:`pythinker_markdown`; a valid top-level
    report block renders via :func:`render_report`; an invalid or nested block is
    left in place so the surrounding markdown shows it as an ordinary code block.
    """
    # Split on "\n" only (NOT str.splitlines, which also breaks on \f, \v, \x85,
    #  ,  ): markdown-it's token.map counts only "\n", so any other
    # split character would shift our line indices out of sync with the parser
    # and leak fence delimiters into the surrounding prose.
    lines = text.split("\n")
    segments: list[RenderableType] = []
    cursor = 0  # line index
    for start, end, payload in _iter_report_payloads(text):
        report = parse_report_block(payload)
        if report is None:
            continue  # malformed — leave it for the markdown renderer
        before = "\n".join(lines[cursor:start]).strip("\n")
        if before:
            segments.append(pythinker_markdown(before))
        segments.append(render_report(report, theme=theme))
        cursor = end

    if not segments:
        return pythinker_markdown(text)

    rest = "\n".join(lines[cursor:]).strip("\n")
    if rest:
        segments.append(pythinker_markdown(rest))

    spaced: list[RenderableType] = []
    for i, segment in enumerate(segments):
        if i:
            spaced.append(Text(""))
        spaced.append(segment)
    return Group(*spaced)
