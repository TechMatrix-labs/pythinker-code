from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Self
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr
from pythinker_core.chat_provider import (
    APIConnectionError,
    APIStatusError,
    StreamedMessagePart,
    ThinkingEffort,
    TokenUsage,
)
from pythinker_core.message import Message, TextPart
from pythinker_core.tooling import Tool
from pythinker_core.tooling.simple import SimpleToolset

from pythinker_code.config import LLMModel, LLMProvider, OAuthRef
from pythinker_code.llm import LLM
from pythinker_code.soul import run_soul
from pythinker_code.soul.agent import Agent, Runtime
from pythinker_code.soul.context import Context
from pythinker_code.soul.pythinkersoul import PythinkerSoul
from pythinker_code.utils.aioqueue import QueueShutDown
from pythinker_code.wire import Wire


class StaticStreamedMessage:
    def __init__(self, parts: Sequence[StreamedMessagePart]) -> None:
        self._iter = self._to_stream(parts)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> StreamedMessagePart:
        return await self._iter.__anext__()

    async def _to_stream(
        self, parts: Sequence[StreamedMessagePart]
    ) -> AsyncIterator[StreamedMessagePart]:
        for part in parts:
            yield part

    @property
    def id(self) -> str | None:
        return "recovering"

    @property
    def usage(self) -> TokenUsage | None:
        return None


class RecoveringSequenceProvider:
    name = "recovering-sequence"

    def __init__(self) -> None:
        self.generate_attempts = 0
        self.recovery_calls = 0

    @property
    def model_name(self) -> str:
        return "recovering-sequence"

    @property
    def thinking_effort(self) -> ThinkingEffort | None:
        return None

    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> StaticStreamedMessage:
        self.generate_attempts += 1
        if self.generate_attempts == 1:
            raise APIConnectionError("Connection error.")
        return StaticStreamedMessage([TextPart(text="recovered")])

    def on_retryable_error(self, error: BaseException) -> bool:
        self.recovery_calls += 1
        return True

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        return self


class AlwaysConnectionErrorProvider:
    name = "always-connection-error"

    def __init__(self) -> None:
        self.generate_attempts = 0
        self.recovery_calls = 0

    @property
    def model_name(self) -> str:
        return "always-connection-error"

    @property
    def thinking_effort(self) -> ThinkingEffort | None:
        return None

    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> StaticStreamedMessage:
        self.generate_attempts += 1
        raise APIConnectionError("Connection error.")

    def on_retryable_error(self, error: BaseException) -> bool:
        self.recovery_calls += 1
        return True

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        return self


class StatusErrorThenSuccessProvider:
    name = "status-error-then-success"

    def __init__(self, status_code: int = 503) -> None:
        self.generate_attempts = 0
        self.recovery_calls = 0
        self._status_code = status_code

    @property
    def model_name(self) -> str:
        return "status-error-then-success"

    @property
    def thinking_effort(self) -> ThinkingEffort | None:
        return None

    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> StaticStreamedMessage:
        self.generate_attempts += 1
        if self.generate_attempts < 3:
            raise APIStatusError(self._status_code, f"Status {self._status_code}")
        return StaticStreamedMessage([TextPart(text="status recovered")])

    def on_retryable_error(self, error: BaseException) -> bool:
        self.recovery_calls += 1
        return True

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        return self


class NonRetryableConnectionProvider:
    name = "non-retryable-connection"

    def __init__(self) -> None:
        self.generate_attempts = 0

    @property
    def model_name(self) -> str:
        return "non-retryable-connection"

    @property
    def thinking_effort(self) -> ThinkingEffort | None:
        return None

    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> StaticStreamedMessage:
        self.generate_attempts += 1
        if self.generate_attempts == 1:
            raise APIConnectionError("Connection error.")
        return StaticStreamedMessage([TextPart(text="non-retryable recovered")])

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        return self


class ConnectionThen401ThenSuccessProvider:
    name = "connection-then-401-then-success"

    def __init__(self) -> None:
        self.generate_attempts = 0
        self.recovery_calls = 0

    @property
    def model_name(self) -> str:
        return "connection-then-401-then-success"

    @property
    def thinking_effort(self) -> ThinkingEffort | None:
        return None

    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> StaticStreamedMessage:
        self.generate_attempts += 1
        if self.generate_attempts == 1:
            raise APIConnectionError("Connection error.")
        if self.generate_attempts == 2:
            raise APIStatusError(401, "expired token")
        return StaticStreamedMessage([TextPart(text="auth recovered")])

    def on_retryable_error(self, error: BaseException) -> bool:
        self.recovery_calls += 1
        return True

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        return self


def _runtime_with_llm(runtime: Runtime, llm: LLM) -> Runtime:
    return Runtime(
        config=runtime.config,
        llm=llm,
        session=runtime.session,
        builtin_args=runtime.builtin_args,
        denwa_renji=runtime.denwa_renji,
        approval=runtime.approval,
        labor_market=runtime.labor_market,
        environment=runtime.environment,
        notifications=runtime.notifications,
        background_tasks=runtime.background_tasks,
        skills=runtime.skills,
        oauth=runtime.oauth,
        additional_dirs=runtime.additional_dirs,
        skills_dirs=runtime.skills_dirs,
        role=runtime.role,
    )


def _make_soul(runtime: Runtime, llm: LLM, tmp_path: Path) -> tuple[PythinkerSoul, Context]:
    agent = Agent(
        name="Retry Test Agent",
        system_prompt="Retry test prompt.",
        toolset=SimpleToolset(),
        runtime=_runtime_with_llm(runtime, llm),
    )
    context = Context(file_backend=tmp_path / "history.jsonl")
    return PythinkerSoul(agent, context=context), context


