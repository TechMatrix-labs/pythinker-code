from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Iterable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp import types as mcp_types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from pydantic import PrivateAttr
from pythinker_core.message import (
    AudioURLPart,
    ContentPart,
    ImageURLPart,
    TextPart,
    ToolCall,
    VideoURLPart,
)
from pythinker_core.tooling import (
    CallableTool,
    HandleResult,
    Tool,
    ToolError,
    ToolOk,
    ToolResult,
    ToolReturnValue,
)
from pythinker_core.tooling.error import ToolNotFoundError, ToolParseError, ToolRuntimeError
from pythinker_core.tooling.mcp import convert_mcp_content
from pythinker_core.utils.typing import JsonType

MCP_MAX_OUTPUT_CHARS = 100_000
_TOOL_NAME_MAX_LENGTH = 64
_TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _seconds_to_timedelta(seconds: float | None) -> timedelta | None:
    if seconds is None:
        return None
    return timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """Configuration for one MCP server connection."""

    name: str
    transport: Literal["stdio", "streamable_http"]
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    timeout_seconds: float | None = None
    sse_read_timeout_seconds: float | None = None
    tool_call_timeout_seconds: float | None = None

    @classmethod
    def stdio(
        cls,
        name: str,
        *,
        command: str,
        args: Iterable[str] = (),
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        tool_call_timeout_seconds: float | None = None,
    ) -> MCPServerConfig:
        """Create a stdio MCP server config."""
        return cls(
            name=name,
            transport="stdio",
            command=command,
            args=tuple(args),
            env=env,
            cwd=cwd,
            tool_call_timeout_seconds=tool_call_timeout_seconds,
        )

    @classmethod
    def streamable_http(
        cls,
        name: str,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        sse_read_timeout_seconds: float | None = None,
        tool_call_timeout_seconds: float | None = None,
    ) -> MCPServerConfig:
        """Create a streamable HTTP MCP server config."""
        return cls(
            name=name,
            transport="streamable_http",
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            sse_read_timeout_seconds=sse_read_timeout_seconds,
            tool_call_timeout_seconds=tool_call_timeout_seconds,
        )


class _MCPToolSession(Protocol):
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
    ) -> mcp_types.CallToolResult: ...


class _MCPSession(_MCPToolSession, Protocol):
    async def initialize(self) -> mcp_types.InitializeResult: ...

    async def list_tools(self, cursor: str | None = None) -> mcp_types.ListToolsResult: ...


@dataclass(slots=True)
class _ConnectedServer:
    name: str
    session: _MCPSession
    tool_call_timeout: timedelta | None


class MCPTool(CallableTool):
    """Pythinker tool wrapper for one MCP tool."""

    _server_name: str = PrivateAttr()
    _mcp_name: str = PrivateAttr()
    _mcp_tool: mcp_types.Tool = PrivateAttr()
    _session: _MCPToolSession = PrivateAttr()
    _tool_call_timeout: timedelta | None = PrivateAttr()
    _max_output_chars: int = PrivateAttr()

    def __init__(
        self,
        *,
        name: str,
        server_name: str,
        mcp_tool: mcp_types.Tool,
        session: _MCPToolSession,
        tool_call_timeout: timedelta | None = None,
        max_output_chars: int = MCP_MAX_OUTPUT_CHARS,
    ) -> None:
        description = mcp_tool.description or "No description provided."
        super().__init__(
            name=name,
            description=(
                f"MCP tool `{mcp_tool.name}` from server `{server_name}`.\n\n{description}"
            ),
            parameters=mcp_tool.inputSchema,
        )
        self._server_name = server_name
        self._mcp_name = mcp_tool.name
        self._mcp_tool = mcp_tool
        self._session = session
        self._tool_call_timeout = tool_call_timeout
        self._max_output_chars = max_output_chars

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def mcp_name(self) -> str:
        return self._mcp_name

    @property
    def mcp_tool(self) -> mcp_types.Tool:
        return self._mcp_tool

    async def __call__(self, *args: Any, **kwargs: Any) -> ToolReturnValue:
        if args:
            return ToolError(
                message="MCP tools require JSON object arguments.",
                brief="Invalid arguments",
            )
        try:
            result = await self._session.call_tool(
                self._mcp_name,
                arguments=kwargs,
                read_timeout_seconds=self._tool_call_timeout,
            )
        except Exception as exc:
            return ToolRuntimeError(str(exc))
        return mcp_tool_result_to_return_value(result, max_output_chars=self._max_output_chars)


