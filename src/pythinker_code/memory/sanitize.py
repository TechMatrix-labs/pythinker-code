from __future__ import annotations

import re

from pythinker_code.project_memory import scan_memory_content

_PRIVATE_RE = re.compile(r"<private>.*?</private>", re.IGNORECASE | re.DOTALL)


def strip_private_spans(text: str) -> str:
    """Remove every ``<private>...</private>`` span from memory candidate text."""
    return _PRIVATE_RE.sub("", text)


def sanitize_candidate_block(text: str) -> str | None:
    """Return injection-safe text, or ``None`` if the block must be dropped."""
    cleaned = strip_private_spans(text).strip()
    if not cleaned:
        return None
    if scan_memory_content(cleaned) is not None:
        return None
    return cleaned
