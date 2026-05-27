from __future__ import annotations

from typing import Any

import pythinker_code.utils.sleep_inhibitor as sleep_inhibitor_module
from pythinker_code.utils.sleep_inhibitor import BLOCKER_SLEEP_SECONDS, SleepInhibitor


class FakePlatformInhibitor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def acquire(self) -> None:
        self.calls.append("acquire")

    def release(self) -> None:
        self.calls.append("release")


def test_sleep_inhibitor_toggles_platform_when_enabled(monkeypatch) -> None:
    platform = FakePlatformInhibitor()
    monkeypatch.setattr(sleep_inhibitor_module, "_make_platform_inhibitor", lambda: platform)

    inhibitor = SleepInhibitor(enabled=True)
    inhibitor.set_turn_running(True)
    assert inhibitor.is_turn_running()

    inhibitor.set_turn_running(False)
    assert not inhibitor.is_turn_running()
    assert platform.calls == ["acquire", "release"]


def test_sleep_inhibitor_disabled_records_state_without_acquiring(monkeypatch) -> None:
    platform = FakePlatformInhibitor()
    monkeypatch.setattr(sleep_inhibitor_module, "_make_platform_inhibitor", lambda: platform)

    inhibitor = SleepInhibitor(enabled=False)
    inhibitor.set_turn_running(True)

    assert inhibitor.is_turn_running()
    assert platform.calls == ["release"]


def test_linux_backend_uses_long_sleep_blocker(monkeypatch) -> None:
    captured_args: list[list[str]] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(args: list[str], **_kwargs: Any) -> FakeProcess:
        captured_args.append(args)
        return FakeProcess()

    monkeypatch.setattr(sleep_inhibitor_module.subprocess, "Popen", fake_popen)

    inhibitor = sleep_inhibitor_module._LinuxSleepInhibitor()
    inhibitor.acquire()
    inhibitor.release()

    assert captured_args == [
        [
            "systemd-inhibit",
            "--what=idle",
            "--mode=block",
            "--who",
            "pythinker",
            "--why",
            "Pythinker is running an active turn",
            "--",
            "sleep",
            BLOCKER_SLEEP_SECONDS,
        ]
    ]
    assert str(2**31 - 1) == BLOCKER_SLEEP_SECONDS
