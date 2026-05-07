from __future__ import annotations

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.config import Config


def test_openrouter_model_catalog_contains_six_curated_models():
    from pythinker_code.auth.openrouter import OPENROUTER_MODELS

    aliases = {model.alias for model in OPENROUTER_MODELS}
    assert aliases == {
        "openrouter/openai/gpt-5.2",
        "openrouter/anthropic/claude-sonnet-4.6",
        "openrouter/anthropic/claude-opus-4.7",
        "openrouter/deepseek/deepseek-v4-pro",
        "openrouter/google/gemini-2.5-pro",
        "openrouter/openrouter/auto",
    }

    assert all(m.provider_key == "managed:openrouter" for m in OPENROUTER_MODELS)


def test_openrouter_env_key_uses_openrouter_api_key(monkeypatch):
    from pythinker_code.auth.openrouter import get_openrouter_api_key_from_env

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert get_openrouter_api_key_from_env() is None

    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-or-test  ")
    assert get_openrouter_api_key_from_env() == "sk-or-test"

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert get_openrouter_api_key_from_env() is None


def test_apply_openrouter_config_writes_provider_and_default():
    from pythinker_code.auth.openrouter import (
        OPENROUTER_BASE_URL,
        OPENROUTER_PROVIDER_KEY,
        _apply_openrouter_config,
    )

    config = Config(is_from_default_location=True)

    _apply_openrouter_config(config, SecretStr("sk-or-test"))

    assert set(config.providers) == {OPENROUTER_PROVIDER_KEY}
    provider = config.providers[OPENROUTER_PROVIDER_KEY]
    assert provider.type == "openai_legacy"
    assert provider.base_url == OPENROUTER_BASE_URL
    assert provider.api_key.get_secret_value() == "sk-or-test"
    assert len([m for m in config.models.values() if m.provider == OPENROUTER_PROVIDER_KEY]) == 6
    assert config.models["openrouter/openai/gpt-5.2"].model == "openai/gpt-5.2"
    assert config.default_model == "openrouter/openai/gpt-5.2"


def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


