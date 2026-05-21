from __future__ import annotations

import pytest

from pythinker_review.reviewflow.mapping import detect_project, map_features
from pythinker_review.reviewflow.models import (
    EvidenceRef,
    FeatureLock,
    FeatureRecord,
    FindingRecord,
    PatchAttempt,
    ReviewflowConfig,
    RunRecord,
    derive_finding_triage,
)
from pythinker_review.reviewflow.reporting import next_finding, render_report
from pythinker_review.reviewflow.state import (
    claim_feature,
    ensure_state_dirs,
    read_feature,
    read_feature_lock_ids,
    read_finding,
    release_feature_lock,
    state_paths,
    write_feature,
    write_finding,
    write_patch_attempt,
    write_run,
)
from pythinker_review.reviewflow.utils import now_iso, stable_id


def test_reviewflow_models_preserve_camel_case_aliases() -> None:
    parsed = EvidenceRef.model_validate(
        {"path": "src/app.py", "startLine": 3, "endLine": 4, "quote": "return user"}
    )

    dumped = parsed.model_dump(by_alias=True)

    assert parsed.start_line == 3
    assert dumped["startLine"] == 3
    assert dumped["endLine"] == 4
    assert derive_finding_triage("security", "high") == "confirmed-bug"


def test_reviewflow_mapping_detects_project_and_features(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text(
        "import subprocess\n\ndef run(request):\n    return subprocess.run(request.args['cmd'])\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_run(): pass\n", encoding="utf-8")

    config = ReviewflowConfig()
    project = detect_project(root, config)
    features, stats = map_features(root, project, config, existing=[])

    assert "python" in project.detected.languages
    assert project.detected.commands.test == "pytest"
    assert stats["created"] >= 2
    src_feature = next(feature for feature in features if feature.title == "Src")
    assert [ref.path for ref in src_feature.owned_files] == ["src/app.py"]
    assert "process-exec" in src_feature.trust_boundaries
    config_feature = next(
        feature for feature in features if feature.title == "Project configuration"
    )
    assert [ref.path for ref in config_feature.owned_files] == ["pyproject.toml"]


def test_reviewflow_state_round_trip_and_locking(tmp_path) -> None:
    paths = state_paths(tmp_path / ".pythinker-review-flow")
    ensure_state_dirs(paths)
    now = now_iso()
    feature = FeatureRecord(
        feature_id=stable_id("feat", ["src/app.py"]),
        title="Src",
        summary="Source feature",
        kind="library",
        owned_files=[],
        created_at=now,
        updated_at=now,
    )
    finding = FindingRecord(
        finding_id=stable_id("finding", ["src/app.py", "3"]),
        feature_id=feature.feature_id,
        title="Unsafe command execution",
        category="security",
        severity="high",
        confidence="high",
        triage="confirmed-bug",
        evidence=[EvidenceRef(path="src/app.py", start_line=3, end_line=3)],
        reasoning="User input reaches subprocess.",
        recommendation="Avoid shelling out with user input.",
        signature="sig",
        created_by_run_id="run_1",
        created_at=now,
        updated_at=now,
    )

    write_feature(paths, feature)
    write_finding(paths, finding)
    claim_feature(paths, feature, '{"lockedByRunId":"run_1"}')

    assert read_feature(paths, feature.feature_id) == feature
    assert read_finding(paths, finding.finding_id) == finding
    assert read_feature_lock_ids(paths) == [feature.feature_id]
    with pytest.raises(RuntimeError, match="feature locked"):
        claim_feature(paths, feature, "{}")
    release_feature_lock(paths, feature.feature_id)
    assert read_feature_lock_ids(paths) == []


def test_reviewflow_state_models_match_reviewflow_json_shape(tmp_path) -> None:
    paths = state_paths(tmp_path / ".pythinker-review-flow")
    ensure_state_dirs(paths)
    now = now_iso()
    run = RunRecord(
        run_id="20260520120000-deadbeef",
        command="review",
        args=["--limit", "1"],
        root_path=str(tmp_path),
        head_sha="abc",
        started_at=now,
        status="running",
    )
    patch = PatchAttempt(
        patch_attempt_id="pat_1",
        finding_ids=["fnd_1"],
        feature_ids=["feat_1"],
        status="validated",
        plan="Fix it",
        created_at=now,
        updated_at=now,
    )

    write_run(paths, run)
    write_patch_attempt(paths, patch)

    run_json = (paths.runs / "20260520120000-deadbeef.json").read_text(encoding="utf-8")
    patch_json = (paths.patches / "pat_1.json").read_text(encoding="utf-8")
    assert '"command": "review"' in run_json
    assert '"claimedFeatureIds"' in run_json
    assert '"patchAttemptId": "pat_1"' in patch_json
    assert '"status": "validated"' in patch_json


def test_clean_locks_clears_feature_and_lock_file(tmp_path) -> None:
    from pythinker_review.reviewflow.state import clear_feature_locks

    paths = state_paths(tmp_path / ".pythinker-review-flow")
    ensure_state_dirs(paths)
    now = now_iso()
    feature = FeatureRecord(
        feature_id="feat_locked",
        title="Locked",
        summary="Locked feature",
        created_at=now,
        updated_at=now,
    )
    write_feature(paths, feature)
    claim_feature(
        paths,
        feature,
        FeatureLock(locked_by_run_id="run_1", locked_at=now, hostname="host", pid=1),
        allow_non_pending=True,
    )

    cleared_features, cleared_files = clear_feature_locks(paths)

    unlocked = read_feature(paths, feature.feature_id)
    assert cleared_features == 1
    assert cleared_files == 1
    assert unlocked is not None
    assert unlocked.lock is None
    assert unlocked.status == "pending"
    assert read_feature_lock_ids(paths) == []


def test_reviewflow_report_ranks_next_open_finding() -> None:
    now = now_iso()
    feature = FeatureRecord(
        feature_id="feat_src",
        title="Source",
        summary="Source feature",
        created_at=now,
        updated_at=now,
    )
    low = FindingRecord(
        finding_id="finding_low",
        feature_id=feature.feature_id,
        title="Low issue",
        category="maintainability",
        severity="low",
        confidence="high",
        triage="risk",
        evidence=[],
        reasoning="Minor cleanup.",
        recommendation="Clean up.",
        signature="low",
        created_by_run_id="run_1",
        created_at=now,
        updated_at=now,
    )
    high = FindingRecord(
        finding_id="finding_high",
        feature_id=feature.feature_id,
        title="High issue",
        category="security",
        severity="high",
        confidence="medium",
        triage="risk",
        evidence=[EvidenceRef(path="src/app.py", start_line=1, end_line=1)],
        reasoning="Dangerous flow.",
        recommendation="Fix the flow.",
        signature="high",
        created_by_run_id="run_1",
        created_at=now,
        updated_at=now,
    )

    assert next_finding([low, high]) == high
    report = render_report([low, high], [feature])
    assert "# Pythinker Reviewflow Report" in report
    assert "HIGH · High issue" in report
    assert "low: 1" in report
