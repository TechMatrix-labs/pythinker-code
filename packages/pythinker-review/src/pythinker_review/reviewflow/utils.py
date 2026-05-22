"""Small stdlib helpers for the Reviewflow workflow port."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from pythinker_review.reviewflow.models import CommandResult


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, parts: list[str], *, length: int = 12) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:length]
    return f"{prefix}_{digest}"


_SAFE_ID_RE = re.compile(r"\A[A-Za-z0-9._-]+\Z")


class InvalidIdentifierError(ValueError):
    """Raised when a workflow identifier could escape its state directory."""


def validate_identifier(value: str, *, label: str) -> str:
    """Reject identifiers that could be interpolated into paths to escape a state dir.

    Workflow IDs (run, feature, finding, patch) are generated as ``<prefix>_<hex>`` or
    a timestamp-hex string. CLI invocation lets the caller pass arbitrary strings, so
    validate before joining onto a directory — ``..`` and path separators are the
    obvious traversal vectors.
    """
    if not value or not _SAFE_ID_RE.fullmatch(value) or value in {".", ".."}:
        raise InvalidIdentifierError(f"invalid {label}: {value!r}")
    return value


def run_id() -> str:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{os.urandom(4).hex()}"


def _timeout_stream_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-20_000:]
    if isinstance(value, str):
        return value[-20_000:]
    return ""


def run_process(
    command: list[str], *, cwd: Path, timeout_s: float = 30.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def run_shell_command(command: str, *, cwd: Path, timeout_s: float = 600.0) -> CommandResult:
    """Run a *trusted* shell command (user-configured) with shell metacharacters.

    Use this only for commands sourced from the user's config (e.g.,
    `ReviewflowConfig.commands.{test, lint, typecheck}`). For commands that
    flow in from model output, use `run_untrusted_command` so shell
    metacharacters are not interpreted.
    """
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S602 - trusted, user-configured command string
            command,
            cwd=cwd,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        exit_code: int | None = proc.returncode
        stdout: str = (proc.stdout or "")[-20_000:]
        stderr: str = (proc.stderr or "")[-20_000:]
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = _timeout_stream_text(exc.stdout)
        stderr = _timeout_stream_text(exc.stderr)
        stderr = f"{stderr}\nTimed out after {timeout_s:g}s".strip()
    return CommandResult(
        command=command,
        cwd=str(cwd),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=round((time.monotonic() - started) * 1000),
    )


_UNSAFE_SHELL_META = re.compile(r"[;&|<>`$()\n\r]|&&|\|\||\$\(")


class UntrustedCommandRejected(RuntimeError):
    """Raised when a model-suggested command fails the safety gate."""


def run_untrusted_command(
    command: str,
    *,
    cwd: Path,
    allowed_binaries: tuple[str, ...] = (),
    timeout_s: float = 600.0,
) -> CommandResult:
    """Run a model-suggested command with shell metacharacters disabled.

    - Shell metacharacters (`;`, `|`, `&`, `&&`, `||`, backticks, `$()`, redirects,
      newlines) cause rejection — the model cannot chain or escape into a shell.
    - `shlex.split` is used to argv-tokenize; `shell=False` runs the binary directly.
    - If `allowed_binaries` is non-empty, the first token must match one of them
      (matched on the basename so `/usr/bin/pytest` and `pytest` both pass when
      `pytest` is in the allow-list).
    """
    if _UNSAFE_SHELL_META.search(command):
        return CommandResult(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            stdout="",
            stderr=(
                "rejected: model-suggested command contains shell metacharacters "
                "(;, |, &, backticks, $(, redirects, etc.)"
            ),
            duration_ms=0,
        )
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        return CommandResult(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            stdout="",
            stderr=f"rejected: model-suggested command failed shlex parse: {exc}",
            duration_ms=0,
        )
    if not argv:
        return CommandResult(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            stdout="",
            stderr="rejected: empty command",
            duration_ms=0,
        )
    if allowed_binaries:
        binary = Path(argv[0]).name
        if binary not in allowed_binaries:
            return CommandResult(
                command=command,
                cwd=str(cwd),
                exit_code=None,
                stdout="",
                stderr=(
                    f"rejected: model-suggested binary '{binary}' is not in the "
                    f"allow-list derived from configured commands: "
                    f"{sorted(allowed_binaries)}"
                ),
                duration_ms=0,
            )
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        exit_code: int | None = proc.returncode
        stdout: str = (proc.stdout or "")[-20_000:]
        stderr: str = (proc.stderr or "")[-20_000:]
    except FileNotFoundError as exc:
        return CommandResult(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            stdout="",
            stderr=f"rejected: binary not found: {exc}",
            duration_ms=0,
        )
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = _timeout_stream_text(exc.stdout)
        stderr = _timeout_stream_text(exc.stderr)
        stderr = f"{stderr}\nTimed out after {timeout_s:g}s".strip()
    return CommandResult(
        command=command,
        cwd=str(cwd),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=round((time.monotonic() - started) * 1000),
    )


def path_matches(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(f"/{normalized}", pattern):
            return True
        if pattern.endswith("/**") and normalized.startswith(pattern[:-3].rstrip("/")):
            return True
    return False


def safe_relative(root: Path, path: Path) -> str | None:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return resolved.relative_to(root_resolved).as_posix()


def read_text_bounded(path: Path, *, limit_chars: int = 20_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= limit_chars:
        return text
    half = limit_chars // 2
    return f"{text[:half]}\n\n... [clipped] ...\n\n{text[-half:]}"


def git_output(root: Path, args: list[str], *, timeout_s: float = 10.0) -> str | None:
    try:
        proc = run_process(["git", *args], cwd=root, timeout_s=timeout_s)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def discover_git(
    root: Path,
) -> tuple[str | None, str | None, str | None, str | None, str | None, bool]:
    git_root = git_output(root, ["rev-parse", "--show-toplevel"])
    head = git_output(root, ["rev-parse", "HEAD"])
    branch = git_output(root, ["branch", "--show-current"])
    default_branch = None
    remote = git_output(root, ["config", "--get", "remote.origin.url"])
    symbolic = git_output(root, ["symbolic-ref", "refs/remotes/origin/HEAD"])
    if symbolic and symbolic.startswith("refs/remotes/origin/"):
        default_branch = symbolic.removeprefix("refs/remotes/origin/")
    dirty = False
    status = git_output(root, ["status", "--porcelain"])
    if status:
        dirty = bool(status.strip())
    return git_root, remote, default_branch, branch, head, dirty


def changed_files_since(root: Path, ref: str) -> set[str]:
    out = git_output(root, ["diff", "--name-only", ref, "--"])
    return set(out.splitlines()) if out else set()


def dirty_files(root: Path) -> set[str]:
    out = git_output(root, ["status", "--porcelain"])
    if not out:
        return set()
    files: set[str] = set()
    for line in out.splitlines():
        value = line[3:].strip()
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        if value:
            files.add(value)
    return files


def source_dirty(root: Path, *, state_dir: Path) -> bool:
    rel_state = state_dir.relative_to(root).as_posix() if state_dir.is_relative_to(root) else ""
    for path in dirty_files(root):
        if rel_state and (path == rel_state or path.startswith(f"{rel_state}/")):
            continue
        return True
    return False


__all__ = [
    "InvalidIdentifierError",
    "UntrustedCommandRejected",
    "changed_files_since",
    "dirty_files",
    "discover_git",
    "git_output",
    "now_iso",
    "path_matches",
    "read_text_bounded",
    "run_id",
    "run_process",
    "run_shell_command",
    "run_untrusted_command",
    "safe_relative",
    "source_dirty",
    "stable_id",
    "validate_identifier",
]
