from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest

from pythinker_host import reset_current_host, set_current_host
from pythinker_host.local import LocalHost
from pythinker_host.path import HostPath


@pytest.fixture
def host_cwd(tmp_path: Path) -> Generator[HostPath]:
    """Set LocalHost as the current Host and switch cwd to a temp directory."""
    token = set_current_host(LocalHost())
    old_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        yield HostPath.unsafe_from_local_path(tmp_path)
    finally:
        os.chdir(old_cwd)
        reset_current_host(token)


def test_join_and_parent(host_cwd: HostPath):
    base = HostPath("folder")
    child = base / "data.txt"

    assert str(child) == str(Path("folder") / "data.txt")
    assert child.parent == HostPath("folder")
    assert child.name == "data.txt"
    assert not child.is_absolute()


def test_home_and_cwd(host_cwd: HostPath):
    assert str(HostPath.home()) == str(Path.home())
    assert str(HostPath.cwd()) == str(host_cwd)


def test_expanduser(host_cwd: HostPath):
    home = HostPath.home()
    assert str(HostPath("~").expanduser()) == str(home)
    assert str(HostPath("~/docs").expanduser()) == str(home / "docs")


def test_canonical_and_relative_to(host_cwd: HostPath):
    canonical = HostPath("nested/../file.txt").canonical()
    assert str(canonical) == str(host_cwd / "file.txt")

    base = HostPath(str(host_cwd / "base"))
    child = base / "inner" / "note.txt"
    relative = child.relative_to(base)
    assert str(relative) == str(HostPath("inner") / "note.txt")


async def test_exists_and_file_ops(host_cwd: HostPath):
    file_path = HostPath("log.txt")
    assert not await file_path.exists()

    await file_path.write_text("hello")
    assert await file_path.exists()
    assert await file_path.is_file()
    assert not await file_path.is_dir()

    await file_path.append_text("\nworld")
    assert await file_path.read_text() == "hello\nworld"

    dir_path = HostPath("logs")
    await dir_path.mkdir()
    assert await dir_path.exists()
    assert await dir_path.is_dir()


async def test_iterdir_and_glob_from_host_path(host_cwd: HostPath):
    base_dir = HostPath("data")
    await base_dir.mkdir()

    await (base_dir / "one.txt").write_text("1")
    await (base_dir / "two.md").write_text("2")
    await (base_dir / "three.txt").write_text("3")

    entries = [entry.name async for entry in base_dir.iterdir()]
    assert set(entries) == {"one.txt", "two.md", "three.txt"}

    globbed = [entry.name async for entry in base_dir.glob("*.txt")]
    assert set(globbed) == {"one.txt", "three.txt"}


async def test_read_write_bytes(host_cwd: HostPath):
    file_path = HostPath("data.bin")
    await file_path.write_bytes(b"\x00\x01\xff")
    assert await file_path.read_bytes() == b"\x00\x01\xff"
