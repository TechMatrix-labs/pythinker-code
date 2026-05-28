from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from pythinker_host.path import HostPath

from pythinker_code.memory.recall import gather_candidates
from pythinker_code.memory.recap import content_hash
from pythinker_code.project_memory import ProjectMemoryStore


@dataclass(frozen=True, slots=True)
class InboxCandidate:
    id: str
    target: str
    title: str
    content: str
    source_path: str
    content_hash: str


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "-", value.lower())[:32].strip("-") or "candidate"


async def inbox_dir(store: ProjectMemoryStore) -> Path:
    root = await store._ensure_dir()  # pyright: ignore[reportPrivateUsage]
    path = root / "memory" / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def list_inbox_candidates(store: ProjectMemoryStore) -> list[InboxCandidate]:
    directory = await inbox_dir(store)
    out: list[InboxCandidate] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(InboxCandidate(**data))
        except Exception:
            continue
    return out


async def generate_inbox_candidates(
    store: ProjectMemoryStore, work_dir: HostPath, *, limit: int = 20
) -> list[InboxCandidate]:
    """Stage scratch/journal candidates for approval-gated durable memory consolidation."""
    existing_entries = [*await store.read_entries("memory"), *await store.read_entries("user")]
    existing_hashes = {
        content_hash(tier="memory", title=entry[:60], body=entry) for entry in existing_entries
    }
    staged = {candidate.content_hash for candidate in await list_inbox_candidates(store)}
    directory = await inbox_dir(store)
    candidates: list[InboxCandidate] = []
    for block in await gather_candidates(store, work_dir):
        if block.tier in {"memory", "user"}:
            continue
        digest = content_hash(tier="memory", title=block.title, body=block.content)
        if digest in existing_hashes or digest in staged:
            continue
        candidate = InboxCandidate(
            id=_safe_id(digest),
            target="memory",
            title=block.title or block.tier,
            content=block.content,
            source_path=block.source_path,
            content_hash=digest,
        )
        path = directory / f"{candidate.id}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(candidate), fh, ensure_ascii=False, indent=2)
        candidates.append(candidate)
        staged.add(digest)
        if len(candidates) >= limit:
            break
    return candidates


async def approve_inbox_candidate(store: ProjectMemoryStore, candidate_id: str) -> str:
    directory = await inbox_dir(store)
    path = directory / f"{_safe_id(candidate_id)}.json"
    if not path.is_file():
        return "Candidate not found."
    data = json.loads(path.read_text(encoding="utf-8"))
    candidate = InboxCandidate(**data)
    result = await store.add("memory", candidate.content)
    if not result.ok:
        return result.message
    path.unlink(missing_ok=True)
    return "Candidate approved and added to project memory."


async def reject_inbox_candidate(store: ProjectMemoryStore, candidate_id: str) -> str:
    directory = await inbox_dir(store)
    path = directory / f"{_safe_id(candidate_id)}.json"
    if not path.is_file():
        return "Candidate not found."
    path.unlink(missing_ok=True)
    return "Candidate rejected."
