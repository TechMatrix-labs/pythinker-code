"""Standalone `pythinker-review` Typer entry."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import sys
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import NoReturn

import typer
from pydantic import BaseModel

from pythinker_review.cli._shared import FailOn, OutputFormat, exit_code
from pythinker_review.engine.artifact_context import ArtifactDiffContext, build_artifact_context
from pythinker_review.engine.diff_source import DiffMode, EmptyDiffError, PreflightError
from pythinker_review.engine.orchestrator import EngineRunInput, EngineRunOutput, run_engine
from pythinker_review.llm.fake import FakeReviewLLM
from pythinker_review.llm.protocol import ReviewLLM
from pythinker_review.output.artifacts import render_artifact_json, render_artifact_pretty
from pythinker_review.output.json import render_json
from pythinker_review.output.pretty import render_pretty
from pythinker_review.output.sarif import render_sarif
from pythinker_review.reviewers.compliance import (
    ComplianceChecklistError,
    load_compliance_context,
)
from pythinker_review.reviewers.pr_artifacts import (
    run_changelog_artifact,
    run_code_suggestions_artifact,
    run_compliance_artifact,
    run_docs_artifact,
    run_labels_artifact,
    run_pr_description_artifact,
    run_pr_question_artifact,
)
from pythinker_review.reviewflow.workflow import (
    ReviewflowWorkflowError,
    ci_project,
    clean_locks_project,
    doctor_project,
    fix_project,
    init_project,
    map_project,
    next_project,
    open_pr_project,
    report_project,
    revalidate_project,
    review_project,
    show_finding_project,
    status_project,
    triage_project,
)
from pythinker_review.store.findings_store import FindingsStore
from pythinker_review.store.gitignore import ensure_gitignored
from pythinker_review.store.models import SEVERITY_ORDER, Finding, Pass, RunMeta

app = typer.Typer(add_completion=False, no_args_is_help=True)


class ReviewMode(str, Enum):
    default = "default"
    deslopify = "deslopify"


class ArtifactFormat(str, Enum):
    pretty = "pretty"
    json = "json"


def _resolve_llm() -> ReviewLLM:
    fake = os.environ.get("PYTHINKER_REVIEW_FAKE_LLM_RESPONSES")
    if fake is not None:
        return FakeReviewLLM(scripted=fake.split("\0") if fake else ['{"findings": []}'])
    typer.secho(
        "No active model configured. Set PYTHINKER_REVIEW_FAKE_LLM_RESPONSES for tests, "
        "or invoke via `pythinker review` for the Pythinker-integrated path.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=3)


def _emit(fmt: OutputFormat, *, meta: RunMeta, findings: list[Finding], no_color: bool) -> str:
    if fmt is OutputFormat.json:
        return render_json(meta, findings)
    if fmt is OutputFormat.sarif:
        return render_sarif(meta, findings)
    return render_pretty(meta, findings, no_color=no_color)


def _mode_from_flags(*, range_: str | None, working_tree: bool, staged: bool) -> DiffMode:
    if range_:
        return DiffMode.range
    if working_tree:
        return DiffMode.working_tree
    if staged:
        return DiffMode.staged
    return DiffMode.base


def _save_output(output: EngineRunOutput, *, repo: Path) -> None:
    store = FindingsStore(repo_root=repo)
    store.begin(output.meta)
    for finding in output.findings:
        store.append(finding)
    store.write_diff(output.meta.id, output.resolved.patch_text)
    store.finalize(output.meta)
    ensure_gitignored(repo_root=repo)


def _run_review_engine(inputs: EngineRunInput) -> EngineRunOutput:
    return asyncio.run(run_engine(llm=_resolve_llm(), inputs=inputs))


def _load_saved_findings(repo: Path) -> list[tuple[RunMeta, Finding]]:
    """Walk .pythinker-review/runs and pull every persisted finding.

    Resilient by design: a single corrupt findings.jsonl line, a half-written
    meta.json, or a malformed Finding record should not crash the entire
    list/show command. Bad records are skipped with a stderr note so the user
    can still see history from healthy runs.
    """
    state = repo / ".pythinker-review" / "runs"
    if not state.exists():
        return []
    out: list[tuple[RunMeta, Finding]] = []
    for run_dir in sorted(state.iterdir(), reverse=True):
        meta_file = run_dir / "meta.json"
        findings_file = run_dir / "findings.jsonl"
        if not meta_file.exists() or not findings_file.exists():
            continue
        try:
            meta = RunMeta.model_validate_json(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            typer.secho(
                f"warning: skipping corrupt meta.json in {run_dir.name}: {exc}",
                fg=typer.colors.YELLOW,
                err=True,
            )
            continue
        try:
            raw = findings_file.read_text(encoding="utf-8")
        except OSError as exc:
            typer.secho(
                f"warning: cannot read findings.jsonl in {run_dir.name}: {exc}",
                fg=typer.colors.YELLOW,
                err=True,
            )
            continue
        for line_no, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                out.append((meta, Finding.model_validate_json(line)))
            except ValueError as exc:
                typer.secho(
                    f"warning: skipping corrupt finding at "
                    f"{run_dir.name}/findings.jsonl:{line_no}: {exc}",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
    return out


def _rank_saved(item: tuple[RunMeta, Finding]) -> tuple[int, float, str, int]:
    _meta, finding = item
    return (
        SEVERITY_ORDER[finding.severity],
        finding.confidence,
        finding.location.file,
        -finding.location.start_line,
    )


def _reviewflow_ready(repo: Path, state_dir: str) -> bool:
    return (repo.resolve() / state_dir / "project.json").exists()


def _emit_workflow(payload: dict[str, object], *, json_output: bool = False) -> None:
    if json_output:
        machine_payload = {key: value for key, value in payload.items() if key != "markdown"}
        typer.echo(json.dumps(machine_payload, indent=2, default=str))
        return
    markdown = payload.get("markdown")
    if isinstance(markdown, str):
        typer.echo(markdown.rstrip())
        return
    for key, value in payload.items():
        if key in {"markdown", "items", "results"}:
            continue
        typer.echo(f"{key}: {value}")


def _workflow_exit(exc: ReviewflowWorkflowError) -> NoReturn:
    typer.secho(str(exc), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc


def _resolve_llm_quiet() -> ReviewLLM | None:
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            return _resolve_llm()
        except typer.Exit:
            return None


@app.command()
def diff(
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.pretty if sys.stdout.isatty() else OutputFormat.json, "--format"
    ),
    fail_on: FailOn = typer.Option(FailOn.high, "--fail-on"),
    allow_partial: bool = typer.Option(False, "--allow-partial"),
    jobs: int = typer.Option(4, "--jobs", min=1),
    save: bool = typer.Option(True, "--save/--no-save"),
    no_color: bool = typer.Option(
        False, "--no-color", help="Disable ANSI colors in pretty output."
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Deprecated alias for --no-color. Will be removed in a future release.",
        hidden=True,
    ),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    with_security: bool = typer.Option(False, "--with-security"),
    mode: ReviewMode = typer.Option(ReviewMode.default, "--mode"),
    chunk_budget_chars: int = typer.Option(12_000, "--chunk-budget-chars", min=500),
    per_chunk_timeout_s: float = typer.Option(120.0, "--per-chunk-timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    if quiet:
        typer.secho(
            "warning: --quiet is deprecated; use --no-color instead.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        no_color = no_color or quiet
    passes: tuple[Pass, ...]
    if mode is ReviewMode.deslopify:
        passes = ("deslopify_review", "security_review") if with_security else ("deslopify_review",)
    else:
        passes = ("code_review", "security_review") if with_security else ("code_review",)
    resolved_repo = repo.resolve()
    inputs = EngineRunInput(
        repo=resolved_repo,
        mode=_mode_from_flags(range_=range_, working_tree=working_tree, staged=staged),
        base_ref=base,
        rev_range=range_,
        passes=passes,
        diagnostics_by_file={},
        includes=tuple(include),
        excludes=tuple(exclude),
        skip_vendored=not no_skip_vendored,
        jobs=jobs,
        per_chunk_timeout_s=per_chunk_timeout_s,
        chunk_budget_chars=chunk_budget_chars,
        allow_partial=allow_partial,
    )
    try:
        output = _run_review_engine(inputs)
    except EmptyDiffError as exc:
        typer.secho(f"no changes to review: {exc}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=2) from exc
    except PreflightError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    if save:
        _save_output(output, repo=resolved_repo)
    typer.echo(_emit(fmt, meta=output.meta, findings=output.findings, no_color=no_color))
    raise typer.Exit(
        code=exit_code(meta=output.meta, findings=output.findings, fail_on=fail_on, llm_error=False)
    )


@app.command(name="init")
def init_stateful(
    force: bool = typer.Option(False, "--force"),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Initialize Reviewflow state for stateful review workflows."""
    try:
        payload = init_project(root=repo, state_dir=state_dir, config_path=config, force=force)
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="map")
def map_stateful(
    dry_run: bool = typer.Option(False, "--dry-run"),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Map repository files into durable feature records."""
    try:
        payload = map_project(root=repo, state_dir=state_dir, config_path=config, dry_run=dry_run)
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="status")
def status_stateful(
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show stateful review project status."""
    try:
        payload = status_project(root=repo, state_dir=state_dir, config_path=config)
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="review")
def review_stateful(
    feature: str | None = typer.Option(None, "--feature"),
    project: str | None = typer.Option(None, "--project"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    since: str | None = typer.Option(None, "--since"),
    jobs: int = typer.Option(1, "--jobs", min=1),
    mode: ReviewMode = typer.Option(ReviewMode.default, "--mode"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    include_dirty: bool = typer.Option(False, "--include-dirty"),
    timeout_s: float = typer.Option(180.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Review mapped features and persist Reviewflow findings."""
    try:
        payload = asyncio.run(
            review_project(
                llm=_resolve_llm(),
                root=repo,
                state_dir=state_dir,
                config_path=config,
                feature_id=feature,
                project_filter=project,
                since=since,
                include_dirty=include_dirty,
                limit=limit,
                jobs=jobs,
                mode=mode.value,
                dry_run=dry_run,
                per_feature_timeout_s=timeout_s,
            )
        )
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="ci")
def ci_stateful(
    limit: int | None = typer.Option(None, "--limit", min=1),
    since: str | None = typer.Option(None, "--since"),
    jobs: int = typer.Option(1, "--jobs", min=1),
    include_dirty: bool = typer.Option(False, "--include-dirty"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run init-if-needed, map, review, report, and GitHub step summary append."""
    try:
        payload = asyncio.run(
            ci_project(
                llm=_resolve_llm(),
                root=repo,
                state_dir=state_dir,
                config_path=config,
                limit=limit,
                since=since,
                jobs=jobs,
                output=output,
                include_dirty=include_dirty,
            )
        )
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="report")
def report_stateful(
    status: str | None = typer.Option(None, "--status"),
    severity: str | None = typer.Option(None, "--severity"),
    feature: str | None = typer.Option(None, "--feature"),
    project: str | None = typer.Option(None, "--project"),
    category: str | None = typer.Option(None, "--category"),
    triage: str | None = typer.Option(None, "--triage"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Render a Reviewflow-style Markdown or JSON findings report."""
    try:
        payload = report_project(
            root=repo,
            state_dir=state_dir,
            config_path=config,
            status=status,
            severity=severity,
            feature_id=feature,
            project_filter=project,
            category=category,
            triage=triage,
            output=output,
        )
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="triage")
def triage_stateful(
    finding: str = typer.Option(..., "--finding"),
    status: str = typer.Option(..., "--status"),
    note: str | None = typer.Option(None, "--note"),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Update one persisted finding's lifecycle status with optional note."""
    try:
        payload = triage_project(
            root=repo,
            finding_id=finding,
            status=status,
            note=note,
            state_dir=state_dir,
            config_path=config,
        )
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="revalidate")
def revalidate_stateful(
    finding: str | None = typer.Option(None, "--finding"),
    all_findings: bool = typer.Option(False, "--all"),
    status: str | None = typer.Option("open", "--status"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    timeout_s: float = typer.Option(180.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Re-check persisted findings against current code."""
    try:
        payload = asyncio.run(
            revalidate_project(
                llm=_resolve_llm(),
                root=repo,
                state_dir=state_dir,
                config_path=config,
                finding_id=finding,
                all_findings=all_findings,
                status=status,
                limit=limit,
                timeout_s=timeout_s,
            )
        )
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="fix")
def fix_stateful(
    finding: str = typer.Option(..., "--finding"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    timeout_s: float = typer.Option(240.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Ask the active model for a unified diff, apply it, and run validation commands."""
    try:
        payload = asyncio.run(
            fix_project(
                llm=_resolve_llm(),
                root=repo,
                finding_id=finding,
                state_dir=state_dir,
                config_path=config,
                dry_run=dry_run,
                timeout_s=timeout_s,
            )
        )
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="open-pr")
def open_pr_stateful(
    patch: str = typer.Option(..., "--patch"),
    base: str | None = typer.Option(None, "--base"),
    branch: str | None = typer.Option(None, "--branch"),
    title: str | None = typer.Option(None, "--title"),
    draft: bool = typer.Option(False, "--draft"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Commit an applied patch, push a branch, and open a GitHub PR via gh."""
    try:
        payload = open_pr_project(
            root=repo,
            patch_id=patch,
            state_dir=state_dir,
            config_path=config,
            base=base,
            branch=branch,
            title=title,
            draft=draft,
            dry_run=dry_run,
            force=force,
        )
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="doctor")
def doctor_stateful(
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Check git/gh/provider availability for Reviewflow workflows."""
    payload = doctor_project(llm=_resolve_llm_quiet(), root=repo)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="clean-locks")
def clean_locks_stateful(
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Clear stale feature lock files."""
    try:
        payload = clean_locks_project(root=repo, state_dir=state_dir, config_path=config)
    except ReviewflowWorkflowError as exc:
        _workflow_exit(exc)
    _emit_workflow(payload, json_output=json_output)


@app.command(name="list")
def list_runs(
    limit: int = typer.Option(20, "--limit", min=1),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    import json as _json

    idx = repo / ".pythinker-review" / "index.json"
    if not idx.exists():
        typer.echo("no runs")
        raise typer.Exit(code=0)
    parsed = _json.loads(idx.read_text(encoding="utf-8"))
    runs = parsed.get("runs", [])[:limit]
    for item in runs:
        if isinstance(item, dict):
            typer.echo(
                f"{item.get('id')}  {item.get('status')}  "
                f"findings={item.get('findings_count')}  branch={item.get('branch')}"
            )


@app.command()
def show(
    run_id: str | None = typer.Argument(None),
    finding: str | None = typer.Option(None, "--finding"),
    fmt: OutputFormat = typer.Option(OutputFormat.pretty, "--format"),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if finding is not None:
        try:
            payload = show_finding_project(
                root=repo, finding_id=finding, state_dir=state_dir, config_path=config
            )
        except ReviewflowWorkflowError as exc:
            _workflow_exit(exc)
        _emit_workflow(payload, json_output=json_output or fmt is OutputFormat.json)
        return
    if run_id is None:
        typer.secho("missing RUN_ID or --finding", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    run_dir = repo / ".pythinker-review" / "runs" / run_id
    if not run_dir.exists():
        typer.secho(f"unknown run: {run_id}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    meta = RunMeta.model_validate_json((run_dir / "meta.json").read_text(encoding="utf-8"))
    findings: list[Finding] = []
    findings_file = run_dir / "findings.jsonl"
    if findings_file.exists():
        for line in findings_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                findings.append(Finding.model_validate_json(line))
    typer.echo(_emit(fmt, meta=meta, findings=findings, no_color=False))


@app.command(name="show-finding")
def show_finding(
    finding_id: str,
    fmt: OutputFormat = typer.Option(OutputFormat.pretty, "--format"),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    for meta, finding in _load_saved_findings(repo):
        if finding.id == finding_id:
            typer.echo(_emit(fmt, meta=meta, findings=[finding], no_color=False))
            raise typer.Exit(code=0)
    typer.secho(f"unknown finding: {finding_id}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


@app.command()
def next(
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
    include_triaged: bool = typer.Option(False, "--include-triaged"),
    state_dir: str = typer.Option(".pythinker-review-flow", "--state-dir"),
    config: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if _reviewflow_ready(repo, state_dir):
        try:
            payload = next_project(root=repo, state_dir=state_dir, config_path=config)
        except ReviewflowWorkflowError as exc:
            _workflow_exit(exc)
        _emit_workflow(payload, json_output=json_output)
        return
    items = _load_saved_findings(repo)
    if not include_triaged:
        items = [(meta, finding) for meta, finding in items if finding.triage == "open"]
    if not items:
        typer.echo("no open findings")
        raise typer.Exit(code=0)
    meta, finding = max(items, key=_rank_saved)
    typer.echo(
        f"{finding.id}  {finding.severity.value}  {finding.location.file}:"
        f"{finding.location.start_line}  {finding.title}  run={meta.id}"
    )
    if finding.minimum_fix_scope:
        typer.echo(f"minimum_fix_scope: {finding.minimum_fix_scope}")
    if finding.suggested_regression_test:
        typer.echo(f"suggested_regression_test: {finding.suggested_regression_test}")


def _build_artifact_context_from_flags(
    *,
    repo: Path,
    base: str,
    staged: bool,
    working_tree: bool,
    range_: str | None,
    include: list[str],
    exclude: list[str],
    no_skip_vendored: bool,
    budget_chars: int,
) -> ArtifactDiffContext:
    return build_artifact_context(
        repo=repo.resolve(),
        mode=_mode_from_flags(range_=range_, working_tree=working_tree, staged=staged),
        base_ref=base,
        rev_range=range_,
        includes=tuple(include),
        excludes=tuple(exclude),
        skip_vendored=not no_skip_vendored,
        budget_chars=budget_chars,
    )


def _emit_artifact(
    fmt: ArtifactFormat, *, kind: str, output: BaseModel, metadata: dict[str, str]
) -> str:
    if fmt is ArtifactFormat.json:
        return render_artifact_json(kind, output, metadata=metadata)
    return render_artifact_pretty(kind, output, metadata=metadata)


def _run_artifact(
    kind: str,
    ctx: ArtifactDiffContext,
    *,
    timeout_s: float,
    question: str = "",
    artifact_context: str = "",
) -> BaseModel:
    async def inner() -> BaseModel:
        llm = _resolve_llm()
        if kind == "describe":
            result = await run_pr_description_artifact(
                diff=ctx.rendered_diff, metadata=ctx.metadata, llm=llm, timeout_s=timeout_s
            )
        elif kind in {"suggest", "improve"}:
            result = await run_code_suggestions_artifact(
                diff=ctx.rendered_diff, metadata=ctx.metadata, llm=llm, timeout_s=timeout_s
            )
        elif kind == "ask":
            result = await run_pr_question_artifact(
                question=question,
                diff=ctx.rendered_diff,
                metadata=ctx.metadata,
                llm=llm,
                timeout_s=timeout_s,
            )
        elif kind == "labels":
            result = await run_labels_artifact(
                diff=ctx.rendered_diff, metadata=ctx.metadata, llm=llm, timeout_s=timeout_s
            )
        elif kind == "changelog":
            result = await run_changelog_artifact(
                diff=ctx.rendered_diff, metadata=ctx.metadata, llm=llm, timeout_s=timeout_s
            )
        elif kind == "docs":
            result = await run_docs_artifact(
                diff=ctx.rendered_diff, metadata=ctx.metadata, llm=llm, timeout_s=timeout_s
            )
        elif kind == "compliance":
            result = await run_compliance_artifact(
                diff=ctx.rendered_diff,
                metadata=ctx.metadata,
                compliance_context=artifact_context,
                llm=llm,
                timeout_s=timeout_s,
            )
        else:
            raise RuntimeError(f"unknown artifact kind: {kind}")
        if not result.ok or result.output is None:
            message = result.failure_message or result.failure_reason or "unknown model error"
            raise RuntimeError(str(message))
        return result.output

    return asyncio.run(inner())


def _run_artifact_command(
    *,
    kind: str,
    base: str,
    staged: bool,
    working_tree: bool,
    range_: str | None,
    fmt: ArtifactFormat,
    include: list[str],
    exclude: list[str],
    no_skip_vendored: bool,
    budget_chars: int,
    timeout_s: float,
    repo: Path,
    question: str = "",
    artifact_context: str = "",
) -> None:
    try:
        ctx = _build_artifact_context_from_flags(
            repo=repo,
            base=base,
            staged=staged,
            working_tree=working_tree,
            range_=range_,
            include=include,
            exclude=exclude,
            no_skip_vendored=no_skip_vendored,
            budget_chars=budget_chars,
        )
        output = _run_artifact(
            kind, ctx, timeout_s=timeout_s, question=question, artifact_context=artifact_context
        )
    except EmptyDiffError as exc:
        typer.secho(f"no changes to analyze: {exc}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=2) from exc
    except PreflightError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    except RuntimeError as exc:
        typer.secho(f"artifact generation failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from exc
    typer.echo(_emit_artifact(fmt, kind=kind, output=output, metadata=ctx.metadata))


@app.command()
def describe(
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: ArtifactFormat = typer.Option(ArtifactFormat.pretty, "--format"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    budget_chars: int = typer.Option(24_000, "--budget-chars", min=500),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    """Draft a PR title, description, and file walkthrough from the diff."""
    _run_artifact_command(
        kind="describe",
        base=base,
        staged=staged,
        working_tree=working_tree,
        range_=range_,
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_skip_vendored=no_skip_vendored,
        budget_chars=budget_chars,
        timeout_s=timeout_s,
        repo=repo,
    )


@app.command()
def suggest(
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: ArtifactFormat = typer.Option(ArtifactFormat.pretty, "--format"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    budget_chars: int = typer.Option(24_000, "--budget-chars", min=500),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    """Draft targeted code suggestions from the diff (source /improve parity)."""
    _run_artifact_command(
        kind="suggest",
        base=base,
        staged=staged,
        working_tree=working_tree,
        range_=range_,
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_skip_vendored=no_skip_vendored,
        budget_chars=budget_chars,
        timeout_s=timeout_s,
        repo=repo,
    )


@app.command()
def improve(
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: ArtifactFormat = typer.Option(ArtifactFormat.pretty, "--format"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    budget_chars: int = typer.Option(24_000, "--budget-chars", min=500),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    """Alias for `suggest`, matching code-reviewr's /improve command."""
    _run_artifact_command(
        kind="improve",
        base=base,
        staged=staged,
        working_tree=working_tree,
        range_=range_,
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_skip_vendored=no_skip_vendored,
        budget_chars=budget_chars,
        timeout_s=timeout_s,
        repo=repo,
    )


@app.command()
def ask(
    question: list[str] = typer.Argument(..., help="Question to answer about the diff."),
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: ArtifactFormat = typer.Option(ArtifactFormat.pretty, "--format"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    budget_chars: int = typer.Option(24_000, "--budget-chars", min=500),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    """Answer a question about the diff."""
    _run_artifact_command(
        kind="ask",
        base=base,
        staged=staged,
        working_tree=working_tree,
        range_=range_,
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_skip_vendored=no_skip_vendored,
        budget_chars=budget_chars,
        timeout_s=timeout_s,
        repo=repo,
        question=" ".join(question),
    )


@app.command()
def labels(
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: ArtifactFormat = typer.Option(ArtifactFormat.pretty, "--format"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    budget_chars: int = typer.Option(24_000, "--budget-chars", min=500),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    """Suggest PR labels from the diff."""
    _run_artifact_command(
        kind="labels",
        base=base,
        staged=staged,
        working_tree=working_tree,
        range_=range_,
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_skip_vendored=no_skip_vendored,
        budget_chars=budget_chars,
        timeout_s=timeout_s,
        repo=repo,
    )


@app.command()
def changelog(
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: ArtifactFormat = typer.Option(ArtifactFormat.pretty, "--format"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    budget_chars: int = typer.Option(24_000, "--budget-chars", min=500),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    """Draft a changelog entry from the diff."""
    _run_artifact_command(
        kind="changelog",
        base=base,
        staged=staged,
        working_tree=working_tree,
        range_=range_,
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_skip_vendored=no_skip_vendored,
        budget_chars=budget_chars,
        timeout_s=timeout_s,
        repo=repo,
    )


@app.command(name="docs")
def docs_command(
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: ArtifactFormat = typer.Option(ArtifactFormat.pretty, "--format"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    budget_chars: int = typer.Option(24_000, "--budget-chars", min=500),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    """Draft documentation update suggestions from the diff."""
    _run_artifact_command(
        kind="docs",
        base=base,
        staged=staged,
        working_tree=working_tree,
        range_=range_,
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_skip_vendored=no_skip_vendored,
        budget_chars=budget_chars,
        timeout_s=timeout_s,
        repo=repo,
    )


@app.command()
def compliance(
    base: str = typer.Option("origin/main", "--base"),
    staged: bool = typer.Option(False, "--staged"),
    working_tree: bool = typer.Option(False, "--working-tree"),
    range_: str | None = typer.Option(None, "--range"),
    fmt: ArtifactFormat = typer.Option(ArtifactFormat.pretty, "--format"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
    no_skip_vendored: bool = typer.Option(False, "--no-skip-vendored"),
    checklist: Path | None = typer.Option(
        None,
        "--checklist",
        help="YAML checklist. Defaults to the bundled code-reviewr compliance checklist.",
    ),
    ticket_text: str = typer.Option("", "--ticket-text", help="Inline ticket/acceptance criteria."),
    ticket_file: Path | None = typer.Option(None, "--ticket-file"),
    budget_chars: int = typer.Option(24_000, "--budget-chars", min=500),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
    repo: Path = typer.Option(Path.cwd(), "--repo", "--root"),
) -> None:
    """Check the diff against a compliance checklist and optional ticket context."""
    try:
        compliance_context = load_compliance_context(
            checklist_path=checklist, ticket_text=ticket_text, ticket_file=ticket_file
        )
    except ComplianceChecklistError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    _run_artifact_command(
        kind="compliance",
        base=base,
        staged=staged,
        working_tree=working_tree,
        range_=range_,
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_skip_vendored=no_skip_vendored,
        budget_chars=budget_chars,
        timeout_s=timeout_s,
        repo=repo,
        artifact_context=compliance_context,
    )


__all__: Sequence[str] = ("app", "_resolve_llm", "_emit")
