from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest
from pythinker_host.path import HostPath

from pythinker_code import scratchpad
from pythinker_code.scratchpad import (
    DEFAULT_SCRATCHPAD_SECTION,
    GitResult,
    ScratchpadStatus,
    TransientScratchpadError,
    append_scratch_event,
    append_scratch_event_sync,
    cleanup_scratch,
    ensure_git_excluded,
    ensure_scratch_created,
    refresh_system_prompt_scratchpad_section,
    render_scratchpad_section,
    scratch_file_exists,
    session_scratch_path,
    with_retries,
)


def _hp(p: Path) -> HostPath:
    # HostPath.unsafe_from_local_path takes a Path, not a str.
    return HostPath.unsafe_from_local_path(p)


@pytest.fixture(autouse=True)
def _reset_verified_work_dirs():
    # The "git verified once" cache is process-global; isolate tests.
    scratchpad._VERIFIED_WORK_DIRS.clear()
    yield
    scratchpad._VERIFIED_WORK_DIRS.clear()


def test_scratch_path_is_under_dot_pythinker(tmp_path: Path):
    assert scratchpad.scratch_path(_hp(tmp_path)) == tmp_path / ".pythinker" / "scratch.md"


def test_scratch_file_exists_detects_existing_file(tmp_path: Path):
    assert scratch_file_exists(_hp(tmp_path)) is False
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text("notes")
    assert scratch_file_exists(_hp(tmp_path)) is True


def test_scratchpad_status_holds_reason():
    status = ScratchpadStatus(
        available=False,
        reason="disabled_git_error",
        git_repo=False,
        tracked=False,
        ignored=False,
    )
    assert status.available is False
    assert status.reason == "disabled_git_error"


async def _instant_sleep(_delay):  # async no-op; must NOT call asyncio.sleep (recursion)
    return None


async def test_with_retries_succeeds_after_one_transient(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    calls = {"n": 0}

    async def op():
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientScratchpadError("locked")
        return "ok"

    assert await with_retries(op) == "ok"
    assert calls["n"] == 2


async def test_with_retries_gives_up_after_budget(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    async def always_transient():
        raise TransientScratchpadError("still locked")

    with pytest.raises(TransientScratchpadError):
        await with_retries(always_transient)


async def test_with_retries_does_not_retry_permanent(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    calls = {"n": 0}

    async def op():
        calls["n"] += 1
        raise PermissionError("EACCES")

    with pytest.raises(PermissionError):
        await with_retries(op)
    assert calls["n"] == 1


class FakeGit:
    """Scriptable git runner: maps an argv prefix to a GitResult."""

    def __init__(self, responses: dict[tuple[str, ...], GitResult]):
        self.responses = responses
        self.calls: list[list[str]] = []

    async def __call__(self, argv: list[str]) -> GitResult:
        self.calls.append(argv)
        for prefix, result in self.responses.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return result
        return GitResult(ok=True, exit_code=1, stdout="")


def _repo_ok_responses(exclude: Path, *, prefix: str = "", ignored_code: int = 0) -> dict:
    return {
        ("rev-parse", "--is-inside-work-tree"): GitResult(True, 0, "true"),
        ("ls-files", "--error-unmatch"): GitResult(True, 1, ""),
        ("rev-parse", "--show-prefix"): GitResult(True, 0, prefix),
        ("rev-parse", "--git-path", "info/exclude"): GitResult(True, 0, str(exclude)),
        ("check-ignore", "-q"): GitResult(True, ignored_code, ""),
    }


async def test_ensure_non_git_is_available(tmp_path):
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.available is True
    assert status.reason == "available_non_git"


async def test_ensure_remote_host_disables(tmp_path, monkeypatch):
    monkeypatch.setattr(scratchpad, "_is_local_host", lambda: False)
    fake = FakeGit({})
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.available is False
    assert status.reason == "disabled_remote_host"


async def test_ensure_git_error_disables(tmp_path):
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(False, -1, "")})
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.reason == "disabled_git_error"


async def test_ensure_ls_files_failure_fails_closed(tmp_path):
    fake = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitResult(True, 0, "true"),
            ("ls-files", "--error-unmatch"): GitResult(False, -1, ""),  # cannot verify
        }
    )
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.available is False
    assert status.reason == "disabled_git_error"


async def test_ensure_tracked_disables(tmp_path):
    fake = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitResult(True, 0, "true"),
            ("ls-files", "--error-unmatch"): GitResult(True, 0, ".pythinker/scratch.md"),
        }
    )
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.reason == "disabled_tracked"
    assert status.tracked is True


