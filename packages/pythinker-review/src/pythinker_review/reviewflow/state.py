"""JSON state store for the pure-Python Reviewflow workflow."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from pythinker_review.reviewflow.models import (
    FeatureLock,
    FeatureRecord,
    FindingRecord,
    PatchAttempt,
    ProjectRecord,
    ReviewflowConfig,
    RunRecord,
)


@dataclass(frozen=True, slots=True)
class StatePaths:
    state_dir: Path
    config: Path
    project: Path
    features: Path
    findings: Path
    runs: Path
    patches: Path
    reports: Path
    locks: Path


def state_paths(state_dir: Path) -> StatePaths:
    return StatePaths(
        state_dir=state_dir,
        config=state_dir / "config.json",
        project=state_dir / "project.json",
        features=state_dir / "features",
        findings=state_dir / "findings",
        runs=state_dir / "runs",
        patches=state_dir / "patches",
        reports=state_dir / "reports",
        locks=state_dir / "locks",
    )


def ensure_state_dirs(paths: StatePaths) -> None:
    for path in (
        paths.state_dir,
        paths.features,
        paths.findings,
        paths.runs,
        paths.patches,
        paths.reports,
        paths.locks,
    ):
        path.mkdir(parents=True, exist_ok=True)


def read_json[T: BaseModel](path: Path, model: type[T]) -> T:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: BaseModel | dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if isinstance(record, BaseModel):
        text = record.model_dump_json(by_alias=True, indent=2)
    else:
        text = json.dumps(record, indent=2, sort_keys=True)
    tmp.write_text(f"{text}\n", encoding="utf-8")
    os.replace(tmp, path)


def read_config(paths: StatePaths) -> ReviewflowConfig | None:
    if not paths.config.exists():
        return None
    return read_json(paths.config, ReviewflowConfig)


def write_config(paths: StatePaths, config: ReviewflowConfig) -> None:
    write_json(paths.config, config)


def read_project(paths: StatePaths) -> ProjectRecord | None:
    if not paths.project.exists():
        return None
    return read_json(paths.project, ProjectRecord)


def write_project(paths: StatePaths, project: ProjectRecord) -> None:
    write_json(paths.project, project)


def _read_records[T: BaseModel](directory: Path, model: type[T]) -> list[T]:
    if not directory.exists():
        return []
    records: list[T] = []
    for path in sorted(directory.glob("*.json")):
        records.append(read_json(path, model))
    return records


def read_features(paths: StatePaths) -> list[FeatureRecord]:
    return _read_records(paths.features, FeatureRecord)


def read_feature(paths: StatePaths, feature_id: str) -> FeatureRecord | None:
    path = paths.features / f"{feature_id}.json"
    if not path.exists():
        return None
    return read_json(path, FeatureRecord)


def write_feature(paths: StatePaths, feature: FeatureRecord) -> None:
    write_json(paths.features / f"{feature.feature_id}.json", feature)


def read_findings(paths: StatePaths) -> list[FindingRecord]:
    return _read_records(paths.findings, FindingRecord)


def read_finding(paths: StatePaths, finding_id: str) -> FindingRecord | None:
    path = paths.findings / f"{finding_id}.json"
    if not path.exists():
        return None
    return read_json(path, FindingRecord)


def write_finding(paths: StatePaths, finding: FindingRecord) -> None:
    write_json(paths.findings / f"{finding.finding_id}.json", finding)


def read_runs(paths: StatePaths) -> list[RunRecord]:
    return _read_records(paths.runs, RunRecord)


def write_run(paths: StatePaths, run: RunRecord) -> None:
    write_json(paths.runs / f"{run.run_id}.json", run)


def read_patch_attempts(paths: StatePaths) -> list[PatchAttempt]:
    return _read_records(paths.patches, PatchAttempt)


def read_patch_attempt(paths: StatePaths, patch_id: str) -> PatchAttempt | None:
    path = paths.patches / f"{patch_id}.json"
    if not path.exists():
        return None
    return read_json(path, PatchAttempt)


def write_patch_attempt(paths: StatePaths, patch: PatchAttempt) -> None:
    write_json(paths.patches / f"{patch.patch_attempt_id}.json", patch)


def feature_lock_path(paths: StatePaths, feature_id: str) -> Path:
    return paths.locks / f"{feature_id}.json"


def claim_feature(
    paths: StatePaths,
    feature: FeatureRecord,
    lock: FeatureLock | str,
    *,
    allow_non_pending: bool = False,
) -> FeatureRecord:
    paths.locks.mkdir(parents=True, exist_ok=True)
    lock_path = feature_lock_path(paths, feature.feature_id)
    lock_text = lock if isinstance(lock, str) else lock.model_dump_json(by_alias=True, indent=2)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"feature locked: {feature.feature_id}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{lock_text}\n")
        current = read_feature(paths, feature.feature_id)
        if current is None:
            raise RuntimeError(f"feature not found: {feature.feature_id}")
        if current.lock is not None:
            raise RuntimeError(f"feature locked: {feature.feature_id}")
        if not allow_non_pending and current.status not in {"pending", "error"}:
            raise RuntimeError(f"feature not reviewable: {feature.feature_id}")
        if isinstance(lock, FeatureLock):
            current.lock = lock
            current.status = "claimed"
            current.updated_at = lock.locked_at
            write_feature(paths, current)
            return current
        return current
    except Exception:
        release_feature_lock(paths, feature.feature_id)
        raise


def release_feature_lock(paths: StatePaths, feature_id: str) -> None:
    feature_lock_path(paths, feature_id).unlink(missing_ok=True)


def read_feature_lock_ids(paths: StatePaths) -> list[str]:
    if not paths.locks.exists():
        return []
    return sorted(path.stem for path in paths.locks.glob("*.json"))


def clear_feature_locks(paths: StatePaths) -> tuple[int, int]:
    cleared_features = 0
    for feature in read_features(paths):
        if feature.lock is None:
            continue
        feature.status = "pending" if feature.status == "claimed" else feature.status
        feature.lock = None
        write_feature(paths, feature)
        cleared_features += 1
    ids = read_feature_lock_ids(paths)
    for lock_id in ids:
        release_feature_lock(paths, lock_id)
    return cleared_features, len(ids)


__all__ = [
    "StatePaths",
    "claim_feature",
    "clear_feature_locks",
    "ensure_state_dirs",
    "read_config",
    "read_feature",
    "read_feature_lock_ids",
    "read_features",
    "read_finding",
    "read_findings",
    "read_json",
    "read_patch_attempt",
    "read_patch_attempts",
    "read_project",
    "read_runs",
    "release_feature_lock",
    "state_paths",
    "write_config",
    "write_feature",
    "write_finding",
    "write_json",
    "write_patch_attempt",
    "write_project",
    "write_run",
]
