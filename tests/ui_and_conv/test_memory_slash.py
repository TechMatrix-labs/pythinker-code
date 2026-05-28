from __future__ import annotations

from collections.abc import Awaitable
from types import SimpleNamespace
from typing import Any

from pythinker_host.path import HostPath


def test_memory_command_is_registered():
    from pythinker_code.ui.shell import slash

    assert slash.registry.find_command("memory") is not None
    assert slash.registry.find_command("mem") is not None


def _fake_soul(tmp_path, *, consolidation: bool) -> SimpleNamespace:
    return SimpleNamespace(
        runtime=SimpleNamespace(
            config=SimpleNamespace(memory=SimpleNamespace(consolidation=consolidation)),
            session=SimpleNamespace(work_dir=HostPath.unsafe_from_local_path(tmp_path)),
            rearm_injection=None,
        )
    )


async def _run(args: str, app: Any) -> None:
    from pythinker_code.ui.shell import slash

    cmd = slash.registry.find_command("memory")
    assert cmd is not None
    ret = cmd.func(app, args)
    if isinstance(ret, Awaitable):
        await ret


async def test_memory_inbox_disabled_short_circuits(tmp_path, monkeypatch, capsys):
    """With memory.consolidation off, `/memory inbox` must not stage anything."""
    from pythinker_code.ui.shell import slash

    monkeypatch.setattr(
        slash, "ensure_pythinker_soul", lambda app: _fake_soul(tmp_path, consolidation=False)
    )

    called = {"scan": False}

    async def _boom(*args, **kwargs):
        called["scan"] = True
        return []

    monkeypatch.setattr("pythinker_code.memory.consolidation.generate_inbox_candidates", _boom)

    await _run("inbox scan", SimpleNamespace())
    out = capsys.readouterr().out.lower()
    assert "disabled" in out
    assert called["scan"] is False


async def test_memory_inbox_enabled_invokes_scan(tmp_path, monkeypatch, capsys):
    """With the flag on, `/memory inbox scan` reaches the consolidation path."""
    from pythinker_code.ui.shell import slash

    monkeypatch.setattr(
        slash, "ensure_pythinker_soul", lambda app: _fake_soul(tmp_path, consolidation=True)
    )

    called = {"scan": False}

    async def _spy(*args, **kwargs):
        called["scan"] = True
        return []

    monkeypatch.setattr("pythinker_code.memory.consolidation.generate_inbox_candidates", _spy)

    await _run("inbox scan", SimpleNamespace())
    assert called["scan"] is True
