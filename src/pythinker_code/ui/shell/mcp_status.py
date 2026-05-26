from __future__ import annotations

import time

from prompt_toolkit.formatted_text import FormattedText
from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from pythinker_code.ui.shell.components.render_utils import sanitize_ansi
from pythinker_code.ui.shell.motion import reduced_motion_enabled
from pythinker_code.ui.theme import get_mcp_prompt_colors, tui_rich_style
from pythinker_code.wire.types import MCPServerSnapshot, MCPStatusSnapshot

_STARTING_STATUSES = frozenset({"pending", "connecting"})


def _safe_text(text: str) -> str:
    return sanitize_ansi(text).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def mcp_startup_header(snapshot: MCPStatusSnapshot) -> str | None:
    """Return the Pythinker-X-style startup header for an MCP loading snapshot."""
    if not snapshot.loading:
        return None

    servers = tuple(snapshot.servers)
    if not servers:
        return "Starting MCP servers"

    total = max(snapshot.total, len(servers))
    starting = sorted(
        _safe_text(server.name) for server in servers if server.status in _STARTING_STATUSES
    )

    if not starting:
        completed = min(
            total,
            sum(1 for server in servers if server.status not in _STARTING_STATUSES),
        )
        if total <= 1:
            return f"Booting MCP server: {_safe_text(servers[0].name)}"
        return f"Starting MCP servers ({completed}/{total})"

    if total <= 1:
        return f"Booting MCP server: {starting[0]}"

    completed = max(0, total - len(starting))
    shown = starting[:3]
    if len(starting) > 3:
        shown.append("…")
    return f"Starting MCP servers ({completed}/{total}): {', '.join(shown)}"


def render_mcp_startup_text(snapshot: MCPStatusSnapshot, *, now: float | None = None) -> Text:
    """Render the animated MCP startup status used by live prompt/status areas."""
    t = time.monotonic() if now is None else now
    glyph = "●" if reduced_motion_enabled() or int(t / 0.8) % 2 == 0 else " "
    line = Text(f"{glyph} ", style=tui_rich_style("muted"))
    line.append(
        mcp_startup_header(snapshot) or "Starting MCP servers",
        style=tui_rich_style("muted"),
    )
    return line


def render_mcp_console(snapshot: MCPStatusSnapshot) -> RenderableType:
    if snapshot.loading:
        return render_mcp_inventory_loading()

    renderables: list[RenderableType] = [
        Text("/mcp", style=tui_rich_style("accent")),
        Text(""),
        Text.assemble("🔌  ", ("MCP Tools", "bold")),
        Text(""),
    ]

    servers = sorted(snapshot.servers, key=lambda server: server.name)
    if not servers:
        renderables.append(Text("  • No MCP servers configured.", style=Style(italic=True)))
        renderables.append(
            Text("    See the MCP docs to configure them.", style=tui_rich_style("muted"))
        )
        return Group(*renderables)

    if snapshot.tools == 0:
        renderables.append(Text("  • No MCP tools available.", style=Style(italic=True)))
        renderables.append(Text(""))

    for server in servers:
        renderables.extend(_server_inventory_lines(server))
        renderables.append(Text(""))

    return Group(*renderables)


def render_mcp_inventory_loading(*, now: float | None = None) -> RenderableType:
    t = time.monotonic() if now is None else now
    glyph = "●" if reduced_motion_enabled() or int(t / 0.8) % 2 == 0 else " "
    line = Text(f"{glyph} ", style=tui_rich_style("muted"))
    line.append("Loading MCP inventory", style=tui_rich_style("tool_title") + Style(bold=True))
    line.append("…", style=tui_rich_style("muted"))
    return line


def _server_inventory_lines(server: MCPServerSnapshot) -> list[RenderableType]:
    status = _safe_text(server.status)
    status_style = _status_color(server.status)
    server_name = _safe_text(server.name)
    lines: list[RenderableType] = [Text.assemble("  • ", (server_name, status_style))]
    lines.append(Text.assemble("    • Status: ", (status, status_style)))

    if server.status == "unauthorized":
        lines.append(
            Text(
                f"    • Auth: Not authorized - run: pythinker mcp auth {server_name}",
                style=tui_rich_style("muted"),
            )
        )

    tool_names = sorted(_safe_text(tool_name) for tool_name in server.tools)
    if tool_names:
        lines.append(Text.assemble("    • Tools: ", ", ".join(tool_names)))
    else:
        lines.append(Text("    • Tools: (none)"))

    return lines


def render_mcp_prompt(snapshot: MCPStatusSnapshot, *, now: float | None = None) -> FormattedText:
    header = mcp_startup_header(snapshot)
    if header is None:
        return FormattedText([])

    colors = get_mcp_prompt_colors()
    t = time.monotonic() if now is None else now
    prefix = f"{'●' if int(t / 0.8) % 2 == 0 else ' '} "
    return FormattedText([(colors.text, f"{prefix}{header}"), ("", "\n")])


def _status_color(status: str) -> Style:
    return {
        "connected": tui_rich_style("success"),
        "connecting": tui_rich_style("info"),
        "pending": tui_rich_style("warning"),
        "failed": tui_rich_style("error"),
        "unauthorized": tui_rich_style("error"),
    }.get(status, tui_rich_style("error"))
