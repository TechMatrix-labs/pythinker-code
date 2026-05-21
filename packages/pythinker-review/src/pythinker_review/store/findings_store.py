"""Append-only JSONL store plus atomic meta/index updates."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TextIO

from pythinker_review.store.models import Finding, RunMeta

_STATE_DIR = ".pythinker-review"
_INDEX_LIMIT = 200


class FindingsStore:
    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)
        self.state_dir = self.repo_root / _STATE_DIR
        self._fp: TextIO | None = None

    def _run_dir(self, run_id: str) -> Path:
        return self.state_dir / "runs" / run_id

    def begin(self, meta: RunMeta) -> None:
        if self._fp is not None:
            raise RuntimeError("begin() called twice; call finalize() first")
        run_dir = self._run_dir(meta.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._fp = (run_dir / "findings.jsonl").open("a", encoding="utf-8")
        self._write_meta(meta)

    def append(self, finding: Finding) -> None:
        if self._fp is None:
            raise RuntimeError("begin() must be called before append()")
        self._fp.write(finding.model_dump_json(by_alias=True) + "\n")

    def write_diff(self, run_id: str, patch_text: str) -> None:
        self._run_dir(run_id).mkdir(parents=True, exist_ok=True)
        (self._run_dir(run_id) / "diff.patch").write_text(patch_text, encoding="utf-8")

    def finalize(self, meta: RunMeta) -> None:
        if self._fp is not None:
            self._fp.flush()
            os.fsync(self._fp.fileno())
            self._fp.close()
            self._fp = None
        self._write_meta(meta)
        self._update_index(meta)

    def _write_meta(self, meta: RunMeta) -> None:
        run_dir = self._run_dir(meta.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "meta.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(meta.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _update_index(self, meta: RunMeta) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        idx_path = self.state_dir / "index.json"
        runs: list[dict[str, object]] = []
        if idx_path.exists():
            try:
                parsed = json.loads(idx_path.read_text(encoding="utf-8"))
                raw_runs = parsed.get("runs", [])
                if isinstance(raw_runs, list):
                    runs = [r for r in raw_runs if isinstance(r, dict)]
            except json.JSONDecodeError:
                runs = []
        runs = [r for r in runs if r.get("id") != meta.id]
        runs.insert(
            0,
            {
                "id": meta.id,
                "started_at": meta.started_at.isoformat(),
                "branch": meta.branch,
                "head_sha": meta.head_sha,
                "status": meta.status,
                "findings_count": meta.findings_count,
            },
        )
        tmp = idx_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"runs": runs[:_INDEX_LIMIT]}, indent=2), encoding="utf-8")
        os.replace(tmp, idx_path)
