from __future__ import annotations

from pathlib import Path

import pytest
from pythinker_host.path import HostPath

from pythinker_code import scratchpad
from pythinker_code.scratchpad import append_scratch_note, scratch_dir


def _hp(p: Path) -> HostPath:
    return HostPath.unsafe_from_local_path(p)


@pytest.fixture(autouse=True)
def _reset_verified_work_dirs():
    scratchpad._VERIFIED_WORK_DIRS.clear()
    yield
    scratchpad._VERIFIED_WORK_DIRS.clear()


async def test_append_note_writes_parseable_block(tmp_path, monkeypatch):
    monkeypatch.setattr("pythinker_code.scratchpad._is_local_host", lambda: True)
    monkeypatch.setattr("pythinker_code.scratchpad._is_verified", lambda wd: True)

    wd = _hp(tmp_path)
    res = await append_scratch_note(
        wd,
        kind="decision",
        content="Chose lexical retriever.\nNo embeddings in the bundle.",
        session_id="abc12345-0000",
        session_title="memory work",
        labels=["file:src/x.py"],
    )
    assert res.appended is True

    files = list((scratch_dir(wd)).glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "### decision —" in text
    assert "kind:decision" in text
    assert "source: agent" in text
    assert "No embeddings in the bundle." in text


async def test_append_note_caps_oversize_body(tmp_path, monkeypatch):
    monkeypatch.setattr("pythinker_code.scratchpad._is_local_host", lambda: True)
    monkeypatch.setattr("pythinker_code.scratchpad._is_verified", lambda wd: True)
    wd = _hp(tmp_path)
    res = await append_scratch_note(
        wd, kind="note", content="x" * 10_000, session_id="abc12345-0000"
    )
    assert res.appended is True
    text = list((scratch_dir(wd)).glob("*.md"))[0].read_text(encoding="utf-8")
    assert text.count("x") <= 2100


async def test_append_note_caps_total_file_size(tmp_path, monkeypatch):
    monkeypatch.setattr("pythinker_code.scratchpad._is_local_host", lambda: True)
    monkeypatch.setattr("pythinker_code.scratchpad._is_verified", lambda wd: True)
    wd = _hp(tmp_path)
    for index in range(80):
        res = await append_scratch_note(
            wd, kind="note", content=f"note {index}\n" + ("x" * 2000), session_id="abc12345-0000"
        )
        assert res.appended is True
    file = list((scratch_dir(wd)).glob("*.md"))[0]
    assert len(file.read_bytes()) <= scratchpad._MAX_SCRATCH_BYTES