async def _drain_ui_messages(wire: Wire) -> None:
    wire_ui = wire.ui_side(merge=True)
    while True:
        try:
            await wire_ui.receive()
        except QueueShutDown:
            return


@pytest.mark.asyncio
async def test_step_retry_recovers_retryable_provider(runtime: Runtime, tmp_path: Path) -> None:
    runtime.config.loop_control.max_retries_per_step = 2
    provider = RecoveringSequenceProvider()
    llm = LLM(
        chat_provider=provider,
        max_context_size=100_000,
        capabilities=set(),
    )
    soul, context = _make_soul(runtime, llm, tmp_path)

    await run_soul(soul, "trigger recovery", _drain_ui_messages, asyncio.Event())

    assert provider.generate_attempts == 2
    assert provider.recovery_calls == 1
    assert context.history[-1].extract_text(" ").strip() == "recovered"


@pytest.mark.asyncio
async def test_step_connection_error_recovery_only_retries_once(
    runtime: Runtime, tmp_path: Path
) -> None:
    runtime.config.loop_control.max_retries_per_step = 5
    provider = AlwaysConnectionErrorProvider()
    llm = LLM(
        chat_provider=provider,
        max_context_size=100_000,
        capabilities=set(),
    )
    soul, _ = _make_soul(runtime, llm, tmp_path)

    with pytest.raises(APIConnectionError):
        await run_soul(soul, "trigger connection failure", _drain_ui_messages, asyncio.Event())

    assert provider.generate_attempts == 2
    assert provider.recovery_calls == 1


@pytest.mark.asyncio
async def test_step_connection_error_records_failed_llm_metrics(
    runtime: Runtime, tmp_path: Path
) -> None:
    runtime.config.loop_control.max_retries_per_step = 5
    provider = AlwaysConnectionErrorProvider()
    llm = LLM(
        chat_provider=provider,
        max_context_size=100_000,
        capabilities=set(),
    )
    soul, _ = _make_soul(runtime, llm, tmp_path)

    with (
        patch("pythinker_code.telemetry.metrics.record_llm_call") as record_llm_call,
        patch("pythinker_code.telemetry.metrics.record_error") as record_error,
        pytest.raises(APIConnectionError),
    ):
        await run_soul(soul, "trigger connection failure", _drain_ui_messages, asyncio.Event())

    failed_llm_calls = [
        call for call in record_llm_call.call_args_list if call.kwargs.get("success") is False
    ]
    assert len(failed_llm_calls) == 2
    for call in failed_llm_calls:
        assert call.kwargs["system"] == "alwaysconnectionerrorprovider"
        assert call.kwargs["model"] == "always-connection-error"
        assert call.kwargs["duration_seconds"] >= 0

    assert [call.kwargs for call in record_error.call_args_list] == [
        {"kind": "api_error", "error_type": "network"},
        {"kind": "api_error", "error_type": "network"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [503, 504], ids=["503", "504"])
async def test_step_status_error_still_uses_tenacity_retries(
    runtime: Runtime, tmp_path: Path, status_code: int
) -> None:
    runtime.config.loop_control.max_retries_per_step = 3
    provider = StatusErrorThenSuccessProvider(status_code=status_code)
    llm = LLM(
        chat_provider=provider,
        max_context_size=100_000,
        capabilities=set(),
    )
    soul, context = _make_soul(runtime, llm, tmp_path)

    await run_soul(soul, "trigger status retry", _drain_ui_messages, asyncio.Event())

    assert provider.generate_attempts == 3
    assert provider.recovery_calls == 0
    assert context.history[-1].extract_text(" ").strip() == "status recovered"


@pytest.mark.asyncio
async def test_step_non_retryable_provider_keeps_tenacity_connection_retries(
    runtime: Runtime, tmp_path: Path
) -> None:
    runtime.config.loop_control.max_retries_per_step = 2
    provider = NonRetryableConnectionProvider()
    llm = LLM(
        chat_provider=provider,
        max_context_size=100_000,
        capabilities=set(),
    )
    soul, context = _make_soul(runtime, llm, tmp_path)

    await run_soul(
        soul, "trigger non-retryable connection retry", _drain_ui_messages, asyncio.Event()
    )

    assert provider.generate_attempts == 2
    assert context.history[-1].extract_text(" ").strip() == "non-retryable recovered"


@pytest.mark.asyncio
async def test_step_connection_recovery_then_401_triggers_oauth_refresh(
    runtime: Runtime, tmp_path: Path
) -> None:
    oauth_provider = LLMProvider(
        type="pythinker",
        base_url="https://api.test/v1",
        api_key=SecretStr(""),
        oauth=OAuthRef(storage="file", key="oauth/pythinker-code"),
    )
    oauth_model = LLMModel(
        provider="managed:pythinker-code",
        model="pythinker-for-coding",
        max_context_size=100_000,
    )
    runtime.config.providers[oauth_model.provider] = oauth_provider
    runtime.config.models["pythinker-code/pythinker-for-coding"] = oauth_model

    provider = ConnectionThen401ThenSuccessProvider()
    llm = LLM(
        chat_provider=provider,
        max_context_size=100_000,
        capabilities=set(),
        model_config=oauth_model,
        provider_config=oauth_provider,
    )
    soul, context = _make_soul(runtime, llm, tmp_path)

    refresh_mock = AsyncMock()
    runtime.oauth.ensure_fresh = refresh_mock

    await run_soul(soul, "trigger mixed recovery", _drain_ui_messages, asyncio.Event())

    assert provider.generate_attempts == 3
    assert provider.recovery_calls == 1
    assert context.history[-1].extract_text(" ").strip() == "auth recovered"
    assert len(refresh_mock.await_args_list) == 2
    assert any(call.kwargs.get("force") is True for call in refresh_mock.await_args_list)
