from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from pythinker_host.path import HostPath

from pythinker_code.scratchpad import GitResult


def _hp(p: Path) -> HostPath:
    return HostPath.unsafe_from_local_path(p)


class FakeGit:
    def __init__(self, responses):
        self.responses = responses

    async def __call__(self, argv):
        for prefix, result in self.responses.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return result
        return GitResult(ok=True, exit_code=1, stdout="")


def _runtime(tmp_path, role="root"):
    session = SimpleNamespace(id="sess1", title="t", work_dir=_hp(tmp_path / "repo"))
    return SimpleNamespace(role=role, session=session, rearmed=[], rearm_injection=lambda key: None)


def _make_tool(tmp_path, monkeypatch, role="root"):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path / "share"))
    from pythinker_code.project_memory import ProjectMemoryStore
    from pythinker_code.tools.memory import Memory

    tool = Memory(cast(Any, _runtime(tmp_path, role)))
    fake = FakeGit({("rev-parse", "--show-toplevel"): GitResult(True, 0, str(tmp_path / "repo"))})
    tool._store = ProjectMemoryStore(_hp(tmp_path / "repo"), git_runner=fake)
    return tool


async def test_memory_tool_add_and_read_back(tmp_path, monkeypatch):
    from pythinker_code.tools.memory import Params

    tool = _make_tool(tmp_path, monkeypatch)
    calls: list[str] = []
    tool._runtime.rearm_injection = calls.append
    res = await tool(Params(action="add", target="memory", content="uses pytest"))
    assert res.is_error is False
    assert await tool._store.read_entries("memory") == ["uses pytest"]
    assert calls == ["project_memory"]


async def test_memory_tool_missing_content_errors(tmp_path, monkeypatch):
    from pythinker_code.tools.memory import Params

    tool = _make_tool(tmp_path, monkeypatch)
    res = await tool(Params(action="add", target="memory", content=None))
    assert res.is_error is True


async def test_memory_tool_blocks_subagent(tmp_path, monkeypatch):
    from pythinker_code.tools.memory import Params

    tool = _make_tool(tmp_path, monkeypatch, role="subagent")
    res = await tool(Params(action="add", target="memory", content="x"))
    assert res.is_error is True
    assert "root" in res.message.lower()
