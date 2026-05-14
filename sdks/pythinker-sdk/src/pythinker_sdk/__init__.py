"""
Pythinker SDK provides a convenient way to access the Pythinker API and build agent workflows.

Key features:

- `generate` creates a completion stream and merges message parts into a `Message`
  with optional `TokenUsage`.
- `step` layers tool dispatch over `generate`, returning `StepResult` and tool outputs.
- Message structures, content parts, and tool abstractions live in this module.

Example (minimal agent loop):

```python
import asyncio

from pythinker_sdk import Pythinker, Message, SimpleToolset, StepResult, ToolResult, step


def tool_result_to_message(result: ToolResult) -> Message:
    return Message(
        role="tool",
        tool_call_id=result.tool_call_id,
        content=result.return_value.output,
    )


async def agent_loop() -> None:
    pythinker = Pythinker(
        base_url="https://api.pythinker-ai.ai/v1",
        api_key="your_pythinker_api_key_here",
        model="pythinker-ai",
    )

    toolset = SimpleToolset()
    history: list[Message] = []
    system_prompt = "You are a helpful assistant."

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break

        history.append(Message(role="user", content=user_input))

        while True:
            result: StepResult = await step(
                chat_provider=pythinker,
                system_prompt=system_prompt,
                toolset=toolset,
                history=history,
            )

            history.append(result.message)
            tool_results = await result.tool_results()
            for tool_result in tool_results:
                history.append(tool_result_to_message(tool_result))

            if text := result.message.extract_text():
                print("Assistant:", text)

            if not result.tool_calls:
                break


asyncio.run(agent_loop())
```
"""

from __future__ import annotations

from pythinker_core import GenerateResult, StepResult, generate, step
from pythinker_core.chat_provider import (
    APIConnectionError,
    APIEmptyResponseError,
    APIStatusError,
    APITimeoutError,
    ChatProviderError,
    StreamedMessagePart,
    ThinkingEffort,
    TokenUsage,
)
from pythinker_core.chat_provider.pythinker import (
    Pythinker,
    PythinkerFiles,
    PythinkerStreamedMessage,
)
from pythinker_core.message import (
    AudioURLPart,
    ContentPart,
    ImageURLPart,
    Message,
    Role,
    TextPart,
    ThinkPart,
    ToolCall,
    ToolCallPart,
    VideoURLPart,
)
from pythinker_core.tooling import (
    BriefDisplayBlock,
    CallableTool,
    CallableTool2,
    DisplayBlock,
    Tool,
    ToolError,
    ToolOk,
    ToolResult,
    ToolResultFuture,
    ToolReturnValue,
    Toolset,
    UnknownDisplayBlock,
)
from pythinker_core.tooling.simple import SimpleToolset

from pythinker_sdk.client import AgentRunResult, MaxStepsReachedError, PythinkerClient
from pythinker_sdk.conversation import Conversation, tool_result_to_message
from pythinker_sdk.mcp import (
    MCP_MAX_OUTPUT_CHARS,
    MCPServerConfig,
    MCPTool,
    MCPToolset,
    mcp_tool_result_to_return_value,
)

__all__ = [
    # providers
    "Pythinker",
    "PythinkerFiles",
    "PythinkerStreamedMessage",
    "StreamedMessagePart",
    "ThinkingEffort",
    # provider errors
    "APIConnectionError",
    "APIEmptyResponseError",
    "APIStatusError",
    "APITimeoutError",
    "ChatProviderError",
    # messages and content parts
    "Message",
    "Role",
    "ContentPart",
    "TextPart",
    "ThinkPart",
    "ImageURLPart",
    "AudioURLPart",
    "VideoURLPart",
    "ToolCall",
    "ToolCallPart",
    # tooling
    "Tool",
    "CallableTool",
    "CallableTool2",
    "Toolset",
    "SimpleToolset",
    "ToolReturnValue",
    "ToolOk",
    "ToolError",
    "ToolResult",
    "ToolResultFuture",
    # display blocks
    "DisplayBlock",
    "BriefDisplayBlock",
    "UnknownDisplayBlock",
    # SDK conveniences
    "PythinkerClient",
    "Conversation",
    "AgentRunResult",
    "MaxStepsReachedError",
    "tool_result_to_message",
    "MCPServerConfig",
    "MCPTool",
    "MCPToolset",
    "MCP_MAX_OUTPUT_CHARS",
    "mcp_tool_result_to_return_value",
    # generation
    "generate",
    "step",
    "GenerateResult",
    "StepResult",
    "TokenUsage",
]
