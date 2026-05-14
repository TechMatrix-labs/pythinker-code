# Pythinker SDK

Pythinker SDK provides a convenient way to access the Pythinker API and build agent workflows in Python.

## Installation

Pythinker SDK requires Python 3.12 or higher. We recommend using uv as the package manager.

```bash
uv init --python 3.12  # or higher
```

Then add Pythinker SDK as a dependency:

```bash
uv add pythinker-sdk
```

## Examples

### Quickstart client

```python
import asyncio

from pythinker_sdk import PythinkerClient


async def main() -> None:
    client = PythinkerClient.from_env(model="pythinker-ai")
    result = await client.generate(
        "Who are you?",
        system_prompt="You are a helpful assistant.",
    )
    print(result.message.extract_text())


asyncio.run(main())
```

`PythinkerClient.from_env()` reads `PYTHINKER_API_KEY` and `PYTHINKER_BASE_URL` while still accepting explicit overrides. For tool-using agents, `run_until_done()` appends assistant and tool-result messages to a `Conversation` until no tool calls remain.

### Simple chat completion

```python
import asyncio

from pythinker_sdk import Pythinker, Message, generate


async def main() -> None:
    pythinker = Pythinker(
        base_url="https://api.pythinker-ai.ai/v1",
        api_key="your_pythinker_api_key_here",
        model="pythinker-ai",
    )

    history = [
        Message(role="user", content="Who are you?"),
    ]

    result = await generate(
        chat_provider=pythinker,
        system_prompt="You are a helpful assistant.",
        tools=[],
        history=history,
    )
    print(result.message)
    print(result.usage)


asyncio.run(main())
```

### Streaming output

```python
import asyncio

from pythinker_sdk import Pythinker, Message, StreamedMessagePart, generate


async def main() -> None:
    pythinker = Pythinker(
        base_url="https://api.pythinker-ai.ai/v1",
        api_key="your_pythinker_api_key_here",
        model="pythinker-ai",
    )

    history = [
        Message(role="user", content="Who are you?"),
    ]

    def output(message_part: StreamedMessagePart) -> None:
        print(message_part)

    result = await generate(
        chat_provider=pythinker,
        system_prompt="You are a helpful assistant.",
        tools=[],
        history=history,
        on_message_part=output,
    )
    print(result.message)
    print(result.usage)


asyncio.run(main())
```

### MCP tools

```python
import asyncio
import os

from pythinker_sdk import MCPServerConfig, MCPToolset, PythinkerClient


async def main() -> None:
    async with MCPToolset.connect(
        [
            MCPServerConfig.streamable_http(
                "search",
                url=os.environ["MCP_SERVER_URL"],
            )
        ]
    ) as toolset:
        client = PythinkerClient.from_env(model="pythinker-ai", toolset=toolset)
        result = await client.run_until_done("Use the search tools to answer: what is MCP?")
        print(result.message.extract_text())


asyncio.run(main())
```

MCP tools are exposed with stable namespaced names such as `search__tool_name` by default. Names are sanitized to provider-safe characters and length limits while preserving the original MCP tool name internally.

For local stdio MCP servers, use `MCPServerConfig.stdio(...)`:

```python
async with MCPToolset.connect(
    [
        MCPServerConfig.stdio(
            "local",
            command="python",
            args=["path/to/server.py"],
        )
    ]
) as toolset:
    ...
```

### Tavily MCP research agent

The SDK includes a Tavily MCP example:

```bash
export PYTHINKER_API_KEY="your_pythinker_api_key_here"
export TAVILY_API_KEY="your_tavily_api_key_here"
uv run python sdks/pythinker-sdk/examples/tavily_mcp_agent.py "latest MCP Python SDK guidance"
```

You can also provide a complete `TAVILY_MCP_URL` instead of `TAVILY_API_KEY`. The example deterministically calls Tavily search with bounded defaults before summarization: `search_depth="advanced"`, `max_results=5`, `include_answer=true`, and `include_raw_content=false`. Advanced search can cost more; change it to `basic`, `fast`, or `ultra-fast` if latency or cost matters more than depth. If you use `TAVILY_API_KEY`, the example constructs the MCP URL in memory but catches startup errors without printing the URL.

### Upload video