class MCPToolset:
    """Toolset backed by one or more MCP client sessions.

    Use `async with MCPToolset.connect([...]) as tools:` so sessions and transports are
    opened, initialized, and closed deterministically.
    """

    def __init__(
        self,
        configs: Iterable[MCPServerConfig] = (),
        *,
        namespace_tools: bool = True,
        max_output_chars: int = MCP_MAX_OUTPUT_CHARS,
    ) -> None:
        self._configs = tuple(configs)
        self._namespace_tools = namespace_tools
        self._max_output_chars = max_output_chars
        self._exit_stack = AsyncExitStack()
        self._started = False
        self._connected_servers: list[_ConnectedServer] = []
        self._tool_dict: dict[str, MCPTool] = {}

    @classmethod
    def connect(
        cls,
        configs: Iterable[MCPServerConfig],
        *,
        namespace_tools: bool = True,
        max_output_chars: int = MCP_MAX_OUTPUT_CHARS,
    ) -> MCPToolset:
        """Return an async context manager that connects the configured MCP servers."""
        return cls(
            configs,
            namespace_tools=namespace_tools,
            max_output_chars=max_output_chars,
        )

    @classmethod
    async def from_session(
        cls,
        server_name: str,
        session: _MCPSession,
        *,
        namespace_tools: bool = True,
        max_output_chars: int = MCP_MAX_OUTPUT_CHARS,
        tool_call_timeout_seconds: float | None = None,
    ) -> MCPToolset:
        """Build a toolset from an already-initialized session.

        This is useful for tests and host applications that own the MCP session lifecycle.
        """
        toolset = cls(namespace_tools=namespace_tools, max_output_chars=max_output_chars)
        await toolset._register_session(
            server_name,
            session,
            tool_call_timeout=_seconds_to_timedelta(tool_call_timeout_seconds),
        )
        toolset._started = True
        return toolset

    async def __aenter__(self) -> MCPToolset:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    @property
    def tools(self) -> list[Tool]:
        return [tool.base for tool in self._tool_dict.values()]

    def handle(self, tool_call: ToolCall) -> HandleResult:
        if tool_call.function.name not in self._tool_dict:
            return ToolResult(
                tool_call_id=tool_call.id,
                return_value=ToolNotFoundError(tool_call.function.name),
            )

        tool = self._tool_dict[tool_call.function.name]
        try:
            arguments: JsonType = json.loads(tool_call.function.arguments or "{}", strict=False)
        except json.JSONDecodeError as exc:
            return ToolResult(tool_call_id=tool_call.id, return_value=ToolParseError(str(exc)))

        async def _call() -> ToolResult:
            try:
                ret = await tool.call(arguments)
                return ToolResult(tool_call_id=tool_call.id, return_value=ret)
            except Exception as exc:
                return ToolResult(
                    tool_call_id=tool_call.id,
                    return_value=ToolRuntimeError(str(exc)),
                )

        return asyncio.create_task(_call())

    async def start(self) -> None:
        """Open transports, initialize sessions, and discover tools."""
        if self._started:
            return
        try:
            for config in self._configs:
                session = await self._open_session(config)
                await session.initialize()
                await self._register_session(
                    config.name,
                    session,
                    tool_call_timeout=_seconds_to_timedelta(config.tool_call_timeout_seconds),
                )
            self._started = True
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Close all MCP transports owned by this toolset."""
        self._connected_servers.clear()
        self._tool_dict.clear()
        self._started = False
        await self._exit_stack.aclose()

    async def _open_session(self, config: MCPServerConfig) -> _MCPSession:
        if config.transport == "stdio":
            if config.command is None:
                raise ValueError(f"MCP server `{config.name}` is missing a stdio command")
            server_params = StdioServerParameters(
                command=config.command,
                args=list(config.args),
                env=config.env,
                cwd=config.cwd,
            )
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            return ClientSession(read_stream, write_stream)

        if config.url is None:
            raise ValueError(f"MCP server `{config.name}` is missing a streamable HTTP URL")
        read_stream, write_stream, _get_session_id = await self._exit_stack.enter_async_context(
            streamablehttp_client(
                config.url,
                headers=config.headers,
                timeout=config.timeout_seconds or 30,
                sse_read_timeout=config.sse_read_timeout_seconds or 300,
            )
        )
        return ClientSession(read_stream, write_stream)

    async def _register_session(
        self,
        server_name: str,
        session: _MCPSession,
        *,
        tool_call_timeout: timedelta | None,
    ) -> None:
        connected_server = _ConnectedServer(
            name=server_name,
            session=session,
            tool_call_timeout=tool_call_timeout,
        )
        self._connected_servers.append(connected_server)
        tools = await _list_all_tools(session)
        for mcp_tool in tools:
            tool_name = self._deduplicated_tool_name(
                self._public_tool_name(server_name, mcp_tool.name),
                original=f"{server_name}:{mcp_tool.name}",
            )
            self._tool_dict[tool_name] = MCPTool(
                name=tool_name,
                server_name=server_name,
                mcp_tool=mcp_tool,
                session=session,
                tool_call_timeout=tool_call_timeout,
                max_output_chars=self._max_output_chars,
            )

    def _public_tool_name(self, server_name: str, tool_name: str) -> str:
        raw_name = f"{server_name}__{tool_name}" if self._namespace_tools else tool_name
        return _safe_tool_name(raw_name)

    def _deduplicated_tool_name(self, base_name: str, *, original: str) -> str:
        if base_name not in self._tool_dict:
            return base_name
        digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]
        suffix = f"_{digest}"
        candidate = f"{base_name[: _TOOL_NAME_MAX_LENGTH - len(suffix)]}{suffix}"
        if candidate not in self._tool_dict:
            return candidate
        raise ValueError(f"Duplicate MCP tool name `{base_name}` from `{original}`")


def _safe_tool_name(name: str) -> str:
    """Return a provider-safe tool name using OpenAI-compatible constraints."""
    safe = _TOOL_NAME_RE.sub("_", name).strip("_")
    if not safe:
        safe = "mcp_tool"
    if len(safe) <= _TOOL_NAME_MAX_LENGTH:
        return safe
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    suffix = f"_{digest}"
    return f"{safe[: _TOOL_NAME_MAX_LENGTH - len(suffix)]}{suffix}"


async def _list_all_tools(session: _MCPSession) -> list[mcp_types.Tool]:
    tools: list[mcp_types.Tool] = []
    cursor: str | None = None
    while True:
        result = await session.list_tools(cursor=cursor)
        tools.extend(result.tools)
        cursor = result.nextCursor
        if cursor is None:
            return tools


def mcp_tool_result_to_return_value(
    result: mcp_types.CallToolResult,
    *,
    max_output_chars: int = MCP_MAX_OUTPUT_CHARS,
) -> ToolOk | ToolError:
    """Convert an MCP tool result into a Pythinker tool return value."""
    content: list[ContentPart] = []
    budget = max_output_chars
    truncated = False

    for part in result.content:
        converted = _convert_mcp_content_part(part)
        budget, was_truncated = _append_bounded_part(content, converted, budget)
        truncated = truncated or was_truncated

    if result.structuredContent is not None:
        structured_text = json.dumps(result.structuredContent, ensure_ascii=False, sort_keys=True)
        budget, was_truncated = _append_bounded_part(
            content,
            TextPart(text=f"Structured content: {structured_text}"),
            budget,
        )
        truncated = truncated or was_truncated

    if truncated:
        content.append(
            TextPart(
                text=(
                    f"\n\n[Output truncated: exceeded {max_output_chars} character limit. "
                    "Use pagination or a more specific query to get remaining content.]"
                )
            )
        )

    if result.isError:
        return ToolError(
            output=content,
            message="MCP tool returned an error. The output may contain details.",
            brief="MCP error",
        )
    return ToolOk(output=content)


def _convert_mcp_content_part(part: mcp_types.ContentBlock) -> ContentPart:
    match part:
        case mcp_types.EmbeddedResource(
            resource=mcp_types.TextResourceContents(uri=uri, mimeType=_mime_type, text=text)
        ):
            return TextPart(text=f"{uri}:\n{text}")
        case _:
            try:
                return convert_mcp_content(part)
            except ValueError as exc:
                return TextPart(text=f"[Unsupported MCP content: {exc}]")


def _append_bounded_part(
    content: list[ContentPart],
    part: ContentPart,
    budget: int,
) -> tuple[int, bool]:
    if budget <= 0:
        return 0, True

    if isinstance(part, TextPart):
        if len(part.text) > budget:
            content.append(TextPart(text=part.text[:budget]))
            return 0, True
        content.append(part)
        return budget - len(part.text), False

    size = _media_part_size(part)
    if size is None:
        content.append(part)
        return budget, False
    if size > budget:
        return 0, True
    content.append(part)
    return budget - size, False


def _media_part_size(part: ContentPart) -> int | None:
    if isinstance(part, ImageURLPart):
        return len(part.image_url.url)
    if isinstance(part, AudioURLPart):
        return len(part.audio_url.url)
    if isinstance(part, VideoURLPart):
        return len(part.video_url.url)
    return None
