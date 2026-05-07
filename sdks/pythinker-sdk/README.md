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

## Environment variables

- `PYTHINKER_API_KEY`: API key for the Pythinker API.
- `PYTHINKER_BASE_URL`: Override the API base URL (defaults to `https://api.pythinker-ai.ai/v1`).