```python
import asyncio
from pathlib import Path
from pythinker_sdk import Pythinker, Message, TextPart, generate


async def main() -> None:
    pythinker = Pythinker(
        base_url="https://api.pythinker-ai.ai/v1",
        api_key="your_pythinker_api_key_here",
        model="pythinker-ai",
    )

    video_path = Path("demo.mp4")
    video_part = await pythinker.files.upload_video(
        data=video_path.read_bytes(),
        mime_type="video/mp4",
    )

    history = [
        Message(
            role="user",
            content=[
                TextPart(text="Please describe this video."),
                video_part,
            ],
        ),
    ]

    result = await generate(
        chat_provider=pythinker,
        system_prompt="You are a helpful assistant.",
        tools=[],
        history=history,
    )
    print(result.message)
    print(result.usage)


asyncio.run(main())
```

### Tool calling with `step`

```python
import asyncio

from pydantic import BaseModel

from pythinker_sdk import CallableTool2, Pythinker, Message, SimpleToolset, StepResult, ToolOk, ToolReturnValue, step


class AddToolParams(BaseModel):
    a: int
    b: int


class AddTool(CallableTool2[AddToolParams]):
    name: str = "add"
    description: str = "Add two integers."
    params: type[AddToolParams] = AddToolParams

    async def __call__(self, params: AddToolParams) -> ToolReturnValue:
        return ToolOk(output=str(params.a + params.b))


async def main() -> None:
    pythinker = Pythinker(
        base_url="https://api.pythinker-ai.ai/v1",
        api_key="your_pythinker_api_key_here",
        model="pythinker-ai",
    )

    toolset = SimpleToolset()
    toolset += AddTool()

    history = [
        Message(role="user", content="Please add 2 and 3 with the add tool."),
    ]

    result: StepResult = await step(
        chat_provider=pythinker,
        system_prompt="You are a precise math tutor.",
        toolset=toolset,
        history=history,
    )
    print(result.message)
    print(await result.tool_results())


asyncio.run(main())
```

## API guide

### `PythinkerClient`

`PythinkerClient` is the high-level SDK entry point for application code. It wraps a chat provider, default system prompt, and optional toolset.

- `PythinkerClient.from_env(...)`: create a client from `PYTHINKER_API_KEY` and `PYTHINKER_BASE_URL`, with explicit arguments taking precedence.
- `await client.generate(prompt, ...)`: generate one assistant message without dispatching tools.
- `await client.step(prompt, ...)`: generate one assistant message and dispatch tool calls once.
- `await client.run_until_done(prompt, max_steps=8, ...)`: keep appending assistant/tool-result messages until the assistant stops calling tools.

### `Conversation`

`Conversation` is a small in-memory helper around `list[Message]`:

- `add_user(...)` appends a user message.
- `add_assistant(...)` appends an assistant message.
- `add_tool_result(...)` converts a `ToolResult` into a tool-role message.
- `last_text()` extracts text from the most recent message.

Use this when you want to own message history explicitly but avoid rewriting tool-result conversion boilerplate.

### MCP tools

`MCPToolset` adapts MCP server tools to Pythinker tools:

- `MCPServerConfig.stdio(...)` connects to a local stdio MCP server.
- `MCPServerConfig.streamable_http(...)` connects to a remote streamable HTTP MCP server.
- `async with MCPToolset.connect([...]) as toolset:` opens sessions, initializes them, discovers tools, and closes transports on exit.
- Tool names are namespaced by default as `server__tool` to avoid collisions.
- Tool output is bounded and receives a truncation note if it exceeds the SDK MCP output budget.

## Error handling and timeouts

Provider calls can raise `ChatProviderError` subclasses such as `APIConnectionError`, `APITimeoutError`, `APIStatusError`, and `APIEmptyResponseError`. MCP tool execution errors are returned to the model as `ToolError` values so agent loops can continue when a tool fails.

For MCP servers, use `tool_call_timeout_seconds` on `MCPServerConfig.stdio(...)` or `MCPServerConfig.streamable_http(...)` to bound individual MCP tool calls.

## API stability

The SDK preserves the current low-level exports from `pythinker-core` (`Pythinker`, `Message`, `generate`, `step`, tool classes, and provider errors). New high-level helpers are additive and are intended to remain backward compatible across minor releases.

## Environment variables

- `PYTHINKER_API_KEY`: API key for the Pythinker API.
- `PYTHINKER_BASE_URL`: Override the API base URL (defaults to `https://api.pythinker-ai.ai/v1`).
- `PYTHINKER_MODEL`: Optional model name used by examples such as `tavily_mcp_agent.py`.
- `TAVILY_API_KEY`: Tavily API key used by the Tavily MCP example when `TAVILY_MCP_URL` is not set.
- `TAVILY_MCP_URL`: Complete Tavily MCP server URL for the Tavily MCP example.
