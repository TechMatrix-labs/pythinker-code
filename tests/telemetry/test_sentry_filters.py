"""Tests for Sentry/Bugsink export filters."""

from __future__ import annotations

from typing import cast

from sentry_sdk.types import Event, Hint

from pythinker_code.telemetry.config import is_disabled, is_test_environment
from pythinker_code.telemetry.sentry import _before_send  # pyright: ignore[reportPrivateUsage]


def test_external_telemetry_disabled_under_pytest() -> None:
    assert is_test_environment() is True
    assert is_disabled() is True


def test_external_telemetry_is_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("PYTHINKER_FORCE_TELEMETRY_IN_TESTS", "1")
    monkeypatch.delenv("PYTHINKER_ENABLE_TELEMETRY", raising=False)
    monkeypatch.delenv("PYTHINKER_DISABLE_TELEMETRY", raising=False)
    assert is_disabled() is True

    monkeypatch.setenv("PYTHINKER_ENABLE_TELEMETRY", "1")
    assert is_disabled() is False

    monkeypatch.setenv("PYTHINKER_DISABLE_TELEMETRY", "1")
    assert is_disabled() is True


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
