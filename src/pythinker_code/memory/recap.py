from __future__ import annotations

import hashlib
from collections.abc import Iterable

from pythinker_code.session_state import SessionState


def content_hash(*, tier: str, title: str, body: str) -> str:
    normalized = "\n".join(part.strip().lower() for part in (tier, title, body))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_session_recap(
    *,
    state: SessionState,
    session_id: str,
    request: str = "",
    scratch_blocks: Iterable[str] = (),
    files_read: Iterable[str] = (),
    files_modified: Iterable[str] = (),
) -> str:
    """Build a stable-schema Markdown recap block for JOURNAL.md."""
    open_todos = [todo.title for todo in state.todos if todo.status in {"pending", "in_progress"}]
    completed = [todo.title for todo in state.todos if todo.status == "done"]
    learned = [block.strip() for block in scratch_blocks if block.strip()]
    title = state.custom_title or session_id[:12]
    body_for_hash = "\n".join([request, *learned, *open_todos, *completed])
    digest = content_hash(tier="journal", title=title, body=body_for_hash)

    def bullets(items: Iterable[str]) -> str:
        lines = [f"- {item}" for item in items if item]
        return "\n".join(lines) if lines else "- none"

    return "\n".join(
        [
            f"session_id: {session_id}",
            f"title: {title}",
            f"content_hash: {digest}",
            "",
            "## request",
            request.strip() or "none",
            "",
            "## investigated",
            bullets(files_read),
            "",
            "## learned",
            bullets(learned),
            "",
            "## completed",
            bullets(completed),
            "",
            "## next_steps",
            bullets(open_todos),
            "",
            "## open_todos",
            bullets(open_todos),
            "",
            "## files_read",
            bullets(files_read),
            "",
            "## files_modified",
            bullets(files_modified),
            "",
            "## labels",
            f"- session:{session_id[:12]}",
        ]
    )