@pytest.mark.asyncio
async def test_login_openrouter_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import login_openrouter_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "sk-or-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr("pythinker_code.auth.openrouter._discover_openrouter_models", fake_discover)

    events = [event async for event in login_openrouter_api_key(config, "sk-or-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "sk-or-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "openrouter/openai/gpt-5.2"
    assert "openrouter/anthropic/claude-opus-4.7" in config.models


@pytest.mark.asyncio
async def test_login_openrouter_falls_back_on_non_auth_response_error(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import login_openrouter_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://openrouter.ai/api/v1/models"),
            (),
            status=503,
            message="Service Unavailable",
        )

    monkeypatch.setattr("pythinker_code.auth.openrouter._discover_openrouter_models", fake_discover)

    events = [event async for event in login_openrouter_api_key(config, "sk-or-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert config.default_model == "openrouter/openai/gpt-5.2"
    assert "openrouter/anthropic/claude-opus-4.7" in config.models


@pytest.mark.asyncio
async def test_login_openrouter_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import login_openrouter_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://openrouter.ai/api/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr("pythinker_code.auth.openrouter._discover_openrouter_models", fake_discover)

    events = [event async for event in login_openrouter_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid OpenRouter API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_openrouter_uses_discovered_metadata_for_curated_only(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import OpenRouterModel, login_openrouter_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            OpenRouterModel(
                model_id="openai/gpt-5.2",
                display_name="OpenAI: GPT-5.2 (overridden)",
                max_context_size=512_000,
            ),
        )

    monkeypatch.setattr("pythinker_code.auth.openrouter._discover_openrouter_models", fake_discover)

    events = [event async for event in login_openrouter_api_key(config, "sk-or-test")]

    assert events[-1].type == "success"
    assert config.models["openrouter/openai/gpt-5.2"].max_context_size == 512_000
    assert "openrouter/anthropic/claude-opus-4.7" in config.models
    openrouter_models = [m for m in config.models.values() if m.provider == "managed:openrouter"]
    assert len(openrouter_models) == 6


@pytest.mark.asyncio
async def test_login_openrouter_requires_key(tmp_path):
    from pythinker_code.auth.openrouter import login_openrouter_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_openrouter_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "OpenRouter API key is required."


def test_parse_discovered_openrouter_models_drops_uncurated_and_keeps_curated_with_override():
    from pythinker_code.auth.openrouter import _parse_discovered_models

    payload = {
        "data": [
            {
                "id": "openai/gpt-5.2",
                "context_length": 700_000,
                "name": "OpenAI: GPT-5.2",
            },
            {
                "id": "openai/gpt-3.5-turbo",
                "context_length": 16_385,
                "name": "OpenAI: GPT-3.5 Turbo",
            },
            {"context_length": 999},
        ]
    }
    result = _parse_discovered_models(payload)
    aliases = {m.alias for m in result}
    assert aliases == {"openrouter/openai/gpt-5.2"}
    by_id = {m.model_id: m for m in result}
    assert by_id["openai/gpt-5.2"].max_context_size == 700_000


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"data": "not a list"}, {"data": [{"context_length": 1000}]}],
)
def test_parse_discovered_openrouter_models_handles_malformed_payloads(payload):
    from pythinker_code.auth.openrouter import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert result == ()


def test_parse_discovered_openrouter_models_overrides_context_length_only_for_positive_int():
    from pythinker_code.auth.openrouter import _parse_discovered_models

    payload = {
        "data": [
            {"id": "openai/gpt-5.2", "context_length": "bogus"},
            {"id": "anthropic/claude-sonnet-4.6", "context_length": -5},
            {"id": "anthropic/claude-opus-4.7", "context_length": 2_000_000},
        ]
    }
    result = _parse_discovered_models(payload)
    by_id = {m.model_id: m for m in result}
    assert by_id["openai/gpt-5.2"].max_context_size == 400_000
    assert by_id["anthropic/claude-sonnet-4.6"].max_context_size == 200_000
    assert by_id["anthropic/claude-opus-4.7"].max_context_size == 2_000_000


def test_merge_overrides_into_static_catalog_keeps_static_for_undiscovered_models():
    from pythinker_code.auth.openrouter import (
        OPENROUTER_MODELS,
        OpenRouterModel,
        _merge_overrides_into_static_catalog,
    )

    discovered = (
        OpenRouterModel(
            model_id="openai/gpt-5.2",
            display_name="OpenAI: GPT-5.2 (overridden)",
            max_context_size=512_000,
        ),
    )
    merged = _merge_overrides_into_static_catalog(discovered)

    assert len(merged) == len(OPENROUTER_MODELS)
    by_id = {m.model_id: m for m in merged}
    assert by_id["openai/gpt-5.2"].max_context_size == 512_000
    assert by_id["openai/gpt-5.2"].display_name == "OpenAI: GPT-5.2 (overridden)"
    # Untouched models keep their static defaults.
    static_by_id = {m.model_id: m for m in OPENROUTER_MODELS}
    for model_id, static_model in static_by_id.items():
        if model_id == "openai/gpt-5.2":
            continue
        assert by_id[model_id] == static_model


@pytest.mark.asyncio
async def test_logout_openrouter_removes_only_openrouter(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import (
        OPENROUTER_PROVIDER_KEY,
        _apply_openrouter_config,
        logout_openrouter,
    )
    from pythinker_code.config import LLMModel, LLMProvider

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)
    config.providers["managed:openai"] = LLMProvider(
        type="openai_responses",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("sk-test"),
    )
    config.models["openai/gpt-5.2"] = LLMModel(
        provider="managed:openai",
        model="gpt-5.2",
        max_context_size=400_000,
    )
    _apply_openrouter_config(config, SecretStr("sk-or-test"))

    events = [event async for event in logout_openrouter(config)]

    assert events[-1].type == "success"
    assert OPENROUTER_PROVIDER_KEY not in config.providers
    assert "openrouter/openai/gpt-5.2" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_openrouter_preserves_non_openrouter_default(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import _apply_openrouter_config, logout_openrouter
    from pythinker_code.config import LLMModel, LLMProvider

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)
    config.providers["managed:openai"] = LLMProvider(
        type="openai_responses",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("sk-test"),
    )
    config.models["openai/gpt-5.2"] = LLMModel(
        provider="managed:openai",
        model="gpt-5.2",
        max_context_size=400_000,
    )
    _apply_openrouter_config(config, SecretStr("sk-or-test"))
    config.default_model = "openai/gpt-5.2"

    events = [event async for event in logout_openrouter(config)]

    assert events[-1].type == "success"
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_openrouter_rejects_non_default_config_location():
    from pythinker_code.auth.openrouter import logout_openrouter

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_openrouter(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
