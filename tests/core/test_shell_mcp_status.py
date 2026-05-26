from __future__ import annotations

from rich.console import Console

from pythinker_code.ui.shell.mcp_status import (
    mcp_startup_header,
    render_mcp_console,
    render_mcp_prompt,
    render_mcp_startup_text,
)
from pythinker_code.wire.types import MCPServerSnapshot, MCPStatusSnapshot


def test_render_mcp_servers_shows_pythinker_x_loading_design() -> None:
    snapshot = MCPStatusSnapshot(
        loading=True,
        connected=0,
        total=2,
        tools=1,
        servers=(
            MCPServerSnapshot(
                name="context7",
                status="connecting",
                tools=("resolve-library-id",),
            ),
            MCPServerSnapshot(
                name="chrome-devtools",
                status="pending",
                tools=(),
            ),
        ),
    )

    console = Console(record=True, force_terminal=False, width=120)
    console.print(render_mcp_console(snapshot))
    output = console.export_text()

    assert "Loading MCP inventory" in output
    assert "MCP Servers:" not in output

    assert mcp_startup_header(snapshot) == ("Starting MCP servers (0/2): chrome-devtools, context7")
    prompt_text = "".join(fragment[1] for fragment in render_mcp_prompt(snapshot, now=0.0))
    prompt_text_off = "".join(fragment[1] for fragment in render_mcp_prompt(snapshot, now=0.9))
    assert prompt_text != prompt_text_off
    assert prompt_text.startswith("● ")
    assert "Starting MCP servers (0/2): chrome-devtools, context7" in prompt_text
    assert "resolve-library-id" not in prompt_text

    startup_text = render_mcp_startup_text(snapshot, now=0.0).plain
    assert startup_text == "● Starting MCP servers (0/2): chrome-devtools, context7"


def test_render_mcp_startup_header_for_single_server() -> None:
    snapshot = MCPStatusSnapshot(
        loading=True,
        connected=0,
        total=1,
        tools=0,
        servers=(MCPServerSnapshot(name="slow-test", status="pending", tools=()),),
    )

    assert mcp_startup_header(snapshot) == "Booting MCP server: slow-test"
    prompt_text = "".join(fragment[1] for fragment in render_mcp_prompt(snapshot, now=0.0))
    assert "Booting MCP server: slow-test" in prompt_text


def test_render_mcp_console_treats_server_and_tool_names_as_literal_text() -> None:
    snapshot = MCPStatusSnapshot(
        loading=False,
        connected=1,
        total=1,
        tools=1,
        servers=(
            MCPServerSnapshot(
                name="[red]evil[/red]",
                status="connected",
                tools=("[bold]tool[/bold]\x1b[31m",),
            ),
        ),
    )

    console = Console(record=True, force_terminal=False, width=120)
    console.print(render_mcp_console(snapshot))
    output = console.export_text()

    assert "[red]evil[/red]" in output
    assert "[bold]tool[/bold]" in output
    assert "\x1b" not in output


def test_render_mcp_servers_shows_pythinker_x_inventory_layout() -> None:
    snapshot = MCPStatusSnapshot(
        loading=False,
        connected=1,
        total=2,
        tools=2,
        servers=(
            MCPServerSnapshot(
                name="context7",
                status="connected",
                tools=("resolve-library-id", "query-docs"),
            ),
            MCPServerSnapshot(
                name="chrome-devtools",
                status="failed",
                tools=(),
            ),
        ),
    )

    console = Console(record=True, force_terminal=False, width=120)
    console.print(render_mcp_console(snapshot))
    output = console.export_text()

    assert "/mcp" in output
    assert "🔌  MCP Tools" in output
    assert "context7" in output
    assert "Status: connected" in output
    assert "Tools: query-docs, resolve-library-id" in output
    assert "chrome-devtools" in output
    assert "Status: failed" in output
    assert "Tools: (none)" in output
    assert "MCP Servers:" not in output

    prompt_text = "".join(fragment[1] for fragment in render_mcp_prompt(snapshot, now=0.0))
    assert prompt_text == ""
