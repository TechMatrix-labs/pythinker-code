"""`pythinker-security-scan` — Python-native Pythinker Security Scan repo scanner and processor."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import typer

from pythinker_review.llm.fake import FakeReviewLLM
from pythinker_review.llm.protocol import ReviewLLM
from pythinker_review.security_scan.matchers import create_default_registry
from pythinker_review.security_scan.paths import DEFAULT_STATE_DIR, get_data_root
from pythinker_review.security_scan.processor import (
    process_project,
    revalidate_project,
    triage_project,
)
from pythinker_review.security_scan.prompt import assemble_prompt, batch_languages
from pythinker_review.security_scan.reporting import (
    export_findings,
    project_status,
    render_markdown_report,
    write_report,
)
from pythinker_review.security_scan.reporting import (
    metrics as project_metrics,
)
from pythinker_review.security_scan.scanner import scan_project
from pythinker_review.security_scan.store import (
    ensure_project,
    load_all_file_records,
    read_info,
    read_project_settings,
    write_info,
)
from pythinker_review.security_scan.tech import detect_tech, read_tech_json, write_tech_json

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _resolve_llm() -> ReviewLLM:
    fake = os.environ.get("PYTHINKER_REVIEW_FAKE_LLM_RESPONSES")
    if fake is not None:
        return FakeReviewLLM(scripted=fake.split("\0") if fake else ["[]"])
    typer.secho(
        "No active model configured. Invoke via `pythinker security-scan ...` or set "
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES for tests.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=3)


def _data_root(root: Path, state_dir: str) -> Path:
    env_data = os.environ.get("PYTHINKER_SECURITY_SCAN_DATA_ROOT")
    if env_data:
        return get_data_root(None).resolve()
    state = Path(state_dir)
    if not state.is_absolute():
        state = root.resolve() / state
    return (state / "data").resolve()


def _project_id(root: Path, project_id: str | None) -> str:
    if project_id:
        return project_id
    name = root.resolve().name
    return "project" if name in {"", "/"} else name.replace(" ", "-")


@app.command()
def init(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
    force_info: bool = typer.Option(False, "--force-info"),
) -> None:
    """Initialize a Pythinker Security Scan data mirror for a repository."""
    root = root.resolve()
    pid = _project_id(root, project_id)
    data_root = _data_root(root, state_dir)
    ensure_project(pid, root, data_root=data_root)
    detected = detect_tech(root)
    write_tech_json(pid, detected, data_root=data_root)
    info_path = data_root / pid / "INFO.md"
    if force_info or not info_path.exists():
        write_info(pid, _default_info(pid, detected.tags), data_root=data_root)
    typer.echo(
        json.dumps(
            {"projectId": pid, "dataRoot": str(data_root), "techTags": detected.tags},
            indent=2,
        )
    )


@app.command()
def scan(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
    matcher: list[str] = typer.Option([], "--matcher", help="Run only this matcher slug."),
    ignore: list[str] = typer.Option([], "--ignore", help="Extra ignore glob."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run deterministic matcher scan and write FileRecords."""
    root = root.resolve()
    pid = _project_id(root, project_id)
    data_root = _data_root(root, state_dir)
    result = scan_project(
        project_id=pid,
        root=root,
        data_root=data_root,
        matcher_slugs=matcher or None,
        ignore_paths=ignore or None,
        on_progress=None if json_output else lambda p: typer.echo(p.message, err=True),
    )
    payload = {
        "projectId": pid,
        "runId": result.run_id,
        "filesWithCandidates": result.files_with_candidates,
        "candidateCount": result.candidate_count,
        "activeMatchers": result.active_matchers,
        "skippedMatchers": result.skipped_matchers,
        "languageStats": [asdict(s) for s in result.language_stats],
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(
            f"Pythinker Security Scan scan complete: {result.files_with_candidates} files, "
            f"{result.candidate_count} candidates (run {result.run_id})"
        )


@app.command()
def process(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    batch_size: int = typer.Option(5, "--batch-size", min=1),
    jobs: int = typer.Option(1, "--jobs", min=1),
    timeout_s: float = typer.Option(180.0, "--timeout-s", min=1.0),
    reinvestigate: bool = typer.Option(False, "--reinvestigate"),
) -> None:
    """Investigate pending candidate files with the active Pythinker model."""
    root = root.resolve()
    pid = _project_id(root, project_id)
    result = asyncio.run(
        process_project(
            project_id=pid,
            data_root=_data_root(root, state_dir),
            llm=_resolve_llm(),
            limit=limit,
            batch_size=batch_size,
            jobs=jobs,
            timeout_s=timeout_s,
            reinvestigate=reinvestigate,
        )
    )
    typer.echo(json.dumps(asdict(result), indent=2))


@app.command()
def revalidate(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
    force: bool = typer.Option(False, "--force"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    timeout_s: float = typer.Option(180.0, "--timeout-s", min=1.0),
) -> None:
    """Re-check stored findings for true/false-positive/fixed verdicts."""
    root = root.resolve()
    result = asyncio.run(
        revalidate_project(
            project_id=_project_id(root, project_id),
            data_root=_data_root(root, state_dir),
            llm=_resolve_llm(),
            force=force,
            limit=limit,
            timeout_s=timeout_s,
        )
    )
    typer.echo(json.dumps(asdict(result), indent=2))


@app.command()
def triage(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
    severity: str = typer.Option("MEDIUM", "--severity"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    timeout_s: float = typer.Option(120.0, "--timeout-s", min=1.0),
) -> None:
    """Classify findings by remediation priority."""
    root = root.resolve()
    result = asyncio.run(
        triage_project(
            project_id=_project_id(root, project_id),
            data_root=_data_root(root, state_dir),
            llm=_resolve_llm(),
            severity=severity,
            limit=limit,
            timeout_s=timeout_s,
        )
    )
    typer.echo(json.dumps(asdict(result), indent=2))


@app.command()
def status(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
) -> None:
    """Show project mirror status."""
    root = root.resolve()
    payload = project_status(_project_id(root, project_id), data_root=_data_root(root, state_dir))
    typer.echo(json.dumps(asdict(payload), indent=2))


@app.command()
def report(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
    write: bool = typer.Option(False, "--write"),
) -> None:
    """Render a Markdown report, optionally writing reports/report.{md,json}."""
    root = root.resolve()
    pid = _project_id(root, project_id)
    data_root = _data_root(root, state_dir)
    if write:
        md_path, json_path = write_report(pid, data_root=data_root)
        typer.echo(json.dumps({"markdown": str(md_path), "json": str(json_path)}, indent=2))
    else:
        typer.echo(render_markdown_report(pid, data_root=data_root))


@app.command()
def metrics(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
) -> None:
    """Print finding counts by severity, slug, and revalidation verdict."""
    root = root.resolve()
    typer.echo(
        json.dumps(
            project_metrics(_project_id(root, project_id), data_root=_data_root(root, state_dir)),
            indent=2,
        )
    )


@app.command(name="export")
def export_cmd(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
    fmt: Literal["json", "md-dir"] = typer.Option("json", "--format"),
    out: Path = typer.Option(Path("security-scan-findings.json"), "--out"),
) -> None:
    """Export findings as JSON or one Markdown file per finding."""
    root = root.resolve()
    written = export_findings(
        _project_id(root, project_id), data_root=_data_root(root, state_dir), fmt=fmt, out=out
    )
    typer.echo(str(written))


@app.command()
def matchers(json_output: bool = typer.Option(False, "--json")) -> None:
    """List migrated matcher slugs."""
    registry = create_default_registry()
    payload = [
        {
            "slug": matcher.slug,
            "description": matcher.description,
            "noiseTier": matcher.noise_tier,
            "filePatterns": matcher.file_patterns,
            "sourceFile": matcher.source_file,
            "patternCount": len(matcher.patterns),
        }
        for matcher in registry.get_all()
    ]
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        for matcher in payload:
            typer.echo(
                f"{matcher['slug']} ({matcher['noiseTier']}, {matcher['patternCount']} patterns)"
            )


@app.command(name="prompt")
def prompt_cmd(
    root: Path = typer.Option(Path.cwd(), "--root", "--repo", exists=True, file_okay=False),
    project_id: str | None = typer.Option(None, "--project-id"),
    state_dir: str = typer.Option(DEFAULT_STATE_DIR, "--state-dir"),
    limit: int = typer.Option(3, "--limit", min=1),
) -> None:
    """Preview the assembled system+user prompt for pending records."""
    root = root.resolve()
    pid = _project_id(root, project_id)
    data_root = _data_root(root, state_dir)
    records = [r for r in load_all_file_records(pid, data_root=data_root) if r.candidates][:limit]
    detected = read_tech_json(pid, data_root=data_root) or detect_tech(root)
    settings = read_project_settings(pid, data_root=data_root)
    assembly = assemble_prompt(
        detected_tags=detected.tags,
        batch_slugs=sorted({c.vuln_slug for record in records for c in record.candidates}),
        batch_languages=batch_languages(records),
        project_info=read_info(pid, data_root=data_root),
        prompt_append=settings.prompt_append,
        records=records,
        project_root=root,
    )
    typer.echo("# SYSTEM\n\n" + assembly.system + "\n\n# USER\n\n" + assembly.user)


def _default_info(project_id: str, tags: list[str]) -> str:
    return f"""# {project_id} security context

- Detected tech: {", ".join(tags) if tags else "unknown"}
- Auth primitives: TODO summarize project-specific auth/permission helpers.
- Trust boundaries: TODO summarize public endpoints, queues, webhooks, jobs, agent tools,
  and external integrations.
- Sensitive data: TODO summarize user, tenant, secret, payment, and privileged resources.
- Project-specific false-positive notes: TODO add framework wrappers or generated paths
  Pythinker Security Scan should ignore.
"""
