# Pythinker SDK examples

Examples in this folder are runnable scripts for SDK integrations.

## Tavily MCP research agent

`tavily_mcp_agent.py` demonstrates:

- `PythinkerClient.from_env(...)`
- `MCPToolset.connect(...)`
- streamable HTTP MCP server configuration
- deterministic bounded Tavily search before summarization

Run from the repository root:

```bash
export PYTHINKER_API_KEY="your_pythinker_api_key_here"
export TAVILY_API_KEY="your_tavily_api_key_here"
uv run python sdks/pythinker-sdk/examples/tavily_mcp_agent.py "latest MCP Python SDK guidance"
```

You can provide `TAVILY_MCP_URL` instead of `TAVILY_API_KEY` when you already have a complete Tavily MCP URL.
