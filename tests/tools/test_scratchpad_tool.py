from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pythinker_host.path import HostPath

from pythinker_code.scratchpad import scratch_dir


def _hp(p: Path) -> HostPath:
    return HostPath.unsafe_from_local_path(p)


class _FakeSession:
    def __init__(self, work_dir: HostPath) -> None:
        self.work_dir = work_dir
        self.id = "abc12345-0000"
        self.title = "memory work"


class _FakeRuntime:
    def __init__(self, work_dir: HostPath, role: str = "root") -> None:
        self.session = _FakeSession(work_dir)
        self.role = role
        self.rearmed: list[str] = []
        self.rearm_injection = self.rearmed.append


async def test_scratchpad_tool_writes_note(tmp_path, monkeypatch):
    monkeypatch.setattr("pythinker_code.scratchpad._is_local_host", lambda: True)
    monkeypatch.setattr("pythinker_code.scratchpad._is_verified", lambda wd: True)
    from pythinker_code.tools.scratchpad import Params, Scratchpad

    runtime = _FakeRuntime(_hp(tmp_path))
    tool = Scratchpad(cast(Any, runtime))
    res = await tool(Params(action="add", kind="decision", content="picked lexical retriever"))
    assert res.__class__.__name__ == "ToolOk"
    assert runtime.rearmed == ["project_memory"]
    text = list(scratch_dir(_hp(tmp_path)).glob("*.md"))[0].read_text(encoding="utf-8")
    assert "picked lexical retriever" in text


async def test_scratchpad_tool_is_root_only(tmp_path):
    from pythinker_code.tools.scratchpad import Params, Scratchpad

    tool = Scratchpad(cast(Any, _FakeRuntime(_hp(tmp_path), role="subagent")))
    res = await tool(Params(action="add", kind="note", content="x"))
    assert res.__class__.__name__ == "ToolError"


async def test_scratchpad_tool_strips_private_and_scans(tmp_path, monkeypatch):
    monkeypatch.setattr("pythinker_code.scratchpad._is_local_host", lambda: True)
    monkeypatch.setattr("pythinker_code.scratchpad._is_verified", lambda wd: True)
    from pythinker_code.tools.scratchpad import Params, Scratchpad

    tool = Scratchpad(cast(Any, _FakeRuntime(_hp(tmp_path))))
    res = await tool(
        Params(action="add", kind="note", content="keep <private>secret</private> this")
    )
    assert res.__class__.__name__ == "ToolOk"
    text = list(scratch_dir(_hp(tmp_path)).glob("*.md"))[0].read_text(encoding="utf-8")
    assert "secret" not in text and "keep" in text
