"""Durable Pythinker Security Scan data mirror for Pythinker.

The store keeps one append-only JSON record per source file, but avoids Node globals and
shell-heavy wrappers.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pythinker_review.security_scan.models import (
    FileRecord,
    ProcessorConfig,
    ProjectConfig,
    RunMeta,
    RunStats,
    RunType,
    ScannerConfig,
    SecurityScanProjectSettings,
    now_iso,
)
from pythinker_review.security_scan.paths import (
    data_dir,
    file_record_path,
    files_dir,
    project_config_path,
    reports_dir,
    run_meta_path,
    runs_dir,
)


def generate_run_id(now: datetime | None = None) -> str:
    ts = (now or datetime.now(tz=UTC)).strftime("%Y%m%d%H%M%S")
    return f"{ts}-{secrets.token_hex(8)}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _detect_github_url(root_path: Path) -> str | None:
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=root_path,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root_path,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if remote.returncode != 0 or branch.returncode != 0:
        return None
    url = remote.stdout.strip().removesuffix(".git")
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.removeprefix("git@github.com:")
    if "github.com" not in url:
        return None
    branch_name = branch.stdout.strip()
    return f"{url}/blob/{branch_name}" if branch_name else url


def ensure_project(project_id: str, root_path: Path, *, data_root: Path) -> ProjectConfig:
    root = root_path.resolve()
    path = project_config_path(project_id, data_root=data_root)
    if path.exists():
        config = ProjectConfig.model_validate(_read_json(path))
        changed = False
        if Path(config.root_path).resolve() != root:
            config.root_path = str(root)
            changed = True
        if not config.github_url:
            config.github_url = _detect_github_url(root)
            changed = changed or bool(config.github_url)
        if changed:
            write_project_config(config, data_root=data_root)
        return config
    config = ProjectConfig.model_validate(
        {
            "projectId": project_id,
            "rootPath": str(root),
            "createdAt": now_iso(),
            "githubUrl": _detect_github_url(root),
        }
    )
    write_project_config(config, data_root=data_root)
    return config


def write_project_config(config: ProjectConfig, *, data_root: Path) -> None:
    _write_json(project_config_path(config.project_id, data_root=data_root), _dump(config))


def read_project_config(project_id: str, *, data_root: Path) -> ProjectConfig:
    return ProjectConfig.model_validate(
        _read_json(project_config_path(project_id, data_root=data_root))
    )


def read_project_settings(project_id: str, *, data_root: Path) -> SecurityScanProjectSettings:
    path = data_dir(project_id, data_root=data_root) / "config.json"
    if not path.exists():
        return SecurityScanProjectSettings()
    try:
        raw = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return SecurityScanProjectSettings()
    return SecurityScanProjectSettings.model_validate(raw)


def write_project_settings(
    project_id: str, settings: SecurityScanProjectSettings, *, data_root: Path
) -> None:
    _write_json(data_dir(project_id, data_root=data_root) / "config.json", _dump(settings))


def read_info(project_id: str, *, data_root: Path) -> str:
    path = data_dir(project_id, data_root=data_root) / "INFO.md"
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""


def write_info(project_id: str, markdown: str, *, data_root: Path) -> Path:
    path = data_dir(project_id, data_root=data_root) / "INFO.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    return path


def create_run_meta(
    *,
    project_id: str,
    root_path: Path,
    run_type: RunType,
    scanner_config: dict[str, Any] | None = None,
    processor_config: dict[str, Any] | None = None,
) -> RunMeta:
    scanner = ScannerConfig.model_validate(scanner_config) if scanner_config is not None else None
    processor = (
        ProcessorConfig.model_validate(processor_config) if processor_config is not None else None
    )
    return RunMeta.model_validate(
        {
            "runId": generate_run_id(),
            "projectId": project_id,
            "rootPath": str(root_path.resolve()),
            "createdAt": now_iso(),
            "type": run_type,
            "phase": "running",
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "scannerConfig": scanner,
            "processorConfig": processor,
            "stats": RunStats().model_dump(by_alias=True),
        }
    )


def write_run_meta(meta: RunMeta, *, data_root: Path) -> None:
    _write_json(run_meta_path(meta.project_id, meta.run_id, data_root=data_root), _dump(meta))


def read_run_meta(project_id: str, run_id: str, *, data_root: Path) -> RunMeta:
    return RunMeta.model_validate(
        _read_json(run_meta_path(project_id, run_id, data_root=data_root))
    )


def complete_run(
    project_id: str,
    run_id: str,
    phase: Literal["done", "error"],
    *,
    data_root: Path,
    stats: dict[str, Any] | RunStats | None = None,
) -> RunMeta:
    meta = read_run_meta(project_id, run_id, data_root=data_root)
    meta.phase = phase
    meta.completed_at = now_iso()
    if stats:
        raw = _dump(stats) if isinstance(stats, RunStats) else stats
        merged = meta.stats.model_dump(by_alias=True)
        merged.update({key: value for key, value in raw.items() if value is not None})
        meta.stats = RunStats.model_validate(merged)
    write_run_meta(meta, data_root=data_root)
    return meta


def list_runs(project_id: str, *, data_root: Path) -> list[RunMeta]:
    path = runs_dir(project_id, data_root=data_root)
    if not path.exists():
        return []
    runs: list[RunMeta] = []
    for item in path.glob("*.json"):
        try:
            runs.append(RunMeta.model_validate(_read_json(item)))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(runs, key=lambda run: run.created_at, reverse=True)


def read_file_record(project_id: str, file_path: str, *, data_root: Path) -> FileRecord | None:
    path = file_record_path(project_id, file_path, data_root=data_root)
    if not path.exists():
        return None
    try:
        return FileRecord.model_validate(_read_json(path))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def write_file_record(record: FileRecord, *, data_root: Path) -> Path:
    path = file_record_path(record.project_id, record.file_path, data_root=data_root)
    _write_json(path, _dump(record))
    return path


def load_all_file_records(project_id: str, *, data_root: Path) -> list[FileRecord]:
    root = files_dir(project_id, data_root=data_root)
    if not root.exists():
        return []
    records: list[FileRecord] = []
    for path in root.rglob("*.json"):
        try:
            records.append(FileRecord.model_validate(_read_json(path)))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda record: record.file_path)


def iter_report_paths(project_id: str, *, data_root: Path) -> Iterable[Path]:
    root = reports_dir(project_id, data_root=data_root)
    if not root.exists():
        return ()
    return root.iterdir()


def _dump(model: Any) -> dict[str, Any]:
    if isinstance(model, dict):
        return model
    return model.model_dump(by_alias=True, exclude_none=True)
