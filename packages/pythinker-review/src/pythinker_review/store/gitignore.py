"""Idempotent .gitignore patcher."""

from __future__ import annotations

from pathlib import Path

_MARKER = "# pythinker-review"
_ENTRY = ".pythinker-review/"


def ensure_gitignored(*, repo_root: Path) -> bool:
    gi = repo_root / ".gitignore"
    if not gi.exists():
        return False
    text = gi.read_text(encoding="utf-8")
    if any(line.strip() == _ENTRY for line in text.splitlines()):
        return False
    prefix = "" if text.endswith("\n") else "\n"
    gi.write_text(f"{text}{prefix}\n{_MARKER}\n{_ENTRY}\n", encoding="utf-8")
    return True
