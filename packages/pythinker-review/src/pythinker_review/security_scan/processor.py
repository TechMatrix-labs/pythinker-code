"""LLM-backed processing, triage, and revalidation for Pythinker Security Scan file records."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pythinker_review.llm.protocol import ReviewLLM
from pythinker_review.security_scan.models import (
    AnalysisEntry,
    FileRecord,
    Finding,
    Revalidation,
    Triage,
    now_iso,
)
from pythinker_review.security_scan.prompt import assemble_prompt, batch_languages
from pythinker_review.security_scan.store import (
    complete_run,
    create_run_meta,
    load_all_file_records,
    read_info,
    read_project_config,
    read_project_settings,
    write_file_record,
    write_run_meta,
)
from pythinker_review.security_scan.tech import read_tech_json


@dataclass(frozen=True, slots=True)
class ProcessResult:
    run_id: str
    analysis_count: int
    finding_count: int
    error_batch_count: int


@dataclass(frozen=True, slots=True)
class TriageResult:
    triaged: int
    p0: int
    p1: int
    p2: int
    skip: int


@dataclass(frozen=True, slots=True)
class RevalidateResult:
    revalidated: int
    true_positive: int
    false_positive: int
    fixed: int
    uncertain: int


def batch_candidates(records: list[FileRecord], max_size: int = 5) -> list[list[FileRecord]]:
    by_dir: dict[str, list[FileRecord]] = {}
    for record in records:
        by_dir.setdefault(str(Path(record.file_path).parent), []).append(record)
    batches: list[list[FileRecord]] = []
    current: list[FileRecord] = []
    for group in by_dir.values():
        if len(group) >= max_size:
            for idx in range(0, len(group), max_size):
                batches.append(group[idx : idx + max_size])
        elif len(current) + len(group) > max_size:
            if current:
                batches.append(current)
            current = list(group)
        else:
            current.extend(group)
    if current:
        batches.append(current)
    return batches


async def process_project(
    *,
    project_id: str,
    data_root: Path,
    llm: ReviewLLM,
    limit: int | None = None,
    batch_size: int = 5,
    jobs: int = 1,
    timeout_s: float = 180.0,
    reinvestigate: bool = False,
) -> ProcessResult:
    project = read_project_config(project_id, data_root=data_root)
    root = Path(project.root_path)
    settings = read_project_settings(project_id, data_root=data_root)
    records = _records_to_process(
        load_all_file_records(project_id, data_root=data_root), reinvestigate
    )
    if limit is not None:
        records = records[:limit]
    run = create_run_meta(
        project_id=project_id,
        root_path=root,
        run_type="process",
        processor_config={
            "agentType": "pythinker-review-llm",
            "model": llm.model_display_name,
            "modelConfig": {},
            "invocationMode": "scan",
        },
    )
    write_run_meta(run, data_root=data_root)
    if not records:
        complete_run(
            project_id,
            run.run_id,
            "done",
            data_root=data_root,
            stats={"filesProcessed": 0, "findingsCount": 0},
        )
        return ProcessResult(
            run_id=run.run_id, analysis_count=0, finding_count=0, error_batch_count=0
        )

    batches = batch_candidates(records, batch_size)
    semaphore = asyncio.Semaphore(max(1, jobs))
    counters = {"analysis": 0, "findings": 0, "errors": 0}

    async def worker(batch: list[FileRecord]) -> None:
        async with semaphore:
            try:
                analysis_count, finding_count = await _process_batch(
                    batch=batch,
                    project_id=project_id,
                    run_id=run.run_id,
                    root=root,
                    data_root=data_root,
                    llm=llm,
                    project_info=read_info(project_id, data_root=data_root),
                    prompt_append=settings.prompt_append,
                    timeout_s=timeout_s,
                )
                counters["analysis"] += analysis_count
                counters["findings"] += finding_count
            except Exception:
                counters["errors"] += 1
                for record in batch:
                    record.status = "error"
                    record.locked_by_run_id = None
                    record.locked_at = None
                    write_file_record(record, data_root=data_root)

    await asyncio.gather(*(worker(batch) for batch in batches))
    phase = "error" if counters["errors"] and counters["analysis"] == 0 else "done"
    complete_run(
        project_id,
        run.run_id,
        phase,
        data_root=data_root,
        stats={
            "filesProcessed": counters["analysis"],
            "findingsCount": counters["findings"],
        },
    )
    return ProcessResult(
        run_id=run.run_id,
        analysis_count=counters["analysis"],
        finding_count=counters["findings"],
        error_batch_count=counters["errors"],
    )


async def _process_batch(
    *,
    batch: list[FileRecord],
    project_id: str,
    run_id: str,
    root: Path,
    data_root: Path,
    llm: ReviewLLM,
    project_info: str,
    prompt_append: str | None,
    timeout_s: float,
) -> tuple[int, int]:
    now = now_iso()
    for record in batch:
        record.status = "processing"
        record.locked_by_run_id = run_id
        record.locked_at = now
        write_file_record(record, data_root=data_root)

    detected = read_tech_json(project_id, data_root=data_root)
    slugs = sorted({candidate.vuln_slug for record in batch for candidate in record.candidates})
    assembly = assemble_prompt(
        detected_tags=detected.tags if detected else [],
        batch_slugs=slugs,
        batch_languages=batch_languages(batch),
        project_info=project_info,
        prompt_append=prompt_append,
        records=batch,
        project_root=root,
    )
    start = time.perf_counter()
    raw = await llm.complete_json(system=assembly.system, user=assembly.user, timeout_s=timeout_s)
    duration_ms = int((time.perf_counter() - start) * 1000)
    parsed = parse_investigate_results(raw, batch)
    by_path = {item["filePath"]: item.get("findings", []) for item in parsed}

    finding_count = 0
    for record in batch:
        new_findings: list[Finding] = []
        for raw_finding in by_path.get(record.file_path, []):
            if not isinstance(raw_finding, dict):
                continue
            raw_finding = {**raw_finding, "producedByRunId": run_id}
            try:
                new_findings.append(Finding.model_validate(raw_finding))
            except ValueError:
                continue
        _merge_findings(record, new_findings)
        finding_count += len(new_findings)
        record.analysis_history.append(
            AnalysisEntry.model_validate(
                {
                    "runId": run_id,
                    "investigatedAt": now_iso(),
                    "durationMs": duration_ms,
                    "agentType": "pythinker-review-llm",
                    "model": llm.model_display_name,
                    "modelConfig": {},
                    "findingCount": len(new_findings),
                    "phase": "process",
                }
            )
        )
        record.status = "analyzed"
        record.locked_by_run_id = None
        record.locked_at = None
        write_file_record(record, data_root=data_root)
    return len(batch), finding_count


def parse_investigate_results(result_text: str, batch: list[FileRecord]) -> list[dict[str, Any]]:
    parsed = _parse_json_payload(result_text)
    if not isinstance(parsed, list):
        raise ValueError("Pythinker Security Scan processor output must be a JSON array")
    batch_paths = {record.file_path for record in batch}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        path = item.get("filePath")
        if isinstance(path, str) and path in batch_paths:
            out.append(item)
            seen.add(path)
    for missing in sorted(batch_paths - seen):
        out.append({"filePath": missing, "findings": []})
    return out


async def revalidate_project(
    *,
    project_id: str,
    data_root: Path,
    llm: ReviewLLM,
    force: bool = False,
    limit: int | None = None,
    timeout_s: float = 180.0,
) -> RevalidateResult:
    records = load_all_file_records(project_id, data_root=data_root)
    items: list[tuple[FileRecord, Finding]] = []
    for record in records:
        for finding in record.findings:
            if force or finding.revalidation is None:
                items.append((record, finding))
    if limit is not None:
        items = items[:limit]
    if not items:
        return RevalidateResult(0, 0, 0, 0, 0)
    run = create_run_meta(
        project_id=project_id,
        root_path=Path(read_project_config(project_id, data_root=data_root).root_path),
        run_type="revalidate",
        processor_config={
            "agentType": "pythinker-review-llm",
            "model": llm.model_display_name,
            "modelConfig": {},
        },
    )
    write_run_meta(run, data_root=data_root)
    raw = await llm.complete_json(
        system="You are a strict static security revalidator. Output JSON only.",
        user=_revalidate_prompt(items),
        timeout_s=timeout_s,
    )
    parsed = _parse_json_payload(raw)
    if not isinstance(parsed, list):
        raise ValueError("revalidation output must be a JSON array")
    by_key = {(record.file_path, finding.title): (record, finding) for record, finding in items}
    counts = {"true-positive": 0, "false-positive": 0, "fixed": 0, "uncertain": 0}
    for verdict in parsed:
        if not isinstance(verdict, dict):
            continue
        key = (str(verdict.get("filePath")), str(verdict.get("title")))
        item = by_key.get(key)
        verdict_value = verdict.get("verdict")
        if item is None or verdict_value not in counts:
            continue
        record, finding = item
        finding.revalidation = Revalidation.model_validate(
            {
                "verdict": verdict_value,
                "reasoning": str(verdict.get("reasoning", "")),
                "adjustedSeverity": verdict.get("adjustedSeverity"),
                "revalidatedAt": now_iso(),
                "runId": run.run_id,
                "model": llm.model_display_name,
            }
        )
        counts[verdict_value] += 1
        record.analysis_history.append(
            AnalysisEntry.model_validate(
                {
                    "runId": run.run_id,
                    "investigatedAt": now_iso(),
                    "durationMs": 0,
                    "agentType": "pythinker-review-llm",
                    "model": llm.model_display_name,
                    "modelConfig": {},
                    "findingCount": 0,
                    "phase": "revalidate",
                }
            )
        )
        write_file_record(record, data_root=data_root)
    total = sum(counts.values())
    complete_run(
        project_id,
        run.run_id,
        "done",
        data_root=data_root,
        stats={
            "findingsRevalidated": total,
            "truePositives": counts["true-positive"],
            "falsePositives": counts["false-positive"],
            "fixed": counts["fixed"],
            "uncertain": counts["uncertain"],
        },
    )
    return RevalidateResult(
        revalidated=total,
        true_positive=counts["true-positive"],
        false_positive=counts["false-positive"],
        fixed=counts["fixed"],
        uncertain=counts["uncertain"],
    )


async def triage_project(
    *,
    project_id: str,
    data_root: Path,
    llm: ReviewLLM,
    severity: str = "MEDIUM",
    limit: int | None = None,
    timeout_s: float = 120.0,
) -> TriageResult:
    records = load_all_file_records(project_id, data_root=data_root)
    items: list[tuple[FileRecord, Finding]] = []
    for record in records:
        for finding in record.findings:
            if finding.severity == severity and finding.triage is None:
                items.append((record, finding))
    if limit is not None:
        items = items[:limit]
    if not items:
        return TriageResult(triaged=0, p0=0, p1=0, p2=0, skip=0)
    prompt = _triage_prompt(items)
    raw = await llm.complete_json(
        system="You are a strict security triage classifier. Output JSON only.",
        user=prompt,
        timeout_s=timeout_s,
    )
    parsed = _parse_json_payload(raw)
    if not isinstance(parsed, list):
        raise ValueError("triage output must be a JSON array")
    by_title = {finding.title: (record, finding) for record, finding in items}
    counts = {"P0": 0, "P1": 0, "P2": 0, "skip": 0}
    for verdict in parsed:
        if not isinstance(verdict, dict):
            continue
        item = by_title.get(str(verdict.get("title")))
        priority = verdict.get("priority")
        if item is None or priority not in counts:
            continue
        record, finding = item
        finding.triage = Triage.model_validate(
            {
                "priority": priority,
                "exploitability": verdict.get("exploitability", "moderate"),
                "impact": verdict.get("impact", "medium"),
                "reasoning": verdict.get("reasoning", ""),
                "triagedAt": now_iso(),
                "model": llm.model_display_name,
            }
        )
        counts[priority] += 1
        write_file_record(record, data_root=data_root)
    total = sum(counts.values())
    return TriageResult(
        triaged=total, p0=counts["P0"], p1=counts["P1"], p2=counts["P2"], skip=counts["skip"]
    )


def _records_to_process(records: list[FileRecord], reinvestigate: bool) -> list[FileRecord]:
    if reinvestigate:
        return [record for record in records if record.candidates]
    return [
        record for record in records if record.candidates and record.status in {"pending", "error"}
    ]


def _merge_findings(record: FileRecord, new_findings: list[Finding]) -> None:
    seen = {(finding.vuln_slug, finding.title) for finding in record.findings}
    for finding in new_findings:
        key = (finding.vuln_slug, finding.title)
        if key not in seen:
            record.findings.append(finding)
            seen.add(key)


def _parse_json_payload(raw: str) -> Any:
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
            if stripped.startswith("json\n"):
                stripped = stripped[5:].strip()
    if "```json" in raw:
        start = raw.find("```json") + len("```json")
        end = raw.find("```", start)
        if end != -1:
            stripped = raw[start:end].strip()
    return json.loads(stripped)


def _revalidate_prompt(items: list[tuple[FileRecord, Finding]]) -> str:
    lines = []
    for idx, (record, finding) in enumerate(items, start=1):
        lines.append(
            f"### {idx}. {finding.title}\n"
            f"- filePath: `{record.file_path}`\n"
            f"- Severity: {finding.severity}\n"
            f"- Slug: {finding.vuln_slug}\n"
            f"- Lines: {', '.join(map(str, finding.line_numbers))}\n"
            f"- Description: {finding.description}\n"
            f"- Recommendation: {finding.recommendation}"
        )
    return (
        "Re-check each finding using static reasoning. Verdicts: true-positive, false-positive, fixed, uncertain. "
        "Use false-positive when a concrete mitigation exists; fixed when the described code is gone or safely changed.\n\n"
        + "\n\n".join(lines)
        + '\n\nReturn JSON: [{"filePath":"path","title":"exact title","verdict":"true-positive|false-positive|fixed|uncertain",'
        + '"adjustedSeverity":"CRITICAL|HIGH|MEDIUM|HIGH_BUG|BUG|LOW", "reasoning":"5-10 sentences"}]'
    )


def _triage_prompt(items: list[tuple[FileRecord, Finding]]) -> str:
    lines = []
    for idx, (record, finding) in enumerate(items, start=1):
        lines.append(
            f"### {idx}. {finding.title}\n"
            f"- File: `{record.file_path}`\n"
            f"- Severity: {finding.severity}\n"
            f"- Slug: {finding.vuln_slug}\n"
            f"- Lines: {', '.join(map(str, finding.line_numbers))}\n"
            f"- Confidence: {finding.confidence}\n"
            f"- Description: {finding.description}"
        )
    return (
        "Classify each finding by remediation priority.\n\n"
        "P0: externally exploitable, direct high impact, fix immediately.\n"
        "P1: real vulnerability with meaningful impact but narrower preconditions.\n"
        "P2: low impact, difficult exploit, or defense-in-depth.\n"
        "skip: false positive or not actionable.\n\n"
        + "\n\n".join(lines)
        + '\n\nReturn JSON: [{"title":"exact title","priority":"P0|P1|P2|skip",'
        + '"exploitability":"trivial|moderate|difficult","impact":"critical|high|medium|low",'
        + '"reasoning":"1-2 sentences"}]'
    )
