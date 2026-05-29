"""Tests for the /feedback shell slash command."""

from __future__ import annotations

from collections.abc import Awaitable
from unittest.mock import Mock

from pythinker_code.ui.shell import slash as shell_slash
from pythinker_code.ui.shell.slash import registry as shell_slash_registry
from pythinker_code.ui.shell.slash import shell_mode_registry


class TestFeedbackRegistration:
    def test_registered_in_shell_registry(self) -> None:
        cmd = shell_slash_registry.find_command("feedback")
        assert cmd is not None
        assert cmd.name == "feedback"

    def test_registered_in_shell_mode_registry(self) -> None:
        cmd = shell_mode_registry.find_command("feedback")
        assert cmd is not None


class TestFeedbackOpensIssue:
    def _run(self, fn, *args):
        ret = fn(*args)
        return ret  # sync now; no Awaitable

    def test_opens_new_issue_url(self, monkeypatch) -> None:
        open_mock = Mock(return_value=True)
        monkeypatch.setattr("webbrowser.open", open_mock)
        monkeypatch.setattr(shell_slash.console, "print", Mock())

        shell = Mock()
        ret = shell_slash.feedback(shell, "")
        assert not isinstance(ret, Awaitable)

        open_mock.assert_called_once()
        url = open_mock.call_args.args[0]
        assert "TechMatrix-labs/pythinker-code" in url
        assert "new" in url

    def test_prints_success_when_browser_opens(self, monkeypatch) -> None:
        monkeypatch.setattr("webbrowser.open", Mock(return_value=True))
        print_mock = Mock()
        monkeypatch.setattr(shell_slash.console, "print", print_mock)

        shell_slash.feedback(Mock(), "")

        output = " ".join(str(c) for c in print_mock.call_args_list)
        assert "Opening" in output or "browser" in output.lower()

    def test_prints_url_when_browser_fails(self, monkeypatch) -> None:
        monkeypatch.setattr("webbrowser.open", Mock(return_value=False))
        print_mock = Mock()
        monkeypatch.setattr(shell_slash.console, "print", print_mock)

        shell_slash.feedback(Mock(), "")

        output = " ".join(str(c) for c in print_mock.call_args_list)
        assert "TechMatrix-labs/pythinker-code" in output
