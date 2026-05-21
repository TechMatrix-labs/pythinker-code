"""Pydantic domain models for Python-native Pythinker Security Scan.

The shapes use Python-first validation with snake_case-friendly aliases while preserving the
repo-wide scanner's JSON data layout.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "HIGH_BUG", "BUG", "LOW"]
Confidence = Literal["high", "medium", "low"]
RevalidationVerdict = Literal[
    "true-positive", "false-positive", "fixed", "uncertain", "accepted-risk"
]
TriagePriority = Literal["P0", "P1", "P2", "skip"]
FileStatus = Literal["pending", "processing", "analyzed", "error"]
RunType = Literal["scan", "process", "revalidate", "triage"]
RunPhase = Literal["running", "done", "error"]
NoiseTier = Literal["precise", "normal", "noisy"]


class SecurityScanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CandidateMatch(SecurityScanModel):
    vuln_slug: str = Field(alias="vulnSlug")
    line_numbers: list[int] = Field(alias="lineNumbers")
    snippet: str
    matched_pattern: str = Field(alias="matchedPattern")

    @field_validator("line_numbers")
    @classmethod
    def _line_numbers_are_positive(cls, value: list[int]) -> list[int]:
        if any(line < 1 for line in value):
            raise ValueError("line numbers must be positive")
        return value


class Triage(SecurityScanModel):
    priority: TriagePriority
    exploitability: Literal["trivial", "moderate", "difficult"]
    impact: Literal["critical", "high", "medium", "low"]
    reasoning: str
    triaged_at: str = Field(alias="triagedAt")
    model: str


class Revalidation(SecurityScanModel):
    verdict: RevalidationVerdict
    reasoning: str
    adjusted_severity: Severity | None = Field(default=None, alias="adjustedSeverity")
    revalidated_at: str = Field(alias="revalidatedAt")
    run_id: str = Field(alias="runId")
    model: str


class Finding(SecurityScanModel):
    severity: Severity
    vuln_slug: str = Field(alias="vulnSlug")
    title: str
    description: str
    line_numbers: list[int] = Field(alias="lineNumbers")
    recommendation: str
    confidence: Confidence
    triage: Triage | None = None
    revalidation: Revalidation | None = None
    produced_by_run_id: str | None = Field(default=None, alias="producedByRunId")

    @field_validator("line_numbers")
    @classmethod
    def _finding_lines_are_positive(cls, value: list[int]) -> list[int]:
        if any(line < 1 for line in value):
            raise ValueError("line numbers must be positive")
        return value


class RefusalSkipped(SecurityScanModel):
    file_path: str | None = Field(default=None, alias="filePath")
    reason: str


class RefusalReport(SecurityScanModel):
    refused: bool
    reason: str | None = None
    skipped: list[RefusalSkipped] = Field(default_factory=list)
    raw: str | None = None


class AnalysisUsage(SecurityScanModel):
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    cache_read_input_tokens: int = Field(default=0, alias="cacheReadInputTokens")
    cache_creation_input_tokens: int = Field(default=0, alias="cacheCreationInputTokens")


class AnalysisEntry(SecurityScanModel):
    run_id: str = Field(alias="runId")
    investigated_at: str = Field(alias="investigatedAt")
    duration_ms: int = Field(alias="durationMs")
    duration_api_ms: int | None = Field(default=None, alias="durationApiMs")
    agent_type: str = Field(alias="agentType")
    model: str
    model_configuration: dict[str, Any] = Field(alias="modelConfig")
    agent_session_id: str | None = Field(default=None, alias="agentSessionId")
    finding_count: int = Field(alias="findingCount")
    num_turns: int | None = Field(default=None, alias="numTurns")
    phase: Literal["process", "revalidate"] | None = None
    cost_usd: float | None = Field(default=None, alias="costUsd")
    usage: AnalysisUsage | None = None
    refusal: RefusalReport | None = None
    reinvestigate_marker: int | None = Field(default=None, alias="reinvestigateMarker")


class RecentCommitter(SecurityScanModel):
    name: str
    email: str
    date: str


class GitInfo(SecurityScanModel):
    recent_committers: list[RecentCommitter] = Field(default_factory=list, alias="recentCommitters")
    enriched_at: str = Field(alias="enrichedAt")
    ownership: dict[str, Any] | None = None


class FileRecord(SecurityScanModel):
    file_path: str = Field(alias="filePath")
    project_id: str = Field(alias="projectId")
    candidates: list[CandidateMatch] = Field(default_factory=list)
    last_scanned_at: str = Field(default="", alias="lastScannedAt")
    last_scanned_run_id: str = Field(default="", alias="lastScannedRunId")
    file_hash: str = Field(default="", alias="fileHash")
    findings: list[Finding] = Field(default_factory=list)
    analysis_history: list[AnalysisEntry] = Field(default_factory=list, alias="analysisHistory")
    git_info: GitInfo | None = Field(default=None, alias="gitInfo")
    status: FileStatus = "pending"
    locked_by_run_id: str | None = Field(default=None, alias="lockedByRunId")
    locked_at: str | None = Field(default=None, alias="lockedAt")

    @model_validator(mode="after")
    def _status_lock_consistency(self) -> FileRecord:
        if self.status != "processing" and self.locked_by_run_id is not None:
            raise ValueError("lockedByRunId is only valid while status is processing")
        return self


class ProjectConfig(SecurityScanModel):
    project_id: str = Field(alias="projectId")
    root_path: str = Field(alias="rootPath")
    created_at: str = Field(alias="createdAt")
    github_url: str | None = Field(default=None, alias="githubUrl")


class RunStats(SecurityScanModel):
    files_scanned: int | None = Field(default=None, alias="filesScanned")
    candidates_found: int | None = Field(default=None, alias="candidatesFound")
    files_processed: int | None = Field(default=None, alias="filesProcessed")
    findings_count: int | None = Field(default=None, alias="findingsCount")
    findings_revalidated: int | None = Field(default=None, alias="findingsRevalidated")
    true_positives: int | None = Field(default=None, alias="truePositives")
    false_positives: int | None = Field(default=None, alias="falsePositives")
    fixed: int | None = None
    uncertain: int | None = None


class ScannerConfig(SecurityScanModel):
    matcher_slugs: list[str] = Field(default_factory=list, alias="matcherSlugs")
    mode: Literal["full", "files"] | None = None
    source: str | None = None
    file_count: int | None = Field(default=None, alias="fileCount")


class ProcessorConfig(SecurityScanModel):
    agent_type: str = Field(alias="agentType")
    model: str
    model_configuration: dict[str, Any] = Field(default_factory=dict, alias="modelConfig")
    invocation_mode: Literal["scan", "direct"] | None = Field(default=None, alias="invocationMode")
    source: str | None = None


class RunMeta(SecurityScanModel):
    run_id: str = Field(alias="runId")
    project_id: str = Field(alias="projectId")
    root_path: str = Field(alias="rootPath")
    created_at: str = Field(alias="createdAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    type: RunType
    phase: RunPhase
    pid: int | None = None
    hostname: str | None = None
    scanner_config: ScannerConfig | None = Field(default=None, alias="scannerConfig")
    processor_config: ProcessorConfig | None = Field(default=None, alias="processorConfig")
    stats: RunStats = Field(default_factory=RunStats)


class DetectedTech(SecurityScanModel):
    tags: list[str]
    languages: list[str] = Field(default_factory=list)
    sentinels: list[str]
    detected_at: str = Field(alias="detectedAt")
    root_path: str = Field(alias="rootPath")


class SecurityScanProjectSettings(SecurityScanModel):
    priority_paths: list[str] = Field(default_factory=list, alias="priorityPaths")
    prompt_append: str | None = Field(default=None, alias="promptAppend")
    ignore_paths: list[str] = Field(default_factory=list, alias="ignorePaths")


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
