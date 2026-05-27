"""Tests for Sentry/Bugsink export filters."""

from __future__ import annotations

from typing import cast

from sentry_sdk.types import Event, Hint

from pythinker_code.telemetry.config import is_disabled, is_enabled, is_test_environment
from pythinker_code.telemetry.sentry import _before_send  # pyright: ignore[reportPrivateUsage]


def test_external_telemetry_disabled_under_pytest() -> None:
    assert is_test_environment() is True
    assert is_disabled() is True


def test_external_telemetry_is_on_by_default(monkeypatch) -> None:
    monkeypatch.setenv("PYTHINKER_FORCE_TELEMETRY_IN_TESTS", "1")
    monkeypatch.delenv("PYTHINKER_DISABLE_TELEMETRY", raising=False)
    # On by default outside the explicit kill switch / pytest guard.
    assert is_disabled() is False

    # Explicit kill switch opts out.
    monkeypatch.setenv("PYTHINKER_DISABLE_TELEMETRY", "1")
    assert is_disabled() is True


def test_is_enabled_combines_toml_and_kill_switch(monkeypatch) -> None:
    """``is_enabled`` is the single gate shared by app startup and the SDK inits.

    Telemetry is on by default; the gate is False only when the TOML setting
    opts out or the kill switch / pytest guard disables emission. Keeping app
    startup and the SDK initializers on this one gate prevents the EventSink
    from being attached while the exporters refuse to initialize.
    """
    monkeypatch.setenv("PYTHINKER_FORCE_TELEMETRY_IN_TESTS", "1")
    monkeypatch.delenv("PYTHINKER_DISABLE_TELEMETRY", raising=False)

    # Default TOML setting + no kill switch -> enabled.
    assert is_enabled(config_telemetry=True) is True
    # TOML opt-out wins even with telemetry on by default.
    assert is_enabled(config_telemetry=False) is False

    # Explicit kill switch disables regardless of the TOML setting.
    monkeypatch.setenv("PYTHINKER_DISABLE_TELEMETRY", "1")
    assert is_enabled(config_telemetry=True) is False


def test_before_send_drops_test_frame_events() -> None:
    event = {
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": "boom",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "tests/telemetry/test_crash.py",
                                "abs_path": "/home/user/project/tests/telemetry/test_crash.py",
                            }
                        ]
                    },
                }
            ]
        }
    }

    assert _before_send(cast(Event, event), cast(Hint, {})) is None


def test_before_send_drops_normal_queue_shutdown_events() -> None:
    event = {
        "exception": {
            "values": [
                {
                    "module": "asyncio.queues",
                    "type": "QueueShutDown",
                    "value": "",
                }
            ]
        }
    }

    assert _before_send(cast(Event, event), cast(Hint, {})) is None
