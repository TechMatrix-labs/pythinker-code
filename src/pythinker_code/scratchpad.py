"""Private per-session scratchpad: git-safe creation and compact history.

The agent owns the semantic notes; this module owns deterministic session file
creation, git-ignore safety, compact milestone appends, and title-based naming.
Scratchpads are retained as history for future context recall unless the user
explicitly asks for cleanup.

Local-host only in v1: file operations use ``pathlib``/``os`` directly, so the
scratchpad is disabled when the active host is not a ``LocalHost``.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
from collections.abc import Awaitable, Callable, Generator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TextIO

import pythinker_host
from pythinker_host import HostProcess, LocalHost
from pythinker_host.path import HostPath

from pythinker_code.utils.logging import logger

SCRATCH_REL_PATH = ".pythinker/scratch.md"
SESSION_SCRATCH_DIR_REL_PATH = ".pythinker/scratch"
SESSION_SCRATCH_IGNORE_PATTERN = f"{SESSION_SCRATCH_DIR_REL_PATH}/*.md"
_SESSION_SCRATCH_IGNORE_SAMPLE = f"{SESSION_SCRATCH_DIR_REL_PATH}/session.md"

StatusReason = Literal[
    "available_non_git",
    "available_git_ignored",
    "disabled_tracked",
    "disabled_not_ignored",
    "disabled_git_error",
    "disabled_path_error",
    "disabled_remote_host",
]

CleanupReason = Literal[
    "deleted",
    "error",
    "locked",
    "missing",
    "not_a_file",
    "remote_host",
    "tracked",
    "unlinked_symlink",
    "unverified",
]

CreationReason = Literal[
    "created",
    "already_exists",
    "available_non_git",
    "available_git_ignored",
    "disabled_tracked",
    "disabled_not_ignored",
    "disabled_git_error",
    "disabled_path_error",
    "disabled_remote_host",
    "not_a_file",
    "unsafe_parent",
    "error",
]


def scratch_path(work_dir: HostPath) -> Path:
    """Absolute local path to the legacy scratch file inside the working directory."""
    return Path(str(work_dir)) / ".pythinker" / "scratch.md"


def scratch_dir(work_dir: HostPath) -> Path:
    """Directory for named per-session scratch files."""
    return Path(str(work_dir)) / ".pythinker" / "scratch"


def _slugify_session_title(title: str | None) -> str:
    if not title:
        return "session"
    chars: list[str] = []
    prev_dash = False
    for char in title.lower():
        if char.isalnum():
            chars.append(char)
            prev_dash = False
        elif not prev_dash:
            chars.append("-")
            prev_dash = True
    slug = "".join(chars).strip("-")
    return (slug or "session")[:48].strip("-") or "session"


def _session_short_id(session_id: str) -> str:
    text = "".join(char if char.isalnum() else "-" for char in str(session_id).lower())
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-")[:12].strip("-") or "session"


def session_scratch_path(
    work_dir: HostPath,
    *,
    session_id: str | None = None,
    session_title: str | None = None,
) -> Path:
    """Named per-session scratch path, falling back to the legacy path if no session ID exists."""
    if not session_id:
        return scratch_path(work_dir)
    short_id = _session_short_id(session_id)
    directory = scratch_dir(work_dir)
    try:
        existing = sorted(directory.glob(f"{short_id}-*.md")) if directory.is_dir() else []
        if existing:
            return existing[0]
    except Exception:
        logger.debug("scratchpad session path lookup failed")
    return directory / f"{short_id}-{_slugify_session_title(session_title)}.md"


def rename_session_scratch(
    work_dir: HostPath,
    *,
    session_id: str,
    session_title: str,
) -> None:
    """Best-effort rename from placeholder slug to a title-derived per-session filename."""
    if not _is_local_host():
        return
    current = session_scratch_path(work_dir, session_id=session_id)
    desired = scratch_dir(work_dir) / (
        f"{_session_short_id(session_id)}-{_slugify_session_title(session_title)}.md"
    )
    try:
        if current == desired or not current.is_file() or current.is_symlink() or desired.exists():
            return
        desired.parent.mkdir(parents=True, exist_ok=True)
        current.rename(desired)
    except Exception:
        logger.debug("scratchpad session rename failed")


def scratch_file_exists(work_dir: HostPath) -> bool:
    """Whether a local scratch file/symlink exists. Never raises."""
    if not _is_local_host():
        return False
    try:
        legacy = scratch_path(work_dir)
        if legacy.exists() or legacy.is_symlink():
            return True
        directory = scratch_dir(work_dir)
        return directory.is_dir() and any(directory.glob("*.md"))
    except Exception:
        logger.debug("scratchpad existence check failed")
        return False


def _is_local_host() -> bool:
    try:
        return isinstance(pythinker_host.get_current_host(), LocalHost)
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class GitResult:
    """Result of one git invocation. ``ok`` is False on timeout/missing exe."""

    ok: bool
    exit_code: int
    stdout: str


# A git runner takes argv (without the leading "git") and returns a GitResult.
GitRunner = Callable[[list[str]], Awaitable[GitResult]]


@dataclass(frozen=True, slots=True)
class ScratchpadStatus:
    available: bool
    reason: StatusReason
    git_repo: bool
    tracked: bool
    ignored: bool


@dataclass(frozen=True, slots=True)
class ScratchpadCleanupResult:
    deleted: bool
    reason: CleanupReason


@dataclass(frozen=True, slots=True)
class ScratchpadCreationResult:
    created: bool
    reason: CreationReason


@dataclass(frozen=True, slots=True)
class ScratchpadAppendResult:
    appended: bool
    reason: str


_BACKOFFS = (0.05, 0.20)  # delays between attempts 1->2 and 2->3
_TRANSIENT_ERRNOS = frozenset({errno.EINTR, errno.EAGAIN, errno.EBUSY, errno.ETXTBSY})
_MAX_SCRATCH_BYTES = 128 * 1024
_VERIFIED_WORK_DIRS: set[str] = set()


class TransientScratchpadError(Exception):
    """A retryable failure (timeout, locked file, transient errno)."""


def is_transient_oserror(exc: OSError) -> bool:
    return exc.errno in _TRANSIENT_ERRNOS


def _work_dir_cache_key(work_dir: HostPath) -> str:
    return str(work_dir)


def _mark_verified(work_dir: HostPath) -> None:
    _VERIFIED_WORK_DIRS.add(_work_dir_cache_key(work_dir))


def _is_verified(work_dir: HostPath) -> bool:
    return _work_dir_cache_key(work_dir) in _VERIFIED_WORK_DIRS


async def with_retries[T](op: Callable[[], Awaitable[T]]) -> T:
    """Run ``op`` up to 3 times, sleeping between attempts on transient failure.

    Only ``TransientScratchpadError`` is retried; everything else propagates.
    """
    last: TransientScratchpadError | None = None
    for attempt, delay in enumerate((*_BACKOFFS, None), start=1):
        try:
            return await op()
        except TransientScratchpadError as exc:
            last = exc
            logger.debug(
                "scratchpad op transient failure on attempt {attempt}: {reason}",
                attempt=attempt,
                reason=str(exc),
            )
            if delay is None:
                break
            await asyncio.sleep(delay)
    assert last is not None
    raise last


_STARTUP_GIT_TIMEOUT = 1.5
_CLEANUP_GIT_TIMEOUT = 0.4
_spawn = pythinker_host.exec  # host process launcher (alias keeps call sites short)


def _default_git_runner(work_dir: HostPath, *, timeout: float = _STARTUP_GIT_TIMEOUT) -> GitRunner:
    cwd = str(work_dir)

    async def _cleanup_proc(proc: HostProcess) -> None:
        with contextlib.suppress(Exception):
            if proc.returncode is None:
                await proc.kill()
            await proc.wait()

    async def _once(argv: list[str]) -> GitResult:
        proc = None
        try:
            proc = await _spawn("git", "-C", cwd, *argv)
            proc.stdin.close()
            out = await asyncio.wait_for(proc.stdout.read(-1), timeout=timeout)
            code = await asyncio.wait_for(proc.wait(), timeout=timeout)
            return GitResult(ok=True, exit_code=code, stdout=out.decode("utf-8", "replace").strip())
        except TimeoutError:
            if proc is not None:
                await _cleanup_proc(proc)
            raise
        except Exception:
            logger.debug("scratchpad git {a} failed", a=argv)
            if proc is not None:
                await _cleanup_proc(proc)
            return GitResult(ok=False, exit_code=-1, stdout="")

    async def run(argv: list[str]) -> GitResult:
        for attempt, last in enumerate((False, True), start=1):  # retry one timeout fresh
            try:
                return await _once(argv)
            except TimeoutError:
                logger.debug(
                    "scratchpad git {a} timed out on attempt {attempt} (last={last})",
                    a=argv,
                    attempt=attempt,
                    last=last,
                )
                if last:
                    return GitResult(ok=False, exit_code=-1, stdout="")
        return GitResult(ok=False, exit_code=-1, stdout="")  # unreachable

    return run


def _disabled(reason: StatusReason, *, git_repo: bool, tracked: bool = False) -> ScratchpadStatus:
    return ScratchpadStatus(
        available=False, reason=reason, git_repo=git_repo, tracked=tracked, ignored=False
    )


async def ensure_git_excluded(
    work_dir: HostPath, *, git_runner: GitRunner | None = None
) -> ScratchpadStatus:
    """Ensure ``.pythinker/scratch.md`` is safe to use without polluting git.

    Fail-closed for git safety: any uncertainty disables the scratchpad for this
    session. Never raises (catches ``Exception``, not ``BaseException``).
    """
    if not _is_local_host():
        return _disabled("disabled_remote_host", git_repo=False)
    runner = git_runner or _default_git_runner(work_dir)
    try:
        inside = await runner(["rev-parse", "--is-inside-work-tree"])
        if not inside.ok:
            return _disabled("disabled_git_error", git_repo=False)
        if inside.exit_code != 0:
            _mark_verified(work_dir)
            return ScratchpadStatus(
                available=True,
                reason="available_non_git",
                git_repo=False,
                tracked=False,
                ignored=False,
            )

        for candidate in (SCRATCH_REL_PATH, _SESSION_SCRATCH_IGNORE_SAMPLE):
            tracked = await runner(["ls-files", "--error-unmatch", "--", candidate])
            if not tracked.ok:
                return _disabled("disabled_git_error", git_repo=True)
            if tracked.exit_code == 0:
                return _disabled("disabled_tracked", git_repo=True, tracked=True)
            if tracked.exit_code != 1:
                return _disabled("disabled_git_error", git_repo=True)

        prefix = await runner(["rev-parse", "--show-prefix"])
        exclude = await runner(["rev-parse", "--git-path", "info/exclude"])
        if (
            not prefix.ok
            or prefix.exit_code != 0
            or not exclude.ok
            or exclude.exit_code != 0
            or not exclude.stdout.strip()
        ):
            return _disabled("disabled_git_error", git_repo=True)
        prefix_text = prefix.stdout.strip()
        for rel_path in (SCRATCH_REL_PATH, SESSION_SCRATCH_IGNORE_PATTERN):
            exclude_line = f"{prefix_text}{rel_path}"
            await with_retries(
                lambda line=exclude_line: _append_exclude_line(
                    work_dir, exclude.stdout.strip(), line
                )
            )

        for candidate in (SCRATCH_REL_PATH, _SESSION_SCRATCH_IGNORE_SAMPLE):
            ignored = await runner(["check-ignore", "-q", "--", candidate])
            if not ignored.ok:
                return _disabled("disabled_git_error", git_repo=True)
            if ignored.exit_code == 1:
                return _disabled("disabled_not_ignored", git_repo=True)
            if ignored.exit_code != 0:
                return _disabled("disabled_git_error", git_repo=True)
        _mark_verified(work_dir)
        return ScratchpadStatus(
            available=True,
            reason="available_git_ignored",
            git_repo=True,
            tracked=False,
            ignored=True,
        )
    except TransientScratchpadError:
        return _disabled("disabled_path_error", git_repo=True)
    except Exception:  # never break startup; do NOT catch BaseException
        logger.debug("scratchpad ensure_git_excluded failed")
        return _disabled("disabled_path_error", git_repo=True)


async def _append_exclude_line(work_dir: HostPath, exclude_path: str, exclude_line: str) -> None:
    """Append ``exclude_line`` to the resolved info/exclude if missing."""
    path = Path(exclude_path)
    if not path.is_absolute():
        path = Path(str(work_dir)) / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _exclude_lock(path):
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if any(line.strip() == exclude_line for line in existing.splitlines()):
                return
            prefix = "" if existing == "" or existing.endswith("\n") else "\n"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"{prefix}{exclude_line}\n")
    except OSError as exc:
        if is_transient_oserror(exc):
            raise TransientScratchpadError(str(exc)) from exc
        raise


@contextlib.contextmanager
def _exclude_lock(path: Path) -> Generator[None]:
    """Best-effort advisory lock for concurrent exclude writes."""
    lock_file = path.with_name(f"{path.name}.scratchpad.lock")
    fh = lock_file.open("w", encoding="utf-8")
    try:
        try:
            import fcntl
        except ImportError:
            yield
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


@contextlib.contextmanager
def _scratch_file_lock(fh: TextIO) -> Generator[None]:
    """Best-effort advisory lock on the scratch file itself (no extra git file)."""
    try:
        import fcntl
    except ImportError:
        yield
    else:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


_DEFAULT_SCRATCHPAD_FILE = """# Pythinker Scratchpad

