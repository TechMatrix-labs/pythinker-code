"""Unit tests for ACPServer.initialize — argv handling."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pythinker_code.acp.server import ACPServer

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "argv, expected_command, expected_terminal_args",
    [
        # Standard entry-point: pythinker acp
        (["/usr/local/bin/pythinker", "acp"], "/usr/local/bin/pythinker", ["login"]),
        # pythinker-code entry-point (JetBrains scenario)
        (["/usr/local/bin/pythinker-code", "acp"], "/usr/local/bin/pythinker-code", ["login"]),
        # pythinker-code entry-point
        (["/usr/local/bin/pythinker-code", "acp"], "/usr/local/bin/pythinker-code", ["login"]),
        # Arbitrary wrapper script
        (["/opt/wrapper.sh", "acp"], "/opt/wrapper.sh", ["login"]),
    ],
    ids=["pythinker", "pythinker-code", "pythinker-code", "wrapper-script"],
)
async def test_initialize_argv_handling(
    argv: list[str],
    expected_command: str,
    expected_terminal_args: list[str],
):
    """initialize() should not crash regardless of sys.argv content."""
    server = ACPServer()

    with patch("pythinker_code.acp.server.sys") as mock_sys:
        mock_sys.argv = argv
        resp = await server.initialize(protocol_version=1)

    assert resp.protocol_version == 1
    assert resp.auth_methods is not None
    assert len(resp.auth_methods) == 1

    auth_method = resp.auth_methods[0]
    assert auth_method.field_meta is not None
    terminal_auth = auth_method.field_meta["terminal-auth"]
    assert terminal_auth["command"] == expected_command
    assert terminal_auth["args"] == expected_terminal_args
