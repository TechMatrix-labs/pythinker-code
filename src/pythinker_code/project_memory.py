"""Central, per-project agent memory: durable MEMORY.md + USER.md.

Stored under the per-user share dir (``~/.pythinker/projects/<key>/memory/``),
keyed by a stable project identity (git remote -> toplevel -> work dir). Ported
in spirit from upstream Hermes ``tools/memory_tool.py`` and re-scoped from global
to per-project. Local-host only in v1.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pythinker_host.path import HostPath

from pythinker_code.scratchpad import GitRunner, _default_git_runner
from pythinker_code.share import get_share_dir
from pythinker_code.utils.logging import logger

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
    (r"sk-[A-Za-z0-9]{20,}", "openai_key"),
    (r"gh[ps]_[A-Za-z0-9]{30,}", "github_token"),
    (r"xox[bp]-[A-Za-z0-9-]{10,}", "slack_token"),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
]

_INVISIBLE_CHARS = frozenset(
    chr(c)
    for c in (
        0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF,
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
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