Compact private session context. Each session block starts with stable labels
for future recall, then short milestone events. Keep full logs in task outputs;
add only decisions, evidence, blockers, and next checks needed to resume work.
"""


async def ensure_scratch_created(
    work_dir: HostPath,
    *,
    session_id: str | None = None,
    session_title: str | None = None,
    git_runner: GitRunner | None = None,
) -> ScratchpadCreationResult:
    """Create the session scratchpad once the runtime knows it is safe.

    This is the deterministic backstop for cases where the model starts a
    multi-agent or multi-step mission but forgets to create the prompt-driven
    scratchpad itself. Never overwrites existing content and never follows a
    pre-existing symlink at the scratch path or parent directory.
    """
    status = await ensure_git_excluded(work_dir, git_runner=git_runner)
    if not status.available:
        return ScratchpadCreationResult(False, status.reason)

    path = session_scratch_path(
        work_dir,
        session_id=session_id,
        session_title=session_title,
    )
    parent = path.parent
    try:
        if path.is_symlink() or path.exists():
            if path.is_symlink() or path.is_file():
                return ScratchpadCreationResult(False, "already_exists")
            return ScratchpadCreationResult(False, "not_a_file")

        if parent.is_symlink():
            return ScratchpadCreationResult(False, "unsafe_parent")
        if parent.exists() and not parent.is_dir():
            return ScratchpadCreationResult(False, "unsafe_parent")
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            return ScratchpadCreationResult(False, "unsafe_parent")

        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_DEFAULT_SCRATCHPAD_FILE)
        return ScratchpadCreationResult(True, "created")
    except FileExistsError:
        return ScratchpadCreationResult(False, "already_exists")
    except TransientScratchpadError:
        return ScratchpadCreationResult(False, "disabled_path_error")
    except Exception:
        logger.debug("scratchpad creation failed")
        return ScratchpadCreationResult(False, "error")


_MAX_EVENT_TITLE = 140
_MAX_EVENT_DETAIL = 220
_MAX_EVENT_DETAILS = 6


def _clean_event_text(value: object, *, max_len: int) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("|", " ")
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1].rstrip()}…"


def _session_marker(session_id: str) -> str:
    return f"<!-- pythinker-session:{_clean_event_text(session_id, max_len=80)} -->"


def _normalize_labels(labels: Sequence[object] | None, *, short_id: str) -> list[str]:
    raw = (f"session:{short_id}", *(labels or ()))
    result: list[str] = []
    for label in raw:
        clean = _clean_event_text(label, max_len=80)
        if clean and clean not in result:
            result.append(clean)
    return result


def _merge_session_labels(existing: str, marker: str, labels: Sequence[str]) -> str:
    if not labels or marker not in existing:
        return existing
    lines = existing.splitlines()
    marker_index = next((i for i, line in enumerate(lines) if line.strip() == marker), -1)
    if marker_index == -1:
        return existing
    label_index = marker_index + 1
    current: list[str] = []
    if label_index < len(lines) and lines[label_index].startswith("labels:"):
        current = [part.strip() for part in lines[label_index][len("labels:") :].split("|")]
        current = [part for part in current if part]
    merged = list(current)
    for label in labels:
        if label not in merged:
            merged.append(label)
    label_line = f"labels: {' | '.join(merged)}"
    if label_index < len(lines) and lines[label_index].startswith("labels:"):
        lines[label_index] = label_line
    else:
        lines.insert(label_index, label_line)
    trailing_newline = "\n" if existing.endswith("\n") else ""
    return "\n".join(lines) + trailing_newline


def _cap_scratch_text(text: str) -> str:
    if len(text.encode("utf-8")) <= _MAX_SCRATCH_BYTES:
        return text

    lines = text.splitlines(keepends=True)
    header: list[str] = []
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## Session "):
            if current is not None:
                blocks.append(current)
            current = [line]
        elif current is None:
            header.append(line)
        else:
            current.append(line)
    if current is not None:
        blocks.append(current)
    if not blocks:
        return text

    kept: list[list[str]] = []
    for block in reversed(blocks):
        candidate = header + [line for kept_block in [block, *kept] for line in kept_block]
        candidate_text = "".join(candidate)
        if len(candidate_text.encode("utf-8")) <= _MAX_SCRATCH_BYTES or not kept:
            kept.insert(0, block)
        else:
            break
    capped = "".join(header + [line for block in kept for line in block])
    if len(capped.encode("utf-8")) <= _MAX_SCRATCH_BYTES:
        return capped
    return text


def _append_scratch_event_to_file(
    path: Path,
    *,
    session_id: str | None,
    title: str,
    details: Sequence[object] | None = None,
    labels: Sequence[object] | None = None,
) -> None:
    try:
        with path.open("r+", encoding="utf-8") as fh, _scratch_file_lock(fh):
            fh.seek(0)
            existing = fh.read()
            lines: list[str] = []
            if session_id:
                marker = _session_marker(session_id)
                short_id = _session_short_id(session_id)
                clean_labels = _normalize_labels(labels, short_id=short_id)
                if marker not in existing:
                    lines.extend(
                        [
                            "",
                            f"## Session {short_id}",
                            marker,
                            f"labels: {' | '.join(clean_labels)}",
                        ]
                    )
                else:
                    merged_existing = _merge_session_labels(existing, marker, clean_labels)
                    if merged_existing != existing:
                        fh.seek(0)
                        fh.write(merged_existing)
                        fh.truncate()
                        existing = merged_existing

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            clean_title = _clean_event_text(title, max_len=_MAX_EVENT_TITLE)
            lines.append(f"- {timestamp} — {clean_title}")
            for detail in list(details or ())[:_MAX_EVENT_DETAILS]:
                clean_detail = _clean_event_text(detail, max_len=_MAX_EVENT_DETAIL)
                if clean_detail:
                    lines.append(f"  - {clean_detail}")

            prefix = "" if existing == "" or existing.endswith("\n") else "\n"
            body = "\n".join(lines)
            full_text = f"{existing}{prefix}{body}\n"
            capped_text = _cap_scratch_text(full_text)
            fh.seek(0)
            fh.write(capped_text)
            fh.truncate()
    except OSError as exc:
        if is_transient_oserror(exc):
            raise TransientScratchpadError(str(exc)) from exc
        raise


def append_scratch_event_sync(
    work_dir: HostPath,
    *,
    title: str,
    details: Sequence[object] | None = None,
    labels: Sequence[object] | None = None,
    session_id: str | None = None,
    session_title: str | None = None,
    create: bool = False,
) -> ScratchpadAppendResult:
    """Append one compact milestone to a local scratchpad. Never raises."""
    if not _is_local_host():
        return ScratchpadAppendResult(False, "remote_host")
    path = session_scratch_path(
        work_dir,
        session_id=session_id,
        session_title=session_title,
    )
    try:
        if path.is_symlink():
            return ScratchpadAppendResult(False, "not_a_file")
        if not path.exists():
            if not create:
                return ScratchpadAppendResult(False, "missing")
            parent = path.parent
            if parent.is_symlink():
                return ScratchpadAppendResult(False, "unsafe_parent")
            if parent.exists() and not parent.is_dir():
                return ScratchpadAppendResult(False, "unsafe_parent")
            parent.mkdir(parents=True, exist_ok=True)
            if parent.is_symlink() or not parent.is_dir():
                return ScratchpadAppendResult(False, "unsafe_parent")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(_DEFAULT_SCRATCHPAD_FILE)
        if not path.is_file():
            return ScratchpadAppendResult(False, "not_a_file")
        _append_scratch_event_to_file(
            path,
            session_id=session_id,
            title=title,
            details=details,
            labels=labels,
        )
        return ScratchpadAppendResult(True, "appended")
    except FileExistsError:
        return append_scratch_event_sync(
            work_dir,
            title=title,
            details=details,
            labels=labels,
            session_id=session_id,
            session_title=session_title,
            create=False,
        )
    except TransientScratchpadError:
        return ScratchpadAppendResult(False, "locked")
    except Exception:
        logger.debug("scratchpad event append failed")
        return ScratchpadAppendResult(False, "error")


async def append_scratch_event(
    work_dir: HostPath,
    *,
    title: str,
    details: Sequence[object] | None = None,
    labels: Sequence[object] | None = None,
    session_id: str | None = None,
    session_title: str | None = None,
    git_runner: GitRunner | None = None,
) -> ScratchpadAppendResult:
    """Create the scratchpad if safe, then append one compact milestone."""
    if _is_verified(work_dir):
        return await asyncio.to_thread(
            append_scratch_event_sync,
            work_dir,
            session_id=session_id,
            session_title=session_title,
            title=title,
            details=details,
            labels=labels,
            create=True,
        )

    creation = await ensure_scratch_created(
        work_dir,
        session_id=session_id,
        session_title=session_title,
        git_runner=git_runner,
    )
    if not creation.created and creation.reason != "already_exists":
        return ScratchpadAppendResult(False, creation.reason)
    _mark_verified(work_dir)
    return await asyncio.to_thread(
        append_scratch_event_sync,
        work_dir,
        session_id=session_id,
        session_title=session_title,
        title=title,
        details=details,
        labels=labels,
        create=False,
    )


async def cleanup_scratch(
    work_dir: HostPath, *, git_runner: GitRunner | None = None
) -> ScratchpadCleanupResult:
    """Delete legacy and named session scratchpads only when proven safe. Never raises."""
    if not _is_local_host():
        return ScratchpadCleanupResult(deleted=False, reason="remote_host")
    legacy_path = scratch_path(work_dir)
    named_dir = scratch_dir(work_dir)
    runner = git_runner or _default_git_runner(work_dir, timeout=_CLEANUP_GIT_TIMEOUT)
    try:
        paths: list[Path] = []
        if legacy_path.is_symlink() or legacy_path.exists():
            paths.append(legacy_path)
        if named_dir.is_dir() and not named_dir.is_symlink():
            paths.extend(sorted(named_dir.glob("*.md")))
        if not paths:
            return ScratchpadCleanupResult(deleted=False, reason="missing")

        inside = await runner(["rev-parse", "--is-inside-work-tree"])
        if not inside.ok:
            return ScratchpadCleanupResult(deleted=False, reason="unverified")
        if inside.exit_code == 0:
            tracked_legacy = await runner(["ls-files", "--error-unmatch", "--", SCRATCH_REL_PATH])
            if not tracked_legacy.ok:
                return ScratchpadCleanupResult(deleted=False, reason="unverified")
            if tracked_legacy.exit_code == 0:
                return ScratchpadCleanupResult(deleted=False, reason="tracked")
            if tracked_legacy.exit_code != 1:
                return ScratchpadCleanupResult(deleted=False, reason="unverified")

            root = Path(str(work_dir))
            for path in paths:
                if path == legacy_path:
                    continue
                try:
                    rel_path = path.relative_to(root).as_posix()
                except ValueError:
                    return ScratchpadCleanupResult(deleted=False, reason="unverified")
                tracked_named = await runner(["ls-files", "--error-unmatch", "--", rel_path])
                if not tracked_named.ok:
                    return ScratchpadCleanupResult(deleted=False, reason="unverified")
                if tracked_named.exit_code == 0:
                    return ScratchpadCleanupResult(deleted=False, reason="tracked")
                if tracked_named.exit_code != 1:
                    return ScratchpadCleanupResult(deleted=False, reason="unverified")

        deleted = False
        for path in paths:
            if path.is_symlink():
                await with_retries(lambda p=path: _unlink(p))
                deleted = True
                continue
            if path.is_dir():
                logger.debug("scratchpad cleanup: path is a directory, skipping")
                return ScratchpadCleanupResult(deleted=False, reason="not_a_file")
            await with_retries(lambda p=path: _unlink(p))
            deleted = True
        return ScratchpadCleanupResult(deleted=deleted, reason="deleted" if deleted else "missing")
    except TransientScratchpadError:
        return ScratchpadCleanupResult(deleted=False, reason="locked")
    except Exception:  # never break shutdown; do NOT catch BaseException
        logger.debug("scratchpad cleanup failed")
        return ScratchpadCleanupResult(deleted=False, reason="error")


async def _unlink(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        if is_transient_oserror(exc):
            raise TransientScratchpadError(str(exc)) from exc
        raise


SCRATCHPAD_SECTION_START = "<!-- PYTHINKER_SCRATCHPAD_SECTION_START -->"
SCRATCHPAD_SECTION_END = "<!-- PYTHINKER_SCRATCHPAD_SECTION_END -->"

DEFAULT_SCRATCHPAD_SECTION = (
    "As the root agent, treat named `.pythinker/scratch/*.md` files as the "
    "minimal session memory for context-aware work. The runtime auto-creates a per-session block "
    "with stable recall labels (for example `session:<id>`, `workspace:<name>`, "
    "`ui:<mode>`, `source:<startup|resume>`) and compact milestones such as "
    "session start, todo summaries, agent/task starts, and task terminal status. "
    "Keep any manual additions short and organized: current objective, searchable "
    "labels, load-bearing evidence, decisions, blockers, and next verification "
    "checkpoint. On a fresh run, or whenever the user asks about prior session "
    "work/history/context, fast-skim the relevant `.pythinker/scratch/*.md` "
    "labels and current session block before answering. Do not paste full logs, "
    "raw prompts, command output, secrets, or duplicate the whole `SetTodoList` "
    "checklist into the file. Retain session scratchpads after successful "
    "completion as compact history for future recall; remove them only when the "
    "user explicitly asks for cleanup. Subagents do not create their own scratch "
    "files."
)

_SECTION_UNAVAILABLE = (
    "Scratchpad unavailable this session; do not create or edit `.pythinker/scratch.md` "
    "or `.pythinker/scratch/*.md`."
)

_SCRATCHPAD_RECOVERY_NOTE = (
    "Startup recovery: prior scratchpad history exists under `.pythinker/scratch/` "
    "or legacy `.pythinker/scratch.md`. If you are the root agent, fast-skim labels "
    "and the current/relevant session block before planning or answering so you "
    "can recover context; keep the history unless the user explicitly asks for "
    "cleanup."
)


def render_scratchpad_section(status: ScratchpadStatus, *, scratch_exists: bool = False) -> str:
    if not status.available:
        return _SECTION_UNAVAILABLE
    if scratch_exists:
        return f"{DEFAULT_SCRATCHPAD_SECTION}\n\n{_SCRATCHPAD_RECOVERY_NOTE}"
    return DEFAULT_SCRATCHPAD_SECTION


def format_scratchpad_block(section: str) -> str:
    return f"{SCRATCHPAD_SECTION_START}\n{section}\n{SCRATCHPAD_SECTION_END}"


def refresh_system_prompt_scratchpad_section(system_prompt: str, section: str) -> str:
    """Refresh only the dynamic scratchpad block in a rendered system prompt."""
    try:
        block = format_scratchpad_block(section)
        start = system_prompt.find(SCRATCHPAD_SECTION_START)
        end = system_prompt.find(SCRATCHPAD_SECTION_END)
        if start != -1 and end != -1 and start < end:
            end += len(SCRATCHPAD_SECTION_END)
            return f"{system_prompt[:start]}{block}{system_prompt[end:]}"
        anchor = "Before every tool response"
        if anchor in system_prompt:
            idx = system_prompt.index(anchor)
            return f"{system_prompt[:idx].rstrip()}\n\n{block}\n\n{system_prompt[idx:]}"
        return f"{system_prompt.rstrip()}\n\n{block}"
    except Exception:
        logger.debug("scratchpad system prompt refresh failed")
        return system_prompt