async def test_ensure_ls_files_fatal_exit_fails_closed(tmp_path):
    fake = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitResult(True, 0, "true"),
            ("ls-files", "--error-unmatch"): GitResult(True, 128, "fatal"),
        }
    )
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.reason == "disabled_git_error"


async def test_ensure_appends_and_verifies(tmp_path):
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text("# existing\n")
    fake = FakeGit(_repo_ok_responses(exclude))
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.available is True
    assert status.reason == "available_git_ignored"
    text = exclude.read_text()
    assert ".pythinker/scratch.md" in text
    assert ".pythinker/scratch/*.md" in text


async def test_ensure_subdir_uses_prefix(tmp_path):
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text("")
    fake = FakeGit(_repo_ok_responses(exclude, prefix="sub/dir/"))
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.available is True
    text = exclude.read_text()
    assert "sub/dir/.pythinker/scratch.md" in text
    assert "sub/dir/.pythinker/scratch/*.md" in text


async def test_ensure_idempotent(tmp_path):
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text(".pythinker/scratch.md\n")
    fake = FakeGit(_repo_ok_responses(exclude))
    await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert exclude.read_text().count(".pythinker/scratch.md") == 1


async def test_ensure_concurrent_calls_do_not_duplicate_exclude_line(tmp_path):
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text("")
    fake = FakeGit(_repo_ok_responses(exclude))
    await asyncio.gather(*(ensure_git_excluded(_hp(tmp_path), git_runner=fake) for _ in range(5)))
    assert exclude.read_text().count(".pythinker/scratch.md") == 1


async def test_ensure_not_ignored_disables(tmp_path):
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text("")
    fake = FakeGit(_repo_ok_responses(exclude, ignored_code=1))
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.reason == "disabled_not_ignored"


async def test_ensure_check_ignore_fatal_exit_fails_closed(tmp_path):
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text("")
    fake = FakeGit(_repo_ok_responses(exclude, ignored_code=128))
    status = await ensure_git_excluded(_hp(tmp_path), git_runner=fake)
    assert status.reason == "disabled_git_error"


requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@requires_git
async def test_ensure_real_repo_root(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    status = await ensure_git_excluded(_hp(tmp_path))  # default runner
    assert status.available is True
    assert status.reason == "available_git_ignored"
    exclude = tmp_path / ".git" / "info" / "exclude"
    text = exclude.read_text()
    assert ".pythinker/scratch.md" in text
    assert ".pythinker/scratch/*.md" in text
    await ensure_git_excluded(_hp(tmp_path))  # idempotent
    text = exclude.read_text()
    assert text.count(".pythinker/scratch.md") == 1
    assert text.count(".pythinker/scratch/*.md") == 1


@requires_git
async def test_ensure_real_repo_nested_subdir(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    sub = tmp_path / "pkg" / "app"
    sub.mkdir(parents=True)
    status = await ensure_git_excluded(_hp(sub))  # work_dir is a subdirectory
    assert status.available is True
    exclude = tmp_path / ".git" / "info" / "exclude"
    text = exclude.read_text()
    assert "pkg/app/.pythinker/scratch.md" in text
    assert "pkg/app/.pythinker/scratch/*.md" in text
    # check-ignore from the subdir agrees both scratch paths are ignored
    r = subprocess.run(["git", "-C", str(sub), "check-ignore", "-q", "--", ".pythinker/scratch.md"])
    assert r.returncode == 0
    r = subprocess.run(
        ["git", "-C", str(sub), "check-ignore", "-q", "--", ".pythinker/scratch/session.md"]
    )
    assert r.returncode == 0


skip_on_windows = pytest.mark.skipif(
    platform.system() == "Windows", reason="symlink requires privileges on Windows"
)


async def test_cleanup_removes_untracked_file(tmp_path):
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text("notes")
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    result = await cleanup_scratch(_hp(tmp_path), git_runner=fake)
    assert result.deleted is True
    assert not p.exists()
    assert (tmp_path / ".pythinker").exists()  # dir preserved


async def test_cleanup_missing_is_noop(tmp_path):
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    result = await cleanup_scratch(_hp(tmp_path), git_runner=fake)
    assert result.deleted is False
    assert result.reason == "missing"


async def test_cleanup_skips_tracked_file(tmp_path):
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text("notes")
    fake = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitResult(True, 0, "true"),
            ("ls-files", "--error-unmatch"): GitResult(True, 0, scratchpad.SCRATCH_REL_PATH),
        }
    )
    result = await cleanup_scratch(_hp(tmp_path), git_runner=fake)
    assert result.deleted is False
    assert result.reason == "tracked"
    assert p.exists()


