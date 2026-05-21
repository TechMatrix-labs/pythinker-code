"""Line-preserving character budget helpers."""

from __future__ import annotations

ELLIPSIS = "\n... [truncated]"


def clip_text(text: str, budget_chars: int, *, ellipsis: str = ELLIPSIS) -> str:
    """Clip text to a character budget while preserving whole lines when possible."""
    if budget_chars <= 0:
        return ""
    if len(text) <= budget_chars:
        return text
    if budget_chars <= len(ellipsis):
        return ellipsis[:budget_chars]
    limit = budget_chars - len(ellipsis)
    prefix = text[:limit]
    newline = prefix.rfind("\n")
    if newline > 0:
        prefix = prefix[:newline]
    return prefix.rstrip() + ellipsis


def approx_tokens(text: str) -> int:
    """Return the Pythinker Security Scan rough token estimate (4 chars ≈ 1 token)."""
    return (len(text) + 3) // 4
