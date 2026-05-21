import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pythinker_review.cli.review import app


def _setup_branch(repo: Path) -> None:
    subprocess.run(["git", "checkout", "-b", "feature", "-q"], cwd=repo, check=True)
    (repo / "app.py").write_text("def greet(name):\n    return f'hi {name}'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add greet", "-q"], cwd=repo, check=True)


def test_describe_command_outputs_structured_description(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "type": ["Enhancement"],
                "title": "Add greeting helper",
                "description": "- Adds a greeting helper",
                "pr_files": [],
                "changes_diagram": None,
            }
        ),
    )
    result = CliRunner().invoke(
        app, ["describe", "--base", "main", "--format", "json", "--repo", str(repo)]
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["kind"] == "describe"
    assert parsed["result"]["title"] == "Add greeting helper"


def test_improve_alias_outputs_code_suggestions(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    (repo / "best_practices.md").write_text(
        "Prefer explicit empty-name handling.", encoding="utf-8"
    )
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "code_suggestions": [
                    {
                        "relevant_file": "app.py",
                        "language": "python",
                        "existing_code": "return f'hi {name}'",
                        "suggestion_content": "Handle empty names before formatting.",
                        "improved_code": "if not name:\n    return 'hi'\nreturn f'hi {name}'",
                        "one_sentence_summary": "Handle empty names",
                        "label": "Organization best practice",
                        "score": 8,
                        "score_why": "Avoids empty-name output surprises.",
                        "start_line": 2,
                        "end_line": 2,
                    },
                    {
                        "relevant_file": "app.py",
                        "language": "python",
                        "existing_code": "return f'hi {name}'",
                        "suggestion_content": "Rename the helper.",
                        "improved_code": "",
                        "one_sentence_summary": "Rename helper",
                        "label": "style",
                        "score": 2,
                        "score_why": "Low impact.",
                        "start_line": 2,
                        "end_line": 2,
                    },
                ]
            }
        ),
    )
    result = CliRunner().invoke(
        app,
        [
            "improve",
            "--base",
            "main",
            "--format",
            "json",
            "--min-score",
            "5",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["kind"] == "improve"
    suggestions = parsed["result"]["code_suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["relevant_file"] == "app.py"
    assert suggestions[0]["score"] == 8


def test_ask_command_includes_question(tmp_git_repo: Callable[..., Path], monkeypatch) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "question": "what changed?",
                "answer": "The diff adds a greeting helper.",
                "confidence": 0.9,
                "referenced_files": ["app.py"],
                "limitations": None,
            }
        ),
    )
    result = CliRunner().invoke(
        app,
        ["ask", "what", "changed?", "--base", "main", "--format", "json", "--repo", str(repo)],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["kind"] == "ask"
    assert parsed["result"]["referenced_files"] == ["app.py"]


def test_ask_line_command_outputs_selected_line_answer(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "question": "why is this return safe?",
                "file": "app.py",
                "start_line": 2,
                "end_line": 2,
                "side": "RIGHT",
                "answer": "It only formats the provided name and does not execute it.",
                "confidence": 0.8,
                "limitations": None,
            }
        ),
    )
    result = CliRunner().invoke(
        app,
        [
            "ask-line",
            "why",
            "is",
            "this",
            "return",
            "safe?",
            "--file",
            "app.py",
            "--start-line",
            "2",
            "--base",
            "main",
            "--format",
            "json",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["kind"] == "ask-line"
    assert parsed["result"]["file"] == "app.py"


def test_ask_line_command_rejects_mismatched_model_metadata(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "question": "why is this return safe?",
                "file": "app.py",
                "start_line": 1,
                "end_line": 1,
                "side": "RIGHT",
                "answer": "This answer points at the wrong selected line.",
                "confidence": 0.8,
                "limitations": None,
            }
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "ask-line",
            "why",
            "is",
            "this",
            "return",
            "safe?",
            "--file",
            "app.py",
            "--start-line",
            "2",
            "--base",
            "main",
            "--format",
            "json",
            "--repo",
            str(repo),
        ],
    )

    assert result.exit_code == 4
    assert "line-question answer did not echo" in result.stderr


