from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pythinker_review.llm.fake import FakeReviewLLM
from pythinker_review.security_scan.matchers import create_default_registry
from pythinker_review.security_scan.processor import parse_investigate_results, process_project
from pythinker_review.security_scan.prompt import assemble_prompt, batch_languages
from pythinker_review.security_scan.scanner import scan_project
from pythinker_review.security_scan.store import load_all_file_records, read_file_record
from pythinker_review.security_scan.tech import detect_tech


def test_security_scan_registry_ports_all_source_matchers() -> None:
    registry = create_default_registry()
    assert len(registry.get_all()) == 198
    assert registry.get_by_slug("auth-bypass") is not None
    assert registry.get_by_slug("github-workflow-security") is not None
    assert registry.get_by_slug("py-fastapi-route") is not None


def test_security_scan_writes_file_records(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('dependencies = ["fastapi"]\n', encoding="utf-8")
    (repo / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.post('/admin')\n"
        "def admin(user_id: str):\n"
        "    return {'ok': user_id}\n",
        encoding="utf-8",
    )
    data_root = tmp_path / "state" / "data"

    result = scan_project(project_id="repo", root=repo, data_root=data_root)

    assert result.candidate_count > 0
    record = read_file_record("repo", "app.py", data_root=data_root)
    assert record is not None
    assert any(candidate.vuln_slug == "py-fastapi-route" for candidate in record.candidates)


def test_security_scan_prompt_includes_system_policy_and_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('dependencies = ["fastapi"]\n', encoding="utf-8")
    (repo / "app.py").write_text("@app.post('/x')\ndef x(): return {}\n", encoding="utf-8")
    data_root = tmp_path / "state" / "data"
    scan_project(
        project_id="repo", root=repo, data_root=data_root, matcher_slugs=["py-fastapi-route"]
    )
    records = load_all_file_records("repo", data_root=data_root)
    tech = detect_tech(repo)

    assembled = assemble_prompt(
        detected_tags=tech.tags,
        batch_slugs=[c.vuln_slug for r in records for c in r.candidates],
        batch_languages=batch_languages(records),
        project_info="Auth uses Depends(current_user).",
        records=records,
        project_root=repo,
    )

    assert "Pythinker Security Scan" in assembled.system
    assert "FastAPI" in assembled.system
    assert "app.py" in assembled.user


def test_security_scan_parse_adds_empty_results_for_missing_files() -> None:
    payload = '[{"filePath":"a.py","findings":[]}]'

    class R:
        file_path: str

        def __init__(self, file_path: str) -> None:
            self.file_path = file_path

    results = parse_investigate_results(payload, [R("a.py"), R("b.py")])  # type: ignore[arg-type]
    assert {item["filePath"] for item in results} == {"a.py", "b.py"}


def test_security_scan_process_uses_review_llm(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('dependencies = ["fastapi"]\n', encoding="utf-8")
    (repo / "app.py").write_text("@app.post('/x')\ndef x(): return {}\n", encoding="utf-8")
    data_root = tmp_path / "state" / "data"
    scan_project(
        project_id="repo", root=repo, data_root=data_root, matcher_slugs=["py-fastapi-route"]
    )
    response = json.dumps([{"filePath": "app.py", "findings": []}])
    llm = FakeReviewLLM(scripted=[response])

    result = asyncio.run(
        process_project(project_id="repo", data_root=data_root, llm=llm, batch_size=1, jobs=1)
    )

    assert result.analysis_count == 1
    assert result.error_batch_count == 0
    record = read_file_record("repo", "app.py", data_root=data_root)
    assert record is not None
    assert record.status == "analyzed"
