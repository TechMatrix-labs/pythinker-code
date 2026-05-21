import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pythinker_review.store.findings_store import FindingsStore
from pythinker_review.store.models import Category, Finding, Location, RunMeta, Severity


def _finding(rid: str = "abc") -> Finding:
    return Finding.model_validate(
        {
            "id": "abcd12345678",
            "rule_id": "sec.x",
            "title": "t",
            "rationale": "r",
            "category": Category.security,
            "severity": Severity.high,
            "location": Location(file="a.py", start_line=1, end_line=1),
            "confidence": 0.9,
            "created_at": datetime(2026, 5, 20, tzinfo=UTC),
            "run_id": rid,
            "pass": "security_review",
        }
    )


def _meta(rid: str = "abc") -> RunMeta:
    now = datetime(2026, 5, 20, tzinfo=UTC)
    return RunMeta(
        id=rid,
        started_at=now,
        finished_at=now,
        status="completed",
        repo_root="/r",
        branch="main",
        head_sha="h",
        base_ref="main",
        base_sha="b",
        source_label="staged",
        passes=["security_review"],
        model="m",
        chunks_total=1,
        chunks_done=1,
        chunks_failed=0,
        findings_count=1,
        allow_partial=False,
        config_hash="0" * 64,
    )


def test_writes_meta_and_findings_and_index(tmp_path: Path) -> None:
    store = FindingsStore(repo_root=tmp_path)
    store.begin(_meta("20260520120000-aaaaaaaa"))
    store.append(_finding("20260520120000-aaaaaaaa"))
    store.finalize(_meta("20260520120000-aaaaaaaa"))
    run_dir = tmp_path / ".pythinker-review" / "runs" / "20260520120000-aaaaaaaa"
    assert (run_dir / "meta.json").exists()
    assert (run_dir / "findings.jsonl").exists()
    index = json.loads((tmp_path / ".pythinker-review" / "index.json").read_text(encoding="utf-8"))
    assert index["runs"][0]["id"] == "20260520120000-aaaaaaaa"


def test_atomic_meta_write_no_tmp_left(tmp_path: Path) -> None:
    store = FindingsStore(repo_root=tmp_path)
    meta = _meta("20260520120000-aaaaaaaa")
    store.begin(meta)
    store.finalize(meta)
    run_dir = tmp_path / ".pythinker-review" / "runs" / "20260520120000-aaaaaaaa"
    assert not any(p.suffix == ".tmp" for p in run_dir.iterdir())


def test_begin_twice_without_finalize_raises(tmp_path: Path) -> None:
    store = FindingsStore(repo_root=tmp_path)
    meta = _meta("20260520120000-aaaaaaaa")
    store.begin(meta)
    with pytest.raises(RuntimeError, match="begin\\(\\) called twice"):
        store.begin(meta)
    store.finalize(meta)
