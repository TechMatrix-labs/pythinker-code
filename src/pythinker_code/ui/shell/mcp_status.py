from __future__ import annotations

import time

from prompt_toolkit.formatted_text import FormattedText
from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from pythinker_code.ui.shell.components.render_utils import sanitize_ansi
from pythinker_code.ui.shell.motion import reduced_motion_enabled
from pythinker_code.ui.theme import get_mcp_prompt_colors, tui_rich_style
from pythinker_code.utils.rich.columns import BulletColumns
from pythinker_code.wire.types import MCPServerSnapshot, MCPStatusSnapshot


def _safe_text(text: str) -> str:
    return sanitize_ansi(text).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def render_mcp_console(snapshot: MCPStatusSnapshot) -> RenderableType:
    header_text = Text.assemble(
        ("MCP Servers: ", "bold"),
        f"{snapshot.connected}/{snapshot.total} connected, {snapshot.tools} tools",
    )
    if snapshot.loading:
        glyph = "●" if reduced_motion_enabled() or int(time.monotonic() / 0.8) % 2 == 0 else " "
        header = Text(f"{glyph} ", style=tui_rich_style("muted"))
        header.append_text(header_text)
    else:
        header = header_text

    renderables: list[RenderableType] = [BulletColumns(header)]
    for server in snapshot.servers:
        color = _status_color(server.status)
        server_name = _safe_text(server.name)
        server_status = _safe_text(server.status)
        server_line = Text(server_name, style=color)
        if server.status == "unauthorized":
            server_line.append(
                f" (unauthorized - run: pythinker mcp auth {server_name})",
                style=tui_rich_style("muted"),
            )
        elif server.status != "connected":
            server_line.append(f" ({server_status})", style=tui_rich_style("muted"))

        lines: list[RenderableType] = [server_line]
        for tool_name in server.tools:
            lines.append(
                BulletColumns(
                    Text(_safe_text(tool_name), style=tui_rich_style("muted")),
                    bullet_style=tui_rich_style("muted"),
                )
            )
        renderables.append(BulletColumns(Group(*lines), bullet_style=color))

    return Group(*renderables)


def render_mcp_prompt(snapshot: MCPStatusSnapshot, *, now: float | None = None) -> FormattedText:
    if not snapshot.loading:
        return FormattedText([])

    fragments: list[tuple[str, str]] = []
    colors = get_mcp_prompt_colors()
    t = time.monotonic() if now is None else now
    prefix = f"{'●' if int(t / 0.8) % 2 == 0 else ' '} "
    fragments.append(
        (
            colors.text,
            (
                f"{prefix}MCP Servers: "
                f"{snapshot.connected}/{snapshot.total} connected, {snapshot.tools} tools"
            ),
        )
    )
    fragments.append(("", "\n"))

    for server in snapshot.servers:
        fragments.append((_prompt_status_style(server.status), f"• {_safe_text(server.name)}"))
        detail = _prompt_server_detail(server)
        if detail:
            fragments.append((colors.detail, detail))
        fragments.append(("", "\n"))

    return FormattedText(fragments)


def _status_color(status: str) -> Style:
    return {
        "connected": tui_rich_style("success"),
        "connecting": tui_rich_style("info"),
        "pending": tui_rich_style("warning"),
        "failed": tui_rich_style("error"),
        "unauthorized": tui_rich_style("error"),
    }.get(status, tui_rich_style("error"))


def _prompt_status_style(status: str) -> str:
    colors = get_mcp_prompt_colors()
    return {
        "connected": colors.connected,
        "connecting": colors.connecting,
        "pending": colors.pending,
        "failed": colors.failed,
        "unauthorized": colors.failed,
    }.get(status, colors.failed)


def _prompt_server_detail(server: MCPServerSnapshot) -> str:
    if server.status == "unauthorized":
        return f" (unauthorized - run: pythinker mcp auth {_safe_text(server.name)})"

    parts: list[str] = []
    if server.status != "connected":
        parts.append(_safe_text(server.status))
    if server.tools:
        label = "tool" if len(server.tools) == 1 else "tools"
        parts.append(f"{len(server.tools)} {label}")

    return f" ({', '.join(parts)})" if parts else ""
