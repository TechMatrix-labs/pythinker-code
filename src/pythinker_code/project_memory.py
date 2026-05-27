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

from pythinker_host.path import HostPath

from pythinker_code.scratchpad import GitRunner, _default_git_runner
from pythinker_code.utils.logging import logger

ENTRY_DELIMITER = "\n§\n"
MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375
INJECTION_BUDGET_BYTES = 8 * 1024


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
