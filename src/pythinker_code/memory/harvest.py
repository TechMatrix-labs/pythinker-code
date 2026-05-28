from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pythinker_core.message import Message, TextPart

from pythinker_code.memory.sanitize import sanitize_candidate_block

_NOTE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(decision|blocker|next|evidence)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_KIND_MAP: dict[str, Literal["decision", "evidence", "blocker", "next", "note"]] = {
    "decision": "decision",
    "evidence": "evidence",
    "blocker": "blocker",
    "next": "next",
}


@dataclass(frozen=True, slots=True)
class ScratchNote:
    kind: Literal["decision", "evidence", "blocker", "next", "note"]
    content: str


class CompactionHarvester:
    """Heuristic, safe-only extraction from messages that compaction will drop."""

    def harvest(self, messages: list[Message] | tuple[Message, ...]) -> list[ScratchNote]:
        notes: list[ScratchNote] = []
        seen: set[tuple[str, str]] = set()
        for msg in messages:
            if msg.role != "assistant":
                continue
            for part in msg.content:
                if not isinstance(part, TextPart):
                    continue
                for line in part.text.splitlines():
                    match = _NOTE_RE.match(line)
                    if match is None:
                        continue
                    kind = _KIND_MAP.get(match.group(1).lower(), "note")
                    clean = sanitize_candidate_block(match.group(2))
                    if clean is None:
                        continue
                    key = (kind, clean)
                    if key in seen:
                        continue
                    seen.add(key)
                    notes.append(ScratchNote(kind=kind, content=clean))
        return notes
