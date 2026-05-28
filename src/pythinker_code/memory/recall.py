from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pythinker_core.message import Message, TextPart
from pythinker_host.path import HostPath

from pythinker_code.memory.retriever import (
    LexicalRetriever,
    RankedBlock,
    RecallQuery,
    estimate_tokens,
)
from pythinker_code.memory.sanitize import sanitize_candidate_block
from pythinker_code.project_memory import INJECTION_BUDGET_BYTES, ProjectMemoryStore
from pythinker_code.scratchpad import scratch_dir, scratch_path
from pythinker_code.session_state import load_session_state
from pythinker_code.soul.dynamic_injection import DynamicInjection, DynamicInjectionProvider
from pythinker_code.utils.logging import logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pythinker_code.soul.pythinkersoul import PythinkerSoul

_OPEN_STATUSES = ("pending", "in_progress")
_NOTE_HEADING_RE = re.compile(r"^### (\w+) —", re.MULTILINE)
_RECALL_TYPE = "project_memory"  # keep the existing injection type id


def find_recent_open_root_todos(
    sessions_dir: Path,
    *,
    current_session_id: str,
    limit: int = 5,
    max_age_days: float = 30.0,
    max_items: int = 10,
) -> list[tuple[str, list[str]]]:
    """Return ``[(session_label, [open todo titles])]`` for recent prior sessions."""
    if not sessions_dir.is_dir():
        return []
    now = time.time()
    candidates: list[tuple[float, str, list[str]]] = []
    for child in sessions_dir.iterdir():
        if not child.is_dir() or child.name == current_session_id:
            continue
        state_file = child / "state.json"
        if not state_file.exists():
            continue
        try:
            mtime = state_file.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) / 86400.0 > max_age_days:
            continue
        try:
            state = load_session_state(child)
        except Exception:
            logger.debug("recall: failed to load state for {sid}", sid=child.name)
            continue
        if state.archived:
            continue
        open_titles = [todo.title for todo in state.todos if todo.status in _OPEN_STATUSES]
        if not open_titles:
            continue
        label = state.custom_title or child.name[:12]
        candidates.append((mtime, label, open_titles))

    candidates.sort(key=lambda item: item[0], reverse=True)
    out: list[tuple[str, list[str]]] = []
    items = 0
    for _mtime, label, titles in candidates[:limit]:
        room = max(0, max_items - items)
        if room == 0:
            break
        kept = titles[:room]
        out.append((label, kept))
        items += len(kept)
    return out


async def build_recall_block(
    *,
    candidates: list[RankedBlock],
    query: RecallQuery,
    open_todos: list[tuple[str, list[str]]],
    budget_tokens: int,
    store_path: str,
) -> str:
    ranked = await LexicalRetriever(candidates).retrieve(query, budget_tokens)
    if not ranked and not open_todos:
        return ""
    _ = store_path
    lines: list[str] = ["Relevant project memory — recalled by relevance, not the full store."]
    if open_todos:
        lines.append("\n## Open todos from recent sessions")
        for label, titles in open_todos:
            for title in titles:
                lines.append(f"- [{label}] {title}")
    if ranked:
        lines.append("\n## Recalled notes & facts")
        for block in ranked:
            source = f" from {block.source_path}" if block.source_path else ""
            lines.append(f"- ({block.tier}{source}) {block.content}")
    return "\n".join(lines).strip()


def _entries_to_blocks(
    entries: list[str], *, tier: str, source_path: str, mtime: float
) -> list[RankedBlock]:
    blocks: list[RankedBlock] = []
    for entry in entries:
        clean = sanitize_candidate_block(entry)
        if clean is None:
            continue
        blocks.append(
            RankedBlock(
                tier=tier,
                source_path=source_path,
                source_id=None,
                session_id=None,
                title=clean[:60],
                labels=(),
                files=(),
                created_at_epoch=mtime,
                token_estimate=estimate_tokens(clean),
                score=0.0,
                content=clean,
            )
        )
    return blocks


