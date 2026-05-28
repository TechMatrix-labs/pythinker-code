"""Resolve the diff to review, plus base/head SHAs and changed files."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

_GIT_TIMEOUT_S = 20.0


class DiffMode(StrEnum):
    base = "base"
    staged = "staged"
    working_tree = "working_tree"
    range = "range"


class PreflightError(RuntimeError):
    """Recoverable, user-actionable git/setup issue."""


class EmptyDiffError(PreflightError):
    """The resolved diff is empty after filters."""


@dataclass(frozen=True, slots=True)
class ResolvedDiff:
    patch_text: str
    base_sha: str
    head_sha: str
    base_ref: str
    source_label: str
    changed_files: tuple[str, ...] = field(default_factory=tuple)


def _git(repo: Path, *args: str, check: bool = True) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise PreflightError("git executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise PreflightError(f"git {args[0]} timed out after {_GIT_TIMEOUT_S}s") from exc
    if check and proc.returncode != 0:
        raise PreflightError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def _ensure_repo(repo: Path) -> None:
    try:
        _git(repo, "rev-parse", "--is-inside-work-tree")
    except PreflightError as exc:
        raise PreflightError(f"{repo} is not a git repository") from exc


def _resolve_ref(repo: Path, ref: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise PreflightError("git executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise PreflightError(f"git rev-parse timed out after {_GIT_TIMEOUT_S}s") from exc
    if proc.returncode != 0:
        raise PreflightError(f"base ref '{ref}' is not resolvable in {repo}")
    return proc.stdout.strip()


def resolve_diff(
    repo: Path,
    *,
    mode: DiffMode,
    base_ref: str = "origin/main",
    fallback_refs: tuple[str, ...] = ("main", "master"),
    rev_range: str | None = None,
    unified: int = 10,
) -> ResolvedDiff:
    repo = repo.resolve()
    _ensure_repo(repo)
    head_sha = _resolve_ref(repo, "HEAD")

    if mode is DiffMode.range:
        if not rev_range or ".." not in rev_range:
            raise PreflightError("--range requires A..B")
        start_ref, _sep, end_ref = rev_range.partition("..")
        base_sha = _resolve_ref(repo, start_ref)
        range_head_sha = _resolve_ref(repo, end_ref) if end_ref else head_sha
        patch = _git(repo, "diff", f"--unified={unified}", rev_range)
        files = _changed_files_from_diff(patch)
        if not files:
            raise EmptyDiffError("range diff is empty")
        return ResolvedDiff(
            patch, base_sha, range_head_sha, start_ref, f"git-range:{rev_range}", files
        )

    if mode is DiffMode.staged:
        patch = _git(repo, "diff", "--cached", f"--unified={unified}")
        files = _changed_files_from_diff(patch)
        if not files:
            raise EmptyDiffError("no staged changes")
        return ResolvedDiff(patch, head_sha, head_sha, "HEAD", "staged", files)

    if mode is DiffMode.working_tree:
        tracked = _git(repo, "diff", f"--unified={unified}", "HEAD")
        untracked = _git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
        synthetic = "".join(_synthesize_added_file_patch(repo, p) for p in untracked if p)
        patch = tracked + synthetic
        files = _changed_files_from_diff(patch)
        if not files:
            raise EmptyDiffError("no working-tree changes")
        return ResolvedDiff(patch, head_sha, head_sha, "HEAD", "working-tree", files)

    candidates = (base_ref, *fallback_refs)
    chosen_ref: str | None = None
    last_err: PreflightError | None = None
    for ref in candidates:
        try:
            _resolve_ref(repo, ref)
            chosen_ref = ref
            break
        except PreflightError as exc:
            last_err = exc
    if chosen_ref is None:
        raise last_err or PreflightError("no resolvable base ref")
    merge_base = _git(repo, "merge-base", "HEAD", chosen_ref).strip()
    if not merge_base:
        raise PreflightError(f"no merge-base between HEAD and {chosen_ref}")
    patch = _git(repo, "diff", f"--unified={unified}", f"{merge_base}..HEAD")
    files = _changed_files_from_diff(patch)
    if not files:
        raise EmptyDiffError(f"no changes between {chosen_ref} and HEAD")
    return ResolvedDiff(patch, merge_base, head_sha, chosen_ref, f"git-diff:{chosen_ref}", files)


def _changed_files_from_diff(patch: str) -> tuple[str, ...]:
    files: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            path = line[len("+++ b/") :].strip()
            if path != "/dev/null":
                files.append(path)
    return tuple(dict.fromkeys(files))


def _synthesize_added_file_patch(repo: Path, rel_path: str) -> str:
    full = repo / rel_path
    try:
        text = full.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""
    lines = text.splitlines(keepends=True)
    body = "".join(f"+{line}" for line in lines)
    header = (
        f"diff --git a/{rel_path} b/{rel_path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{rel_path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
    )
    return header + body
