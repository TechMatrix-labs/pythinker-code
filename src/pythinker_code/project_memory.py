"""Central, per-project agent memory: durable MEMORY.md + USER.md.

Stored under the per-user share dir (``~/.pythinker/projects/<key>/memory/``),
keyed by a stable project identity (git remote -> toplevel -> work dir). Ported
in spirit from upstream Hermes ``tools/memory_tool.py`` and re-scoped from global
to per-project. Local-host only in v1.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pythinker_core.message import Message
from pythinker_host.path import HostPath

from pythinker_code.scratchpad import (
    GitRunner,
    _default_git_runner,  # pyright: ignore[reportPrivateUsage]
)
from pythinker_code.share import get_share_dir
from pythinker_code.soul.dynamic_injection import DynamicInjection, DynamicInjectionProvider
from pythinker_code.utils.logging import logger

if TYPE_CHECKING:
    from pythinker_code.soul.pythinkersoul import PythinkerSoul

ENTRY_DELIMITER = "\n§\n"
MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375
INJECTION_BUDGET_BYTES = 8 * 1024

Target = Literal["memory", "user"]


def _normalize_remote(url: str) -> str:
    text = url.strip().lower()
    text = re.sub(r"//[^@/]*@", "//", text)  # strip credentials
    text = re.sub(r"^git@([^:]+):", r"//\1/", text)  # scp-style -> path-style
    text = text.removesuffix(".git").rstrip("/")
    return text


def _slug(text: str) -> str:
    chars: list[str] = []
    prev_dash = False
    for ch in text.lower():
        if ch.isalnum():
            chars.append(ch)
            prev_dash = False
        elif not prev_dash:
            chars.append("-")
            prev_dash = True
    slug = "".join(chars).strip("-")
    return (slug or "project")[:48].strip("-") or "project"


async def _project_identity(work_dir: HostPath, runner: GitRunner) -> str:
    remote = await runner(["remote", "get-url", "origin"])
    if remote.ok and remote.exit_code == 0 and remote.stdout.strip():
        return _normalize_remote(remote.stdout.strip())
    top = await runner(["rev-parse", "--show-toplevel"])
    if top.ok and top.exit_code == 0 and top.stdout.strip():
        return top.stdout.strip()
    return str(work_dir)


async def project_key(work_dir: HostPath, *, git_runner: GitRunner | None = None) -> str:
    """Stable ``<slug>-<12hex>`` key for the project. Never raises."""
    runner = git_runner or _default_git_runner(work_dir)
    try:
        identity = await _project_identity(work_dir, runner)
    except Exception:
        logger.debug("project_key identity resolution failed; using work_dir")
        identity = str(work_dir)
    basename = Path(identity.rstrip("/")).name or "project"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"{_slug(basename)}-{digest}"


@dataclass(frozen=True, slots=True)
class MemoryOpResult:
    ok: bool
    message: str


class ProjectMemoryStore:
    """Read/write the per-project MEMORY.md + USER.md under the central share dir."""

    def __init__(
        self,
        work_dir: HostPath,
        *,
        git_runner: GitRunner | None = None,
        memory_char_limit: int = MEMORY_CHAR_LIMIT,
        user_char_limit: int = USER_CHAR_LIMIT,
    ) -> None:
        self._work_dir = work_dir
        self._git_runner = git_runner
        self._memory_limit = memory_char_limit
        self._user_limit = user_char_limit
        self._root: Path | None = None

    async def _ensure_dir(self) -> Path:
        if self._root is None:
            key = await project_key(self._work_dir, git_runner=self._git_runner)
            root = get_share_dir() / "projects" / key
            (root / "memory").mkdir(parents=True, exist_ok=True)
            self._root = root
        return self._root

    def _filename(self, target: Target) -> str:
        return "USER.md" if target == "user" else "MEMORY.md"

    def _char_limit(self, target: Target) -> int:
        return self._user_limit if target == "user" else self._memory_limit

    async def _path_for(self, target: Target) -> Path:
        root = await self._ensure_dir()
        return root / "memory" / self._filename(target)

    @staticmethod
    def _split_entries(raw: str) -> list[str]:
        if not raw.strip():
            return []
        return [e.strip() for e in raw.split(ENTRY_DELIMITER) if e.strip()]

    async def read_entries(self, target: Target) -> list[str]:
        path = await self._path_for(target)
        try:
            if not path.exists():
                return []
            return self._split_entries(path.read_text(encoding="utf-8"))
        except OSError:
            logger.debug("project memory read failed for {t}", t=target)
            return []

    @staticmethod
    @contextlib.contextmanager
    def _file_lock(path: Path) -> Generator[None]:
        # NOTE (v1): fcntl gives cross-process safety. The lock is held across
        # await in callers, so do NOT invoke store mutations concurrently on one
        # event loop / store instance in v1 (the Memory tool is root-only and
        # sequential). Revisit with asyncio.to_thread / asyncio.Lock if that changes.
        lock_path = path.with_name(path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = lock_path.open("a+", encoding="utf-8")
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

    async def _write_entries(self, target: Target, entries: list[str]) -> None:
        path = await self._path_for(target)
        content = ENTRY_DELIMITER.join(entries) if entries else ""
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".mem_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    async def add(self, target: Target, content: str) -> MemoryOpResult:
        content = content.strip()
        if not content:
            return MemoryOpResult(False, "Content cannot be empty.")
        blocked = scan_memory_content(content)
        if blocked:
            return MemoryOpResult(False, blocked)
        path = await self._path_for(target)
        with self._file_lock(path):
            entries = await self.read_entries(target)
            if content in entries:
                return MemoryOpResult(True, "Entry already exists (no duplicate added).")
            limit = self._char_limit(target)
            new_total = len(ENTRY_DELIMITER.join([*entries, content]))
            if new_total > limit:
                current = len(ENTRY_DELIMITER.join(entries))
                return MemoryOpResult(
                    False,
                    f"Memory at {current}/{limit} chars; this entry ({len(content)}) "
                    "exceeds the limit. Replace or remove entries first.",
                )
            await self._write_entries(target, [*entries, content])
        return MemoryOpResult(True, "Entry added.")

    @staticmethod
    def _match_one(entries: list[str], old_text: str) -> int | MemoryOpResult:
        matches = [i for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return MemoryOpResult(False, f"No entry matched '{old_text}'.")
        if len(matches) > 1 and len({entries[i] for i in matches}) > 1:
            return MemoryOpResult(
                False, f"Multiple entries matched '{old_text}'. Be more specific."
            )
        return matches[0]

    async def replace(self, target: Target, old_text: str, new_content: str) -> MemoryOpResult:
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text:
            return MemoryOpResult(False, "old_text cannot be empty.")
        if not new_content:
            return MemoryOpResult(False, "new_content cannot be empty. Use 'remove' to delete.")
        blocked = scan_memory_content(new_content)
        if blocked:
            return MemoryOpResult(False, blocked)
        path = await self._path_for(target)
        with self._file_lock(path):
            entries = await self.read_entries(target)
            idx = self._match_one(entries, old_text)
            if isinstance(idx, MemoryOpResult):
                return idx
            limit = self._char_limit(target)
            candidate = list(entries)
            candidate[idx] = new_content
            if len(ENTRY_DELIMITER.join(candidate)) > limit:
                return MemoryOpResult(False, f"Replacement would exceed the {limit}-char limit.")
            await self._write_entries(target, candidate)
        return MemoryOpResult(True, "Entry replaced.")

    async def remove(self, target: Target, old_text: str) -> MemoryOpResult:
        old_text = old_text.strip()
        if not old_text:
            return MemoryOpResult(False, "old_text cannot be empty.")
        path = await self._path_for(target)
        with self._file_lock(path):
            entries = await self.read_entries(target)
            idx = self._match_one(entries, old_text)
            if isinstance(idx, MemoryOpResult):
                return idx
            entries.pop(idx)
            await self._write_entries(target, entries)
        return MemoryOpResult(True, "Entry removed.")

    async def append_journal(self, recap: str) -> MemoryOpResult:
        """Prepend one stable session recap to ``JOURNAL.md`` if it is new."""
        recap = recap.strip()
        if not recap:
            return MemoryOpResult(False, "Recap cannot be empty.")
        blocked = scan_memory_content(recap)
        if blocked:
            return MemoryOpResult(False, blocked)
        root = await self._ensure_dir()
        path = root / "memory" / "JOURNAL.md"
        with self._file_lock(path):
            entries = self._split_entries(path.read_text(encoding="utf-8")) if path.exists() else []
            if recap in entries:
                return MemoryOpResult(True, "Journal recap already exists (no duplicate added).")
            await self._write_journal_entries([recap, *entries])
        return MemoryOpResult(True, "Journal recap added.")

    async def _write_journal_entries(self, entries: list[str]) -> None:
        root = await self._ensure_dir()
        path = root / "memory" / "JOURNAL.md"
        content = ENTRY_DELIMITER.join(entries) if entries else ""
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".journal_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    async def _read_journal(self, *, last_n: int = 10) -> list[str]:
        """Read up to ``last_n`` newest session recaps from ``JOURNAL.md``.

        Forward hook: ``JOURNAL.md`` is written by a later phase (P2) which
        prepends recaps (newest-first), so the first ``last_n`` entries are the
        most recent. No writer exists yet, so this returns ``[]`` in P1; reading
        it here keeps the P2 writer purely additive.
        """
        root = await self._ensure_dir()
        path = root / "memory" / "JOURNAL.md"
        try:
            if not path.exists():
                return []
            return self._split_entries(path.read_text(encoding="utf-8"))[:last_n]
        except OSError:
            return []

    async def snapshot(self, *, budget: int = INJECTION_BUDGET_BYTES) -> str:
        memory = await self.read_entries("memory")
        user = await self.read_entries("user")
        journal = await self._read_journal()
        sections: list[tuple[str, list[str]]] = [
            ("## Project memory", memory),
            ("## User", user),
            ("## Recent sessions", journal),
        ]
        out: list[str] = []
        used = 0
        for heading, entries in sections:
            if not entries:
                continue
            chunk = heading + "\n" + "\n".join(f"- {e}" for e in entries) + "\n"
            if used + len(chunk.encode("utf-8")) > budget and out:
                break
            out.append(chunk)
            used += len(chunk.encode("utf-8"))
        if not out:
            return ""
        # Header (exempt from the entry budget) names the source files so the
        # agent can read full files if truncated and knows the write path.
        root = await self._ensure_dir()
        header = (
            "Project memory — durable facts recorded for this project, stored at "
            f"{root / 'memory'}. Update it with the Memory tool; if this block looks "
            "truncated, read MEMORY.md / USER.md there directly.\n"
        )
        return (header + "\n" + "\n".join(out)).strip()


_MEMORY_THREAT_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(?:(?:previous|all|above|prior)\s+)+instructions", "prompt_injection"),
    (r"you\s+are\s+now\s+", "role_hijack"),
    (r"do\s+not\s+tell\s+the\s+user", "deception_hide"),
    (r"system\s+prompt\s+override", "sys_prompt_override"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "disregard_rules"),
    (r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_curl"),
    (r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_wget"),
    (r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", "read_secrets"),
    (r"authorized_keys", "ssh_backdoor"),
]

_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}", "openai_key"),
    (r"gh[posru]_[A-Za-z0-9]{30,}", "github_token"),
    (r"xox[bp]-[A-Za-z0-9-]{10,}", "slack_token"),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
]

_INVISIBLE_CHARS = frozenset(
    chr(c)
    for c in (
        0x200B,
        0x200C,
        0x200D,
        0x2060,
        0xFEFF,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
    )
)


def scan_memory_content(content: str) -> str | None:
    """Return an error string if content is unsafe to persist+inject, else None."""
    for ch in content:
        if ch in _INVISIBLE_CHARS:
            return f"Blocked: invisible unicode U+{ord(ch):04X} (possible injection)."
    for pattern, pid in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return (
                f"Blocked: content matches threat pattern '{pid}'. Memory is injected "
                "into the prompt and must not contain injection/exfiltration payloads."
            )
    for pattern, pid in _SECRET_PATTERNS:
        if re.search(pattern, content):
            return (
                f"Blocked: content looks like a secret ('{pid}'). Do not store secrets in memory."
            )
    return None


_INJECTION_TYPE = "project_memory"


class ProjectMemoryInjectionProvider(DynamicInjectionProvider):
    """Injects the project-memory snapshot once per session (root soul only)."""

    def __init__(self, store: ProjectMemoryStore) -> None:
        self._store = store
        self._injected = False

    async def get_injections(
        self, history: Sequence[Message], soul: PythinkerSoul
    ) -> list[DynamicInjection]:
        _ = history, soul
        if self._injected:
            return []
        self._injected = True
        try:
            block = await self._store.snapshot()
        except Exception:
            logger.debug("project memory snapshot failed")
            return []
        if not block.strip():
            return []
        return [DynamicInjection(type=_INJECTION_TYPE, content=block)]

    async def on_context_compacted(self) -> None:
        self._injected = False
