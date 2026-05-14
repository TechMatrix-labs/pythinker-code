from __future__ import annotations

import asyncio
import json
import os
import sys
from urllib.parse import quote

from pythinker_sdk import MCPServerConfig, MCPToolset, PythinkerClient, ToolCall, ToolResult

DEFAULT_TAVILY_MCP_BASE_URL = "https://mcp.tavily.com/mcp/"


def tavily_mcp_url_from_env() -> str:
    """Return a Tavily MCP URL without printing or logging secrets."""
    if url := os.getenv("TAVILY_MCP_URL"):
        return url

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("Set TAVILY_MCP_URL or TAVILY_API_KEY before running this example.")
    return f"{DEFAULT_TAVILY_MCP_BASE_URL}?tavilyApiKey={quote(api_key)}"


def find_tavily_search_tool(toolset: MCPToolset) -> str:
    """Find the Tavily search tool name after SDK namespacing/sanitization."""
    tool_names = [tool.name for tool in toolset.tools]
    for suffix in ("tavily_search", "search"):
        for name in tool_names:
            if name.endswith(suffix):
                return name
    raise RuntimeError("Tavily search tool was not found on the MCP server.")


async def bounded_tavily_search(toolset: MCPToolset, query: str) -> ToolResult:
    """Call Tavily search with deterministic bounded parameters before summarization."""
    tool_name = find_tavily_search_tool(toolset)
    result = toolset.handle(
        ToolCall(
            id="tavily-search-1",
            function=ToolCall.FunctionBody(
                name=tool_name,
                arguments=json.dumps(
                    {
                        "query": query,
                        "search_depth": "advanced",
                        "max_results": 5,
                        "include_answer": True,
                        "include_raw_content": False,
                    }
                ),
            ),
        )
    )
    if isinstance(result, ToolResult):
        return result
    return await result


async def main() -> None:
    query = " ".join(sys.argv[1:]).strip() or "latest Model Context Protocol Python SDK guidance"

    async with MCPToolset.connect(
        [MCPServerConfig.streamable_http("tavily", url=tavily_mcp_url_from_env())]
    ) as toolset:
        search_result = await bounded_tavily_search(toolset, query)
        client = PythinkerClient.from_env(
            model=os.getenv("PYTHINKER_MODEL", "pythinker-ai"),
            system_prompt=(
                "You are a concise research assistant. Summarize Tavily MCP search results "
                "in 5 bullets or fewer and cite source URLs when present."
            ),
        )
        result = await client.generate(
            "Answer this research question using the bounded Tavily MCP search result below.\n\n"
            f"Question: {query}\n\n"
            f"Search result:\n{search_result.return_value.output}"
        )

    print(result.message.extract_text())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(
            "Tavily MCP example failed. Verify PYTHINKER_API_KEY plus either "
            f"TAVILY_API_KEY or TAVILY_MCP_URL. Error type: {type(exc).__name__}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
