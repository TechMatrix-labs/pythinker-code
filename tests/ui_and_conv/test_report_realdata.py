# tests/ui_and_conv/test_report_realdata.py
"""Report rendering grounded in the real security-scan-findings.json fixture.

The fixture is RAW scanner shape (filePath / severity UPPERCASE / vulnSlug /
title / description / lineNumbers / recommendation / confidence). report.py
consumes the Report shape (title / severity lowercase / location / body). The
transform below encodes the contract: case-fold severity, fold the scanner's
extended severities (HIGH_BUG, BUG) into the canonical five via _SEVERITY_ALIASES,
fold filePath + lineNumbers into location, fold description + recommendation into
body.

No in-repo production transform exists: the external scanner emits canonical
``report`` JSON directly and report.parse_report_block rejects any non-canonical
severity, so this adapter is the documented contract (see the design spec R2 and
Task 12).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pythinker_code.ui.shell.components.report import (
    Report,
    ReportFinding,
    Severity,
    render_report,
)
from tests.ui_and_conv._md_contract_helpers import THEMES, WIDTHS, render_plain

_FIXTURE = Path(__file__).resolve().parents[2] / "security-scan-findings.json"
_VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
# Scanner-native severities outside the canonical five, folded to a canonical
# value. The scanner's compound "*_BUG" / bare "BUG" tags are bug-tracker
# qualifiers, not Report severities.
_SEVERITY_ALIASES = {"high_bug": "high", "bug": "medium"}


def _location(raw: dict) -> str | None:
    path = raw.get("filePath")
    if not isinstance(path, str) or not path:
        return None
    lines = raw.get("lineNumbers") or []
    if isinstance(lines, list) and lines:
        return f"{path}:{lines[0]}"
    return path


def _body(raw: dict) -> str:
    parts = []
    if raw.get("description"):
        parts.append(str(raw["description"]))
    if raw.get("recommendation"):
        parts.append(f"**Fix:** {raw['recommendation']}")
    return "\n\n".join(parts)


def _to_finding(raw: dict) -> ReportFinding:
    raw_severity = str(raw["severity"]).lower()
    severity = _SEVERITY_ALIASES.get(raw_severity, raw_severity)
    assert severity in _VALID_SEVERITIES, f"unexpected severity {raw['severity']!r}"
    return ReportFinding(
        title=str(raw["title"]),
        severity=severity,  # type: ignore[arg-type]
        location=_location(raw),
        body=_body(raw),
    )


def _load_report(limit: int | None = None) -> Report:
    raw = json.loads(_FIXTURE.read_text())
    findings = tuple(_to_finding(r) for r in (raw[:limit] if limit else raw))
    return Report(title="Security Scan", scope=f"{len(findings)} findings", findings=findings)


def test_fixture_transforms_to_valid_report():
    report = _load_report()
    assert len(report.findings) == 92
    # Every transformed severity is a valid Report severity.
    seen: set[Severity] = {f.severity for f in report.findings}
    assert seen <= _VALID_SEVERITIES
    assert "critical" in seen  # the fixture contains CRITICAL findings


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
def test_real_report_renders_across_theme_and_width(theme, width):
    out = render_plain(render_report(_load_report(limit=12), theme=theme), width=width)
    assert "Security Scan" in out
    # The summary tally line names at least one present severity.
    assert any(sev in out for sev in ("critical", "high", "medium", "low", "info"))


def test_real_report_shows_locations_and_titles():
    out = render_plain(render_report(_load_report(limit=5)), width=100)
    report = _load_report(limit=5)
    for finding in report.findings:
        assert finding.title[:20] in out
        if finding.location:
            # the file path portion of the first finding's location appears
            assert finding.location.split(":")[0].split("/")[-1] in out
