from __future__ import annotations

import time

import pytest
from pydantic import SecretStr

from pythinker_code.auth.oauth import OAuthManager, OAuthToken, save_tokens
from pythinker_code.auth.openai import OPENAI_CHATGPT_BASE_URL, OPENAI_CHATGPT_OAUTH_KEY
from pythinker_code.auth.platforms import managed_provider_key
from pythinker_code.config import Config, LLMModel, LLMProvider, OAuthRef
from pythinker_code.llm import create_llm


def _openai_chatgpt_config() -> Config:
    provider_key = managed_provider_key("openai-chatgpt")
    return Config(
        is_from_default_location=True,
        default_model="openai-chatgpt/gpt-5.1-codex",
        providers={
            provider_key: LLMProvider(
                type="openai_codex",
                base_url=OPENAI_CHATGPT_BASE_URL,
                api_key=SecretStr(""),
                oauth=OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY),
            )
        },
        models={
            "openai-chatgpt/gpt-5.1-codex": LLMModel(
                provider=provider_key,
                model="gpt-5.1-codex",
                max_context_size=1050000,
                capabilities={"thinking"},
            )
        },
    )


def test_create_llm_supports_openai_codex_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    captured = {}

    class FakeOpenAIResponses:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.model_name = kwargs["model"]

        def with_thinking(self, effort):
            captured["thinking"] = effort
            return self

    monkeypatch.setattr(
        "pythinker_core.contrib.chat_provider.openai_responses.OpenAIResponses", FakeOpenAIResponses
    )
    config = _openai_chatgpt_config()
    provider = next(iter(config.providers.values()))
    model = next(iter(config.models.values()))

    llm = create_llm(provider, model, thinking=True, oauth=OAuthManager(config))

    assert llm is not None
    assert captured["model"] == "gpt-5.1-codex"
    assert captured["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert captured["api_key"] == ""
    assert captured["system_prompt_as_instructions"] is True
    assert captured["thinking"] == "high"


@pytest.mark.asyncio
async def test_oauth_manager_refreshes_openai_chatgpt_ref(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = _openai_chatgpt_config()
    ref = OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY)
    save_tokens(
        ref,
        OAuthToken(
            access_token="old-access",
            refresh_token="old-refresh",
            expires_at=time.time() - 1,
            scope="openid",
            token_type="Bearer",
            expires_in=3600,
        ),
    )

    async def fake_refresh(refresh_token):
        assert refresh_token == "old-refresh"
        return OAuthToken(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at=time.time() + 3600,
            scope="openid",
            token_type="Bearer",
            expires_in=3600,
        )

    monkeypatch.setattr("pythinker_code.auth.openai.refresh_openai_chatgpt_token", fake_refresh)
    manager = OAuthManager(config)

    await manager.ensure_fresh(force=True)

    assert manager.resolve_api_key(SecretStr(""), ref) == "new-access"


def test_create_llm_supports_opencode_go_openai_provider(monkeypatch):
    captured = {}

    class FakeOpenAILegacy:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.model_name = kwargs["model"]

    monkeypatch.setattr(
        "pythinker_core.contrib.chat_provider.openai_legacy.OpenAILegacy", FakeOpenAILegacy
    )

    provider = LLMProvider(
        type="openai_legacy",
        base_url="https://opencode.ai/zen/go/v1",
        api_key=SecretStr("ocgo-test"),
    )
    model = LLMModel(
        provider="managed:opencode-go-openai",
        model="kimi-k2.6",
        max_context_size=262_000,
    )

    llm = create_llm(provider, model)

    assert llm is not None
    assert captured["model"] == "kimi-k2.6"
    assert captured["base_url"] == "https://opencode.ai/zen/go/v1"
    assert captured["api_key"] == "ocgo-test"


def test_create_llm_supports_opencode_go_anthropic_provider(monkeypatch):
    captured = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.model_name = kwargs["model"]

    monkeypatch.setattr("pythinker_core.contrib.chat_provider.anthropic.Anthropic", FakeAnthropic)

    provider = LLMProvider(
        type="anthropic",
        base_url="https://opencode.ai/zen/go/v1",
        api_key=SecretStr("ocgo-test"),
    )
    model = LLMModel(
        provider="managed:opencode-go-anthropic",
        model="minimax-m2.7",
        max_context_size=205_000,
    )

    llm = create_llm(provider, model)

    assert llm is not None
    assert captured["model"] == "minimax-m2.7"
    assert captured["base_url"] == "https://opencode.ai/zen/go/v1"
    assert captured["api_key"] == "ocgo-test"
