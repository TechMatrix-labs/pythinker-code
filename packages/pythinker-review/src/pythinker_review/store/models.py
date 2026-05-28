"""Pydantic models for findings, runs, and chunk failures."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.critical: 4,
    Severity.high: 3,
    Severity.medium: 2,
    Severity.low: 1,
    Severity.info: 0,
}


class Category(StrEnum):
    correctness = "correctness"
    security = "security"
    debugging = "debugging"
    performance = "performance"
    readability = "readability"
    test_coverage = "test_coverage"
    api_design = "api_design"
    dependency = "dependency"
    secret = "secret"


Pass = Literal["code_review", "security_review", "debug_review", "deslopify_review"]
ChunkFailureReason = Literal[
    "timeout", "llm_error", "malformed_output", "validation_error", "worker_error"
]
RunStatus = Literal["running", "completed", "completed_with_warnings", "failed", "cancelled"]
Triage = Literal["open", "false_positive", "accepted", "wont_fix"]


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    sha: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    patch: str | None = None


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    rule_id: str
    title: str = Field(max_length=80)
    rationale: str
    category: Category
    severity: Severity
    location: Location
    pass_: Pass = Field(alias="pass")
    suggestion: Suggestion | None = None
    evidence_snippet: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_reason: str | None = None
    exploitability: str | None = None
    reproduction: str | None = None
    test_analysis: str | None = None
    suggested_regression_test: str | None = None
    minimum_fix_scope: str | None = None
    triage: Triage = "open"
    triage_note: str | None = None
    created_at: datetime
    run_id: str


class ChunkFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    file: str
    pass_: Pass = Field(alias="pass")
    reason: ChunkFailureReason
    message: str


class RunMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    repo_root: str
    branch: str | None
    head_sha: str
    base_ref: str
    base_sha: str
    source_label: str
    passes: list[Pass]
    model: str
    chunks_total: int = Field(ge=0)
    chunks_done: int = Field(ge=0)
    chunks_failed: int = Field(ge=0)
    findings_count: int = Field(ge=0)
    allow_partial: bool
    chunk_failures: list[ChunkFailure] = Field(default_factory=list)
    config_hash: str
