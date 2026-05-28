from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

from pythinker_host.path import HostPath

from pythinker_code.memory.recall import build_recall_block
from pythinker_code.memory.retriever import RankedBlock, RecallQuery, estimate_tokens


def _block(content: str) -> RankedBlock:
    return RankedBlock(
        tier="memory",
        source_path="MEMORY.md",
        source_id=None,
        session_id=None,
        title="t",
        labels=(),
        files=(),
        created_at_epoch=time.time(),
        token_estimate=estimate_tokens(content),
        score=1.0,
        content=content,
    )


def _hp(p: Path) -> HostPath:
    return HostPath.unsafe_from_local_path(p)


async def test_build_recall_block_includes_open_todos_and_facts():
    block = await build_recall_block(
        candidates=[_block("use the lexical retriever")],
        query=RecallQuery(text="retriever"),
        open_todos=[("prior session", ["wire the retriever"])],
        budget_tokens=1000,
        store_path="/tmp/x/memory",
    )
    assert "use the lexical retriever" in block
    assert "wire the retriever" in block
    assert "prior session" in block


async def test_build_recall_block_empty_when_nothing():
    block = await build_recall_block(
        candidates=[],
        query=RecallQuery(text="x"),
        open_todos=[],
        budget_tokens=1000,
        store_path="/tmp/x/memory",
    )
    assert block == ""


async def test_build_recall_block_open_todos_only_does_not_suggest_missing_files():
    block = await build_recall_block(
        candidates=[],
        query=RecallQuery(text="x"),
        open_todos=[("prior", ["finish review"])],
        budget_tokens=1000,
        store_path="/tmp/x/memory",
    )
    assert "finish review" in block
    assert "/tmp/x/memory" not in block
    assert "MEMORY.md" not in block
    assert "USER.md" not in block


async def test_gather_candidates_includes_scratch_notes(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path / "share"))
    monkeypatch.setattr("pythinker_code.scratchpad._is_local_host", lambda: True)
    monkeypatch.setattr("pythinker_code.scratchpad._is_verified", lambda wd: True)
    from pythinker_code.memory.recall import gather_candidates
    from pythinker_code.project_memory import ProjectMemoryStore
    from pythinker_code.scratchpad import append_scratch_note

    wd = _hp(tmp_path)
    await append_scratch_note(
        wd, kind="decision", content="use bm25 ranking", session_id="s0000000-0000"
    )
    blocks = await gather_candidates(ProjectMemoryStore(wd), wd)
    assert any("bm25" in block.content for block in blocks)


async def test_provider_injects_once_and_rearms(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path / "share"))
    monkeypatch.setattr("pythinker_code.scratchpad._is_local_host", lambda: True)
    monkeypatch.setattr("pythinker_code.scratchpad._is_verified", lambda wd: True)
    from pythinker_code.memory.recall import RecallInjectionProvider
    from pythinker_code.project_memory import ProjectMemoryStore
    from pythinker_code.scratchpad import append_scratch_note

    wd = _hp(tmp_path)
    await append_scratch_note(wd, kind="note", content="recall me bm25", session_id="s0000000-0000")

    class _Meta:
        sessions_dir = tmp_path / "sessions"

    class _Sess:
        work_dir = wd
        id = "s0000000-0000"
        title = "t"
        work_dir_meta = _Meta()

    prov = RecallInjectionProvider(ProjectMemoryStore(wd), cast(Any, _Sess()))
    first = await prov.get_injections([], cast(Any, None))
    assert first and "bm25" in first[0].content
    assert await prov.get_injections([], cast(Any, None)) == []
    await prov.on_context_compacted()
    assert await prov.get_injections([], cast(Any, None))