def test_help_docs_command_outputs_doc_answer(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    docs = repo / "docs"
    docs.mkdir()
    (docs / "usage.md").write_text("# Usage\n\nRun `pythinker review diff`.", encoding="utf-8")
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "user_question": "how do I review?",
                "response": "Run `pythinker review diff`.",
                "relevant_sections": [
                    {"file_name": "docs/usage.md", "relevant_section_header_string": "# Usage"}
                ],
                "question_is_relevant": True,
            }
        ),
    )
    result = CliRunner().invoke(
        app,
        [
            "help-docs",
            "how",
            "do",
            "I",
            "review?",
            "--docs-path",
            "docs",
            "--format",
            "json",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["kind"] == "help-docs"
    assert parsed["result"]["relevant_sections"][0]["file_name"] == "docs/usage.md"


def test_labels_changelog_and_docs_commands_output_artifacts(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    labels_file = repo / "labels.yaml"
    labels_file.write_text(
        "labels:\n  - name: API\n    description: Public API changes\n", encoding="utf-8"
    )
    runner = CliRunner()
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps({"labels": ["API"], "rationale": "Adds a helper."}),
    )
    labels_result = runner.invoke(
        app,
        [
            "generate-labels",
            "--base",
            "main",
            "--format",
            "json",
            "--labels-file",
            str(labels_file),
            "--repo",
            str(repo),
        ],
    )
    assert labels_result.exit_code == 0, labels_result.stdout
    assert json.loads(labels_result.stdout)["result"]["labels"] == ["API"]

    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "title": "Add greeting helper",
                "entry": "Adds a small greeting helper.",
                "bullets": ["Added greeting helper."],
                "migration_notes": None,
            }
        ),
    )
    changelog_result = runner.invoke(
        app,
        [
            "update-changelog",
            "--base",
            "main",
            "--format",
            "json",
            "--pr-url",
            "https://example.test/pr/1",
            "--add-pr-link",
            "--repo",
            str(repo),
        ],
    )
    assert changelog_result.exit_code == 0, changelog_result.stdout
    assert json.loads(changelog_result.stdout)["result"]["title"] == "Add greeting helper"

    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "docs_suggestions": [
                    {
                        "relevant_file": "app.py",
                        "target_symbol": "greet",
                        "relevant_line": 1,
                        "doc_placement": "before",
                        "docs_gap": "New helper is undocumented.",
                        "suggested_doc": "Document `greet(name)` in the README.",
                    }
                ]
            }
        ),
    )
    docs_result = runner.invoke(
        app,
        [
            "add-docs",
            "--base",
            "main",
            "--format",
            "json",
            "--docs-style",
            "Google-style docstring",
            "--symbol",
            "greet",
            "--repo",
            str(repo),
        ],
    )
    assert docs_result.exit_code == 0, docs_result.stdout
    docs = json.loads(docs_result.stdout)["result"]["docs_suggestions"]
    assert docs[0]["target_symbol"] == "greet"


def test_artifact_context_file_must_stay_inside_repo(tmp_git_repo: Callable[..., Path]) -> None:
    repo = tmp_git_repo()
    outside = repo.parent / "labels.yaml"
    outside.write_text("labels:\n  - external\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "generate-labels",
            "--labels-file",
            str(outside),
            "--repo",
            str(repo),
        ],
    )

    assert result.exit_code == 2
    assert "escapes repository" in result.stderr