def _scratch_note_content(body: str) -> str:
    text = body.strip()
    if "\n\n" in text:
        return text.split("\n\n", 1)[1].strip()
    lines = text.splitlines()
    if lines and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", lines[0].strip()):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _scratch_note_blocks(work_dir: HostPath) -> list[RankedBlock]:
    blocks: list[RankedBlock] = []
    try:
        directory = scratch_dir(work_dir)
        files = sorted(directory.glob("*.md")) if directory.is_dir() else []
        legacy = scratch_path(work_dir)
        if legacy.is_file():
            files.append(legacy)
    except Exception:
        return []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            mtime = path.stat().st_mtime
        except OSError:
            continue
        parts = _NOTE_HEADING_RE.split(text)
        # parts = [pre, kind1, body1, kind2, body2, ...]
        for index in range(1, len(parts) - 1, 2):
            kind = parts[index]
            body = _scratch_note_content(parts[index + 1])
            clean = sanitize_candidate_block(body)
            if clean is None:
                continue
            blocks.append(
                RankedBlock(
                    tier="scratch",
                    source_path=str(path),
                    source_id=None,
                    session_id=None,
                    title=kind,
                    labels=(f"kind:{kind}",),
                    files=(),
                    created_at_epoch=mtime,
                    token_estimate=estimate_tokens(clean),
                    score=0.0,
                    content=clean,
                )
            )
    return blocks


async def gather_candidates(store: ProjectMemoryStore, work_dir: HostPath) -> list[RankedBlock]:
    now = time.time()
    blocks: list[RankedBlock] = []
    blocks += _entries_to_blocks(
        await store.read_entries("memory"), tier="memory", source_path="MEMORY.md", mtime=now
    )
    blocks += _entries_to_blocks(
        await store.read_entries("user"), tier="user", source_path="USER.md", mtime=now
    )
    blocks += _entries_to_blocks(
        await store._read_journal(),  # pyright: ignore[reportPrivateUsage]
        tier="journal",
        source_path="JOURNAL.md",
        mtime=now,
    )
    blocks += _scratch_note_blocks(work_dir)
    return blocks


def _last_user_text(history: Sequence[Message]) -> str:
    for msg in reversed(list(history)):
        if getattr(msg, "role", None) != "user":
            continue
        texts = [part.text for part in msg.content if isinstance(part, TextPart)]
        joined = " ".join(text for text in texts if text)
        if joined.strip():
            return joined
    return ""


class RecallInjectionProvider(DynamicInjectionProvider):
    """Replaces the verbatim project-memory dump with relevance-ranked recall."""

    def __init__(self, store: ProjectMemoryStore, session: Any) -> None:
        self._store = store
        self._session = session
        self._injected = False

    async def get_injections(
        self, history: Sequence[Message], soul: PythinkerSoul
    ) -> list[DynamicInjection]:
        _ = soul
        if self._injected:
            return []
        self._injected = True
        try:
            work_dir = cast(HostPath, self._session.work_dir)
            candidates = await gather_candidates(self._store, work_dir)
            open_todos: list[tuple[str, list[str]]] = []
            try:
                sessions_dir = cast(Path, self._session.work_dir_meta.sessions_dir)
                open_todos = find_recent_open_root_todos(
                    sessions_dir, current_session_id=str(self._session.id)
                )
            except Exception:
                logger.debug("recall: open-todo discovery failed")
            query = RecallQuery(
                text=_last_user_text(history),
                labels=tuple(title for _label, items in open_todos for title in items),
            )
            store_root = await self._store._ensure_dir()  # pyright: ignore[reportPrivateUsage]
            block = await build_recall_block(
                candidates=candidates,
                query=query,
                open_todos=open_todos,
                budget_tokens=INJECTION_BUDGET_BYTES // 4,
                store_path=str(store_root / "memory"),
            )
        except Exception:
            logger.debug("recall: snapshot failed")
            return []
        if not block.strip():
            return []
        return [DynamicInjection(type=_RECALL_TYPE, content=block)]

    async def on_context_compacted(self) -> None:
        self._injected = False

    def rearm(self, key: str) -> bool:
        if key != _RECALL_TYPE:
            return False
        self._injected = False
        return True
