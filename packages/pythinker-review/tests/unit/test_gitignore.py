from pathlib import Path

from pythinker_review.store.gitignore import ensure_gitignored


def test_appends_when_file_exists_and_missing_entry(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# user\nbuild/\n", encoding="utf-8")
    ensure_gitignored(repo_root=tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".pythinker-review/" in text
    assert "# pythinker-review" in text


def test_idempotent(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# user\nbuild/\n", encoding="utf-8")
    ensure_gitignored(repo_root=tmp_path)
    ensure_gitignored(repo_root=tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").count(".pythinker-review/") == 1


def test_no_op_when_gitignore_missing(tmp_path: Path) -> None:
    ensure_gitignored(repo_root=tmp_path)
    assert not (tmp_path / ".gitignore").exists()


def test_does_not_match_substring_false_positive(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# user\nmypythinker-review/\n", encoding="utf-8")
    added = ensure_gitignored(repo_root=tmp_path)
    assert added is True
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    assert ".pythinker-review/" in lines
    assert "mypythinker-review/" in lines