def test_similar_issues_command_searches_local_issue_docs(
    tmp_git_repo: Callable[..., Path],
) -> None:
    repo = tmp_git_repo()
    gitignore = repo / ".gitignore"
    gitignore.write_text("*.pyc\n", encoding="utf-8")
    issues = repo / "issues"
    issues.mkdir()
    (issues / "1.md").write_text(
        "# Greeting fails for empty name\n\nThe greeting helper should handle empty input.",
        encoding="utf-8",
    )
    (issues / "2.md").write_text("# Unrelated docs typo\n\nFix spelling.", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "similar_issue",
            "--issue-text",
            "empty name greeting bug",
            "--issues-dir",
            "issues",
            "--format",
            "json",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["kind"] == "similar-issues"
    assert {match["path"] for match in parsed["result"]["matches"]} >= {"issues/1.md"}
    assert parsed["metadata"]["similarity_backend"] == "lexical"
    assert gitignore.read_text(encoding="utf-8") == "*.pyc\n"
    assert not (repo / ".pythinker-review" / "chroma").exists()


def test_similar_issues_auto_backend_without_persistence_stays_read_only(
    tmp_git_repo: Callable[..., Path],
) -> None:
    repo = tmp_git_repo()
    gitignore = repo / ".gitignore"
    gitignore.write_text("*.pyc\n", encoding="utf-8")
    issues = repo / "issues"
    issues.mkdir()
    (issues / "1.md").write_text(
        "# Greeting fails for empty name\n\nThe greeting helper should handle empty input.",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        [
            "similar-issues",
            "--issue-text",
            "empty name greeting bug",
            "--issues-dir",
            "issues",
            "--backend",
            "auto",
            "--format",
            "json",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["metadata"]["similarity_backend"] in {"lexical", "chroma"}
    if parsed["metadata"]["similarity_backend"] == "chroma":
        assert "chroma_path" not in parsed["metadata"]
    assert gitignore.read_text(encoding="utf-8") == "*.pyc\n"
    assert not (repo / ".pythinker-review" / "chroma").exists()


def test_similar_issues_chroma_without_persistence_stays_read_only(
    tmp_git_repo: Callable[..., Path],
) -> None:
    repo = tmp_git_repo()
    gitignore = repo / ".gitignore"
    gitignore.write_text("*.pyc\n", encoding="utf-8")
    issues = repo / "issues"
    issues.mkdir()
    (issues / "1.md").write_text(
        "# Greeting fails for empty name\n\nThe greeting helper should handle empty input.",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        [
            "similar-issues",
            "--issue-text",
            "empty name greeting bug",
            "--issues-dir",
            "issues",
            "--backend",
            "chroma",
            "--format",
            "json",
            "--repo",
            str(repo),
        ],
    )
    if (
        result.exit_code == 2
        and "chromadb" in result.stderr.lower()
        and "not installed" in result.stderr.lower()
    ):
        pytest.skip("optional ChromaDB backend is not installed")
    assert result.exit_code == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["metadata"]["similarity_backend"] == "chroma"
    assert "chroma_path" not in parsed["metadata"]
    assert gitignore.read_text(encoding="utf-8") == "*.pyc\n"
    assert not (repo / ".pythinker-review" / "chroma").exists()


def test_similar_issues_command_supports_lexical_backend(tmp_git_repo: Callable[..., Path]) -> None:
    repo = tmp_git_repo()
    issues = repo / "issues"
    issues.mkdir()
    (issues / "1.md").write_text(
        "# Greeting fails for empty name\n\nThe greeting helper should handle empty input.",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        [
            "similar-issues",
            "--issue-text",
            "empty name greeting bug",
            "--issues-dir",
            "issues",
            "--backend",
            "lexical",
            "--format",
            "json",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["metadata"]["similarity_backend"] == "lexical"


def test_answer_alias_routes_to_diff_question(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "question": "what changed?",
                "answer": "The diff adds a greeting helper.",
                "confidence": 0.9,
                "referenced_files": ["app.py"],
                "limitations": None,
            }
        ),
    )
    result = CliRunner().invoke(
        app,
        ["answer", "what", "changed?", "--base", "main", "--format", "json", "--repo", str(repo)],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["kind"] == "ask"


def test_artifact_validation_rejects_paths_outside_diff(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "code_suggestions": [
                    {
                        "relevant_file": "other.py",
                        "language": "python",
                        "existing_code": "print('x')",
                        "suggestion_content": "Change unrelated file.",
                        "improved_code": "print('y')",
                        "one_sentence_summary": "Change unrelated",
                        "label": "possible bug",
                        "score": 8,
                    }
                ]
            }
        ),
    )
    result = CliRunner().invoke(
        app, ["improve", "--base", "main", "--format", "json", "--repo", str(repo)]
    )
    assert result.exit_code == 4
    assert "artifact validation failed" in result.stderr


def test_compliance_alias_outputs_checklist_result(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "overall_status": "pass",
                "ticket_summary": "Greeting helper is added.",
                "checks": [],
                "risks": [],
            }
        ),
    )
    result = CliRunner().invoke(
        app,
        [
            "ticket_pr_compliance_check",
            "--base",
            "main",
            "--format",
            "json",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["kind"] == "compliance"


def test_compliance_command_outputs_checklist_result(
    tmp_git_repo: Callable[..., Path], monkeypatch
) -> None:
    repo = tmp_git_repo()
    _setup_branch(repo)
    monkeypatch.setenv(
        "PYTHINKER_REVIEW_FAKE_LLM_RESPONSES",
        json.dumps(
            {
                "overall_status": "pass",
                "ticket_summary": "Greeting helper is added.",
                "checks": [
                    {
                        "title": "Consistent Naming Conventions",
                        "status": "pass",
                        "rationale": "`greet` uses snake_case-compatible naming.",
                        "evidence_files": ["app.py"],
                        "missing_requirements": [],
                    }
                ],
                "risks": [],
            }
        ),
    )
    result = CliRunner().invoke(
        app,
        [
            "compliance",
            "--base",
            "main",
            "--format",
            "json",
            "--ticket-text",
            "Add a greeting helper.",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["kind"] == "compliance"
    assert parsed["result"]["overall_status"] == "pass"
