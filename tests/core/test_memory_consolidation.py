from __future__ import annotations

from pathlib import Path

from pythinker_host.path import HostPath

from pythinker_code.memory.consolidation import (
    approve_inbox_candidate,
    generate_inbox_candidates,
    list_inbox_candidates,
    reject_inbox_candidate,
)
from pythinker_code.project_memory import ProjectMemoryStore


def _hp(p: Path) -> HostPath:
    return HostPath.unsafe_from_local_path(p)


async def test_memory_inbox_scan_approve_and_reject(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path / "share"))
    monkeypatch.setattr("pythinker_code.scratchpad._is_local_host", lambda: True)
    monkeypatch.setattr("pythinker_code.scratchpad._is_verified", lambda wd: True)
    from pythinker_code.scratchpad import append_scratch_note

    wd = _hp(tmp_path / "repo")
    await append_scratch_note(wd, kind="decision", content="consolidate this", session_id="s1")
    store = ProjectMemoryStore(wd)

    created = await generate_inbox_candidates(store, wd)
    assert len(created) == 1
    assert (await list_inbox_candidates(store))[0].content == "consolidate this"

    message = await approve_inbox_candidate(store, created[0].id)
    assert "approved" in message
    assert any("consolidate this" in entry for entry in await store.read_entries("memory"))
    assert await list_inbox_candidates(store) == []

    await append_scratch_note(wd, kind="decision", content="reject this", session_id="s1")
    created = await generate_inbox_candidates(store, wd)
    reject = next(candidate for candidate in created if "reject this" in candidate.content)
    assert "rejected" in await reject_inbox_candidate(store, reject.id)
