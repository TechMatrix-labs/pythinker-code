from __future__ import annotations

from pathlib import Path

from pythinker_host.path import HostPath

from pythinker_code.scratchpad import GitResult


def _hp(p: Path) -> HostPath:
    return HostPath.unsafe_from_local_path(p)


class FakeGit:
    """Scriptable git runner: maps an argv prefix to a GitResult."""

    def __init__(self, responses: dict[tuple[str, ...], GitResult]):
        self.responses = responses
        self.calls: list[list[str]] = []

    async def __call__(self, argv: list[str]) -> GitResult:
        self.calls.append(argv)
        for prefix, result in self.responses.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return result
        return GitResult(ok=True, exit_code=1, stdout="")


async def test_project_key_prefers_normalized_remote(tmp_path):
    from pythinker_code.project_memory import project_key

    fake = FakeGit(
        {("remote", "get-url", "origin"): GitResult(True, 0, "https://x:y@GitHub.com/Foo/Bar.git/")}
    )
    key1 = await project_key(_hp(tmp_path), git_runner=fake)
    fake2 = FakeGit(
        {("remote", "get-url", "origin"): GitResult(True, 0, "git@github.com:foo/bar.git")}
    )
    key2 = await project_key(_hp(tmp_path / "other"), git_runner=fake2)
    assert key1.startswith("bar-")
    assert len(key1.split("-")[-1]) == 12
    assert key2.startswith("bar-")


async def test_project_key_falls_back_to_toplevel_then_workdir(tmp_path):
    from pythinker_code.project_memory import project_key

    top = tmp_path / "repo"
    top.mkdir()
    fake = FakeGit(
        {
            ("remote", "get-url", "origin"): GitResult(True, 1, ""),
            ("rev-parse", "--show-toplevel"): GitResult(True, 0, str(top)),
        }
    )
    key = await project_key(_hp(tmp_path), git_runner=fake)
    assert key.startswith("repo-")

    fake_nongit = FakeGit(
        {
            ("remote", "get-url", "origin"): GitResult(True, 128, ""),
            ("rev-parse", "--show-toplevel"): GitResult(True, 128, ""),
        }
    )
    key2 = await project_key(_hp(top), git_runner=fake_nongit)
    assert key2.startswith("repo-")


async def test_project_key_never_raises_on_git_failure(tmp_path):
    from pythinker_code.project_memory import project_key

    class Boom:
        async def __call__(self, argv):
            raise RuntimeError("git exploded")

    key = await project_key(_hp(tmp_path), git_runner=Boom())
    assert key