async def test_cleanup_unverifiable_git_skips(tmp_path):
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text("notes")
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(False, -1, "")})
    result = await cleanup_scratch(_hp(tmp_path), git_runner=fake)
    assert result.deleted is False
    assert result.reason == "unverified"
    assert p.exists()


async def test_cleanup_ls_files_fatal_exit_skips(tmp_path):
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text("notes")
    fake = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitResult(True, 0, "true"),
            ("ls-files", "--error-unmatch"): GitResult(True, 128, "fatal"),
        }
    )
    result = await cleanup_scratch(_hp(tmp_path), git_runner=fake)
    assert result.deleted is False
    assert result.reason == "unverified"
    assert p.exists()


async def test_cleanup_remote_host_skips(tmp_path, monkeypatch):
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text("notes")
    monkeypatch.setattr(scratchpad, "_is_local_host", lambda: False)
    fake = FakeGit({})
    result = await cleanup_scratch(_hp(tmp_path), git_runner=fake)
    assert result.deleted is False
    assert result.reason == "remote_host"
    assert p.exists()


async def test_cleanup_skips_directory(tmp_path):
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.mkdir(parents=True)  # scratch path is a directory
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    result = await cleanup_scratch(_hp(tmp_path), git_runner=fake)
    assert result.deleted is False
    assert result.reason == "not_a_file"
    assert p.is_dir()


async def test_ensure_scratch_created_creates_non_git_file(tmp_path):
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    result = await ensure_scratch_created(_hp(tmp_path), git_runner=fake)
    p = scratchpad.scratch_path(_hp(tmp_path))
    assert result.created is True
    assert result.reason == "created"
    assert p.is_file()
    assert "Pythinker Scratchpad" in p.read_text(encoding="utf-8")


async def test_ensure_scratch_created_never_overwrites_existing_file(tmp_path):
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text("custom notes", encoding="utf-8")
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    result = await ensure_scratch_created(_hp(tmp_path), git_runner=fake)
    assert result.created is False
    assert result.reason == "already_exists"
    assert p.read_text(encoding="utf-8") == "custom notes"


async def test_ensure_scratch_created_respects_git_unavailable_status(tmp_path):
    fake = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitResult(True, 0, "true"),
            ("ls-files", "--error-unmatch"): GitResult(True, 0, scratchpad.SCRATCH_REL_PATH),
        }
    )
    result = await ensure_scratch_created(_hp(tmp_path), git_runner=fake)
    assert result.created is False
    assert result.reason == "disabled_tracked"
    assert not scratchpad.scratch_path(_hp(tmp_path)).exists()


async def test_append_scratch_event_creates_compact_session_log(tmp_path):
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    result = await append_scratch_event(
        _hp(tmp_path),
        session_id="abcdef1234567890",
        session_title="Deep Code Scan",
        labels=["workspace:repo", "scope:security"],
        title="agent started",
        details=["type: explore", "task: agent-123"],
        git_runner=fake,
    )

    assert result.appended is True
    p = session_scratch_path(
        _hp(tmp_path), session_id="abcdef1234567890", session_title="Deep Code Scan"
    )
    assert p.name == "abcdef123456-deep-code-scan.md"
    text = p.read_text(encoding="utf-8")
    assert "## Session abcdef123456" in text
    assert "labels: session:abcdef123456 | workspace:repo | scope:security" in text
    assert "<!-- pythinker-session:abcdef1234567890 -->" in text
    assert "— agent started" in text
    assert "  - type: explore" in text
    assert "  - task: agent-123" in text


async def test_append_scratch_event_does_not_duplicate_session_heading(tmp_path):
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    await append_scratch_event(
        _hp(tmp_path),
        session_id="test-session",
        title="first",
        git_runner=fake,
    )
    await append_scratch_event(
        _hp(tmp_path),
        session_id="test-session",
        title="second",
        git_runner=fake,
    )

    text = session_scratch_path(_hp(tmp_path), session_id="test-session").read_text(
        encoding="utf-8"
    )
    assert text.count("<!-- pythinker-session:test-session -->") == 1
    assert "— first" in text
    assert "— second" in text


def test_append_scratch_event_sync_missing_is_noop(tmp_path):
    result = append_scratch_event_sync(_hp(tmp_path), title="missing")
    assert result.appended is False
    assert result.reason == "missing"


