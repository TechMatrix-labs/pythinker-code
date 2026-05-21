"""Public engine entry tying diff resolution, rendering, chunking, running, and dedupe."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from pythinker_review.engine.chunker import build_chunks
from pythinker_review.engine.dedupe import dedupe_findings
from pythinker_review.engine.diff_source import DiffMode, ResolvedDiff, resolve_diff
from pythinker_review.engine.runner import RunnerResult, run_chunks
from pythinker_review.engine.structured_diff import render_structured_diff
from pythinker_review.llm.protocol import ReviewLLM
from pythinker_review.signals.models import Signal
from pythinker_review.signals.scanner import scan_signals
from pythinker_review.store.ids import generate_run_id
from pythinker_review.store.models import Finding, Pass, RunMeta, RunStatus


@dataclass(frozen=True, slots=True)
class EngineRunInput:
    repo: Path
    mode: DiffMode
    base_ref: str
    rev_range: str | None
    passes: tuple[Pass, ...]
    diagnostics_by_file: dict[str, str]
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    skip_vendored: bool
    jobs: int
    per_chunk_timeout_s: float
    chunk_budget_chars: int
    allow_partial: bool


@dataclass(frozen=True, slots=True)
class EngineRunOutput:
    meta: RunMeta
    findings: list[Finding]
    runner: RunnerResult
    resolved: ResolvedDiff


def _config_hash(passes: tuple[Pass, ...]) -> str:
    parts: list[str] = list(passes)
    for name in ("code_review.system.md", "security_review.system.md", "debug_review.system.md"):
        try:
            parts.append(
                resources.files("pythinker_review.reviewers.prompts")
                .joinpath(name)
                .read_text(encoding="utf-8")
            )
        except (FileNotFoundError, ModuleNotFoundError):
            continue
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _added_lines_by_file(patch_text: str) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    new_lineno = 0
    for line in patch_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[len("+++ b/") :].strip()
            out.setdefault(current, [])
            continue
        if line.startswith("@@"):
            try:
                new_lineno = int(line.split("+", 1)[1].split(",", 1)[0].split(" ", 1)[0])
            except (IndexError, ValueError):
                new_lineno = 0
            continue
        if not current:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            out[current].append((new_lineno, line[1:]))
            new_lineno += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            new_lineno += 1
    return out


def _branch_name(repo: Path) -> str | None:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    branch = proc.stdout.strip()
    return branch or None


async def run_engine(*, llm: ReviewLLM, inputs: EngineRunInput) -> EngineRunOutput:
    resolved = resolve_diff(
        inputs.repo,
        mode=inputs.mode,
        base_ref=inputs.base_ref,
        rev_range=inputs.rev_range,
    )
    structured_files = render_structured_diff(resolved.patch_text)
    chunks = build_chunks(
        structured_files,
        includes=inputs.includes,
        excludes=inputs.excludes,
        skip_vendored=inputs.skip_vendored,
        budget_chars=inputs.chunk_budget_chars,
    )
    signals_by_file: dict[str, list[Signal]] = {}
    if "security_review" in inputs.passes:
        for path, lines in _added_lines_by_file(resolved.patch_text).items():
            signals_by_file[path] = scan_signals(file_path=path, added_lines=lines)

    started = datetime.now(tz=UTC)
    run_id = generate_run_id(now=started)
    runner = await run_chunks(
        chunks=chunks,
        passes=inputs.passes,
        signals_by_file=signals_by_file,
        diagnostics_by_file=inputs.diagnostics_by_file,
        llm=llm,
        jobs=inputs.jobs,
        per_chunk_timeout_s=inputs.per_chunk_timeout_s,
        allow_partial=inputs.allow_partial,
    )
    findings = dedupe_findings(
        [(tagged.pass_, tagged.finding) for tagged in runner.findings],
        run_id=run_id,
        head_sha=resolved.head_sha,
        created_at=started,
    )
    finished = datetime.now(tz=UTC)
    if runner.cancelled:
        status: RunStatus = "cancelled"
    elif runner.failed:
        status = "failed"
    elif runner.chunks_failed and inputs.allow_partial:
        status = "completed_with_warnings"
    else:
        status = "completed"
    meta = RunMeta(
        id=run_id,
        started_at=started,
        finished_at=finished,
        status=status,
        repo_root=str(inputs.repo),
        branch=_branch_name(inputs.repo),
        head_sha=resolved.head_sha,
        base_ref=resolved.base_ref,
        base_sha=resolved.base_sha,
        source_label=resolved.source_label,
        passes=list(inputs.passes),
        model=llm.model_display_name,
        chunks_total=runner.chunks_total,
        chunks_done=runner.chunks_done,
        chunks_failed=runner.chunks_failed,
        findings_count=len(findings),
        allow_partial=inputs.allow_partial,
        chunk_failures=list(runner.chunk_failures),
        config_hash=_config_hash(inputs.passes),
    )
    return EngineRunOutput(meta=meta, findings=findings, runner=runner, resolved=resolved)


__all__ = ["EngineRunInput", "EngineRunOutput", "run_engine", "_added_lines_by_file"]
