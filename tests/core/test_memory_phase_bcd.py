from __future__ import annotations

import time
from pathlib import Path

from pythinker_core.message import Message, TextPart
from pythinker_host.path import HostPath

from pythinker_code.memory.harvest import CompactionHarvester
from pythinker_code.memory.recap import build_session_recap, content_hash
from pythinker_code.memory.retriever import RankedBlock, RecallQuery, estimate_tokens
from pythinker_code.memory.retriever_sqlite import SqliteFts5Retriever
from pythinker_code.project_memory import ProjectMemoryStore
from pythinker_code.session_state import SessionState, TodoItemState


def _hp(p: Path) -> HostPath:
    return HostPath.unsafe_from_local_path(p)


def test_content_hash_is_stable_and_normalized():
    assert content_hash(tier="memory", title="T", body="Body") == content_hash(
        tier=" MEMORY ", title="t", body=" body "
    )


async def test_append_journal_prepends_and_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path / "share"))
    store = ProjectMemoryStore(_hp(tmp_path / "repo"))
    assert (await store.append_journal("first recap")).ok is True
    assert (await store.append_journal("second recap")).ok is True
    assert (await store.append_journal("first recap")).ok is True
    assert await store._read_journal(last_n=10) == ["second recap", "first recap"]


def test_build_session_recap_has_stable_schema():
    state = SessionState(
        custom_title="memory work",
        todos=[
            TodoItemState(title="ship phase b", status="done"),
            TodoItemState(title="ship phase c", status="pending"),
        ],
    )
    recap = build_session_recap(
        state=state,
        session_id="abc12345-0000",
        request="implement memory",
        scratch_blocks=["decision: lexical first"],
        files_read=["src/x.py"],
        files_modified=["src/y.py"],
    )
    for heading in (
        "## request",
        "## investigated",
        "## learned",
        "## completed",
        "## next_steps",
        "## open_todos",
        "## files_read",
        "## files_modified",
        "## labels",
    ):
        assert heading in recap
    assert "ship phase c" in recap


def test_compaction_harvester_extracts_safe_assistant_notes():
    messages = [
        Message(
            role="assistant",
            content=[
                TextPart(
                    text="Decision: use lexical recall\nBlocker: <private>secret</private>\nNext: run tests"
                )
            ],
        ),
        Message(role="tool", content=[TextPart(text="Decision: ignore tool output")]),
    ]
    notes = CompactionHarvester().harvest(messages)
    assert [(note.kind, note.content) for note in notes] == [
        ("decision", "use lexical recall"),
        ("next", "run tests"),
    ]


async def test_sqlite_retriever_falls_back_to_lexical():
    block = RankedBlock(
        tier="memory",
        source_path="MEMORY.md",
        source_id=None,
        session_id=None,
        title="retriever",
        labels=(),
        files=(),
        created_at_epoch=time.time(),
        token_estimate=estimate_tokens("lexical sqlite fallback"),
        score=0.0,
        content="lexical sqlite fallback",
    )
    out = await SqliteFts5Retriever([block], fts5_available=False).retrieve(
        RecallQuery(text="sqlite fallback"), budget_tokens=100
    )
    assert out and out[0].content == "lexical sqlite fallback"
