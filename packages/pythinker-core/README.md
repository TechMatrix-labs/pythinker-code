# Pythinker Core

Pythinker Core provides the low-level LLM, message, streaming, provider, and tool abstractions used by Pythinker CLI and Pythinker SDK.

## Installation

Pythinker Core requires Python 3.12 or higher. We recommend using uv as the package manager.

```bash
uv add pythinker-core
```

To enable provider integrations beyond the Pythinker API, install the optional extra:

```bash
uv add 'pythinker-core[contrib]'
```

## Example

```python
import asyncio

import pythinker_core
from pythinker_core.chat_provider.pythinker import Pythinker
from pythinker_core.message import Message


async def main() -> None:
    pythinker = Pythinker(
        base_url="https://api.pythinker-ai.ai/v1",
        api_key="your_pythinker_api_key_here",
        model="pythinker-ai",
    )

    result = await pythinker_core.generate(
        chat_provider=pythinker,
        system_prompt="You are a helpful assistant.",
        tools=[],
        history=[Message(role="user", content="Who are you?")],
    )
    print(result.message)


asyncio.run(main())
```
