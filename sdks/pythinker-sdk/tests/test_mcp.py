from __future__ import annotations

import asyncio

import pytest
from mcp import types as mcp_types
from pydantic import AnyUrl

from pythinker_sdk import (
    AudioURLPart,
    ImageURLPart,
    MCPServerConfig,
    MCPToolset,
    TextPart,
    ToolCall,
    ToolResult,
    VideoURLPart,
)
from pythinker_sdk.mcp import mcp_tool_result_to_return_value


class FakeSession:
    def __init__(self, tools: list[mcp_types.Tool] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.cursors: list[str | None] = []
        self._tools = tools

    async def initialize(self) -> mcp_types.InitializeResult:
        raise AssertionError("from_session expects an initialized session")

    async def list_tools(self, cursor: str | None = None) -> mcp_types.ListToolsResult:
        self.cursors.append(cursor)
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        }
        if self._tools is not None:
            return mcp_types.ListToolsResult(tools=self._tools)
        if cursor is None:
            return mcp_types.ListToolsResult(
                tools=[mcp_types.Tool(name="search", description="Search", inputSchema=schema)],
                nextCursor="page-2",
            )
        return mcp_types.ListToolsResult(
            tools=[mcp_types.Tool(name="extract", description="Extract", inputSchema=schema)]
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
        read_timeout_seconds: object | None = None,
    ) -> mcp_types.CallToolResult:
        self.calls.append((name, arguments))
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=f"{name}:{arguments!r}")],
            isError=False,
        )


def test_mcp_server_config_factories() -> None:
    stdio = MCPServerConfig.stdio("local", command="python", args=["server.py"])
    http = MCPServerConfig.streamable_http("remote", url="https://example.test/mcp")

    assert stdio.transport == "stdio"
    assert stdio.args == ("server.py",)
    assert http.transport == "streamable_http"
    assert http.url == "https://example.test/mcp"


@pytest.mark.asyncio
async def test_mcp_toolset_discovers_namespaced_tools_and_calls_original_name() -> None:
    session = FakeSession()
    toolset = await MCPToolset.from_session("tavily", session)

    assert [tool.name for tool in toolset.tools] == ["tavily__search", "tavily__extract"]
    assert session.cursors == [None, "page-2"]

    result = toolset.handle(
        ToolCall(
            id="call-1",
            function=ToolCall.FunctionBody(
                name="tavily__search",
                arguments='{"query":"mcp"}',
            ),
        )
    )
    assert isinstance(result, asyncio.Future)
    tool_result: ToolResult = await result

    assert session.calls == [("search", {"query": "mcp"})]
    assert tool_result.tool_call_id == "call-1"
    assert tool_result.return_value.is_error is False
    assert "search" in str(tool_result.return_value.output)

    await toolset.close()
    assert toolset.tools == []


@pytest.mark.asyncio
async def test_mcp_toolset_sanitizes_public_tool_names() -> None:
    raw_tool_name = "bad tool/with.dots-and-a-very-long-name-that-exceeds-provider-limits"
    session = FakeSession(
        [
            mcp_types.Tool(
                name=raw_tool_name,
                description="Unsafe name",
                inputSchema={"type": "object", "additionalProperties": True},
            )
        ]
    )
    toolset = await MCPToolset.from_session("bad server!", session)
    public_name = toolset.tools[0].name

    assert len(public_name) <= 64
    assert public_name.replace("_", "").replace("-", "").isalnum()

    result = toolset.handle(
        ToolCall(
            id="call-unsafe",
            function=ToolCall.FunctionBody(name=public_name, arguments="{}"),
        )
    )
    assert isinstance(result, asyncio.Future)
    await result

    assert session.calls == [(raw_tool_name, {})]


def test_mcp_result_conversion_includes_structured_content() -> None:
    result = mcp_tool_result_to_return_value(
        mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="summary")],
            structuredContent={"answer": 42},
            isError=False,
        )
    )

    assert result.is_error is False
    assert isinstance(result.output, list)
    assert [part.text for part in result.output if isinstance(part, TextPart)] == [
        "summary",
        'Structured content: {"answer": 42}',
    ]


def test_mcp_result_conversion_handles_media_and_embedded_resources() -> None:
    result = mcp_tool_result_to_return_value(
        mcp_types.CallToolResult(
            content=[
                mcp_types.ImageContent(type="image", data="aW1n", mimeType="image/png"),
                mcp_types.AudioContent(type="audio", data="YXVkaW8=", mimeType="audio/mpeg"),
                mcp_types.EmbeddedResource(
                    type="resource",
                    resource=mcp_types.TextResourceContents(
                        uri=AnyUrl("file:///config.txt"),
                        text="config text",
                    ),
                ),
                mcp_types.EmbeddedResource(
                    type="resource",
                    resource=mcp_types.BlobResourceContents(
                        uri=AnyUrl("file:///clip.mp4"),
                        mimeType="video/mp4",
                        blob="dmlkZW8=",
                    ),
                ),
            ],
            isError=False,
        )
    )

    assert isinstance(result.output, list)
    assert isinstance(result.output[0], ImageURLPart)
    assert result.output[0].image_url.url == "data:image/png;base64,aW1n"
    assert isinstance(result.output[1], AudioURLPart)
    assert result.output[1].audio_url.url == "data:audio/mpeg;base64,YXVkaW8="
    assert isinstance(result.output[2], TextPart)
    assert result.output[2].text == "file:///config.txt:\nconfig text"
    assert isinstance(result.output[3], VideoURLPart)
    assert result.output[3].video_url.url == "data:video/mp4;base64,dmlkZW8="


def test_mcp_result_conversion_marks_errors() -> None:
    result = mcp_tool_result_to_return_value(
        mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="failed")],
            isError=True,
        )
    )

    assert result.is_error is True
    assert result.brief == "MCP error"


def test_mcp_result_conversion_truncates_output() -> None:
    result = mcp_tool_result_to_return_value(
        mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="abcdef")],
            isError=False,
        ),
        max_output_chars=3,
    )

    assert isinstance(result.output, list)
    texts = [part.text for part in result.output if isinstance(part, TextPart)]
    assert texts[0] == "abc"
    assert "Output truncated" in texts[1]
