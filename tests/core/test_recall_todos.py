from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pythinker_code.memory.recall import find_recent_open_root_todos


def _write_state(sessions_dir: Path, sid: str, todos, *, archived=False, age_s=0.0):
    directory = sessions_dir / sid
    directory.mkdir(parents=True, exist_ok=True)
    state = {"version": 1, "archived": archived, "todos": todos}
    (directory / "state.json").write_text(json.dumps(state), encoding="utf-8")
    when = time.time() - age_s
    os.utime(directory / "state.json", (when, when))


async def test_finds_open_todos_excluding_current_and_done(tmp_path):
    sessions = tmp_path / "sessions"
    _write_state(sessions, "current0", [{"title": "live", "status": "pending"}])
    _write_state(
        sessions,
        "prior111",
        [
            {"title": "wire retriever", "status": "in_progress"},
            {"title": "ship it", "status": "done"},
        ],
    )
    out = find_recent_open_root_todos(sessions, current_session_id="current0")
    titles = [title for _, items in out for title in items]
    assert "wire retriever" in titles
    assert "ship it" not in titles
    assert "live" not in titles


async def test_skips_archived_and_too_old(tmp_path):
    sessions = tmp_path / "sessions"
    _write_state(
        sessions, "arch0000", [{"title": "archived task", "status": "pending"}], archived=True
    )
    _write_state(
        sessions, "old00000", [{"title": "old task", "status": "pending"}], age_s=40 * 86400
    )
    out = find_recent_open_root_todos(sessions, current_session_id="x", max_age_days=30)
    titles = [title for _, items in out for title in items]
    assert titles == []
