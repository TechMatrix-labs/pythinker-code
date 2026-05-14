from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch
from pythinker_core.chat_provider.echo import ScriptedEchoChatProvider

from pythinker_sdk import (
    CallableTool,
    Conversation,
    Message,
    PythinkerClient,
    SimpleToolset,
    TextPart,
    ToolOk,
    ToolReturnValue,
    tool_result_to_message,
)


class EchoTool(CallableTool):
    def __init__(self) -> None:
        super().__init__(
            name="echo",
            description="Echo the provided text.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        )

    async def __call__(self, text: str) -> ToolReturnValue:
        return ToolOk(output=f"echo:{text}")


def test_client_from_env_accepts_explicit_api_key(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("PYTHINKER_API_KEY", raising=False)

    client = PythinkerClient.from_env(model="test-model", api_key="explicit-key")

    assert client.chat_provider.model_name == "test-model"


def test_conversation_helpers_append_messages() -> None:
    conversation = Conversation()

    user = conversation.add_user("hello")
    assistant = conversation.add_assistant(TextPart(text="hi"))

    assert user.role == "user"
    assert assistant.role == "assistant"
    assert conversation.last_text() == "hi"


@pytest.mark.asyncio
async def test_tool_result_to_message_round_trip() -> None:
    toolset = SimpleToolset([EchoTool()])
    provider = ScriptedEchoChatProvider(
        ['tool_call: {"id": "call-1", "name": "echo", "arguments": "{\\"text\\":\\"hi\\"}"}']
    )
    client = PythinkerClient(chat_provider=provider, toolset=toolset)

    result = await client.step(history=[Message(role="user", content="use the tool")])
    tool_result = (await result.tool_results())[0]
    message = tool_result_to_message(tool_result)

    assert message.role == "tool"
    assert message.tool_call_id == "call-1"
    assert message.extract_text() == "echo:hi"


@pytest.mark.asyncio
async def test_client_generate_accepts_prompt() -> None:
    provider = ScriptedEchoChatProvider(["text: hello"])
    client = PythinkerClient(chat_provider=provider)

    result = await client.generate("say hello")

    assert result.message.extract_text() == "hello"


@pytest.mark.asyncio
async def test_client_run_until_done_appends_tool_results() -> None:
    toolset = SimpleToolset([EchoTool()])
    provider = ScriptedEchoChatProvider(
        [
            'tool_call: {"id": "call-1", "name": "echo", "arguments": "{\\"text\\":\\"hi\\"}"}',
            "text: done",
        ]
    )
    client = PythinkerClient(chat_provider=provider, toolset=toolset)

    result = await client.run_until_done("please echo hi")

    assert result.message.extract_text() == "done"
    assert len(result.steps) == 2
    assert [message.role for message in result.conversation.history] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert result.tool_results[0].return_value.output == "echo:hi"
