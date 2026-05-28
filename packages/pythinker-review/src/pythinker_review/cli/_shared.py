"""Shared CLI types: output format, threshold, and exit-code computation."""

from __future__ import annotations

from enum import StrEnum

from pythinker_review.store.models import SEVERITY_ORDER, Finding, RunMeta, Severity


class OutputFormat(StrEnum):
    pretty = "pretty"
    json = "json"
    sarif = "sarif"


class FailOn(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    none = "none"


_FAIL_TO_SEV: dict[FailOn, Severity | None] = {
    FailOn.critical: Severity.critical,
    FailOn.high: Severity.high,
    FailOn.medium: Severity.medium,
    FailOn.low: Severity.low,
    FailOn.none: None,
}


def exit_code(*, meta: RunMeta, findings: list[Finding], fail_on: FailOn, llm_error: bool) -> int:
    if llm_error:
        return 3
    if meta.status == "failed":
        return 4
    if meta.status == "cancelled":
        return 130
    threshold = _FAIL_TO_SEV[fail_on]
    if threshold is not None and any(
        SEVERITY_ORDER[finding.severity] >= SEVERITY_ORDER[threshold] for finding in findings
    ):
        return 1
    return 0