async def test_append_verifies_git_once_per_session(tmp_path):
    # Regression guard: repeated journal writes must not re-run git verification
    # (rev-parse/ls-files/check-ignore) on every call.
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    await append_scratch_event(_hp(tmp_path), session_id="sid", title="first", git_runner=fake)
    calls_after_first = len(fake.calls)
    assert calls_after_first > 0
    await append_scratch_event(_hp(tmp_path), session_id="sid", title="second", git_runner=fake)
    await append_scratch_event(_hp(tmp_path), session_id="sid", title="third", git_runner=fake)
    assert len(fake.calls) == calls_after_first  # no further git invocations
    text = session_scratch_path(_hp(tmp_path), session_id="sid").read_text(encoding="utf-8")
    assert "— first" in text
    assert "— second" in text
    assert "— third" in text


async def test_append_failed_verification_is_not_cached(tmp_path):
    # A transient/failed verification must not poison the session; a later call retries.
    failing = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(False, -1, "")})
    bad = await append_scratch_event(_hp(tmp_path), session_id="sid", title="x", git_runner=failing)
    assert bad.appended is False
    healthy = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    good = await append_scratch_event(
        _hp(tmp_path), session_id="sid", title="y", git_runner=healthy
    )
    assert good.appended is True


async def test_append_caps_file_growth_by_dropping_oldest_sessions(tmp_path):
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    p = session_scratch_path(_hp(tmp_path), session_id="keep")
    p.parent.mkdir(parents=True, exist_ok=True)
    # Seed an oversized file: an old session block padded past the cap, then a marker block.
    padding = "- 2026-01-01 00:00 — old event\n" * 6000
    p.write_text(
        f"# Pythinker Scratchpad\n\n## Session oldsession\n"
        f"<!-- pythinker-session:oldsession -->\nlabels: session:oldsession\n{padding}",
        encoding="utf-8",
    )
    assert len(p.read_text(encoding="utf-8").encode("utf-8")) > scratchpad._MAX_SCRATCH_BYTES
    await append_scratch_event(_hp(tmp_path), session_id="keep", title="newest", git_runner=fake)
    text = p.read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) <= scratchpad._MAX_SCRATCH_BYTES
    assert text.startswith("# Pythinker Scratchpad")
    assert "## Session keep" in text  # newest session retained
    assert "— newest" in text
    assert "oldsession" not in text  # oldest block dropped


@skip_on_windows
async def test_cleanup_symlink_unlinks_link_not_target(tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("keep me")
    p = scratchpad.scratch_path(_hp(tmp_path))
    p.parent.mkdir(parents=True)
    os.symlink(target, p)
    fake = FakeGit({("rev-parse", "--is-inside-work-tree"): GitResult(True, 128, "")})
    result = await cleanup_scratch(_hp(tmp_path), git_runner=fake)
    assert result.deleted is True
    assert not p.exists()
    assert target.read_text() == "keep me"


_AVAILABLE = ScratchpadStatus(True, "available_git_ignored", True, False, True)
_UNAVAILABLE = ScratchpadStatus(False, "disabled_tracked", True, True, False)


def test_render_available_matches_default_constant():
    text = render_scratchpad_section(_AVAILABLE)
    assert text == DEFAULT_SCRATCHPAD_SECTION
    assert "minimal session memory" in text
    assert ".pythinker/scratch/*.md" in text
    assert "SetTodoList" in text
    assert "full logs" in text
    assert "Retain session scratchpads" in text


def test_render_unavailable_is_the_guard_line():
    text = render_scratchpad_section(_UNAVAILABLE)
    assert "do not create or edit `.pythinker/scratch.md`" in text
    assert "`.pythinker/scratch/*.md`" in text
    assert "If you are the root agent" not in text


def test_render_available_with_existing_scratchpad_adds_recovery_instruction():
    text = render_scratchpad_section(_AVAILABLE, scratch_exists=True)
    assert DEFAULT_SCRATCHPAD_SECTION in text
    assert "prior scratchpad history exists" in text
    assert "fast-skim labels" in text


def test_refresh_replaces_existing_marked_scratchpad_block():
    prompt = (
        "Before\n"
        "<!-- PYTHINKER_SCRATCHPAD_SECTION_START -->\nold\n"
        "<!-- PYTHINKER_SCRATCHPAD_SECTION_END -->\n"
        "After"
    )
    refreshed = refresh_system_prompt_scratchpad_section(prompt, "new")
    assert "old" not in refreshed
    assert "new" in refreshed
    assert refreshed.count("PYTHINKER_SCRATCHPAD_SECTION_START") == 1


def test_refresh_inserts_block_into_legacy_prompt():
    prompt = "Intro\n\nBefore every tool response, batch independent work."
    refreshed = refresh_system_prompt_scratchpad_section(prompt, "guard")
    assert "guard" in refreshed
    assert refreshed.index("guard") < refreshed.index("Before every tool response")
