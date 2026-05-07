from __future__ import annotations

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.config import Config


def test_anthropic_model_catalog_contains_three_frontier_models():
    from pythinker_code.auth.anthropic_direct import ANTHROPIC_MODELS

    aliases = {model.alias for model in ANTHROPIC_MODELS}
    assert aliases == {
        "anthropic/claude-opus-4-7",
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-haiku-4-5",
    }

    api_ids = {m.alias: m.model_id for m in ANTHROPIC_MODELS}
    assert api_ids == {
        "anthropic/claude-opus-4-7": "claude-opus-4-7",
        "anthropic/claude-sonnet-4-6": "claude-sonnet-4-6",
        "anthropic/claude-haiku-4-5": "claude-haiku-4-5-20251001",
    }

    assert all(m.provider_key == "managed:anthropic" for m in ANTHROPIC_MODELS)


def test_anthropic_env_key_uses_anthropic_api_key(monkeypatch):
    from pythinker_code.auth.anthropic_direct import get_anthropic_api_key_from_env

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert get_anthropic_api_key_from_env() is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "  sk-ant-test  ")
    assert get_anthropic_api_key_from_env() == "sk-ant-test"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert get_anthropic_api_key_from_env() is None


def test_apply_anthropic_config_writes_provider_and_default():
    from pythinker_code.auth.anthropic_direct import (
        ANTHROPIC_BASE_URL,
        ANTHROPIC_PROVIDER_KEY,
        _apply_anthropic_config,
    )

    config = Config(is_from_default_location=True)

    _apply_anthropic_config(config, SecretStr("sk-ant-test"))

    assert set(config.providers) == {ANTHROPIC_PROVIDER_KEY}
    provider = config.providers[ANTHROPIC_PROVIDER_KEY]
    assert provider.type == "anthropic"
    assert provider.base_url == ANTHROPIC_BASE_URL
    assert provider.api_key.get_secret_value() == "sk-ant-test"
    assert config.models["anthropic/claude-opus-4-7"].provider == ANTHROPIC_PROVIDER_KEY
    assert config.models["anthropic/claude-opus-4-7"].model == "claude-opus-4-7"
    assert config.models["anthropic/claude-opus-4-7"].max_context_size == 1_000_000
    assert config.default_model == "anthropic/claude-opus-4-7"


def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


@pytest.mark.asyncio
async def test_login_anthropic_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "sk-ant-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr(
        "pythinker_code.auth.anthropic_direct._discover_anthropic_models", fake_discover
    )

    events = [event async for event in login_anthropic_api_key(config, "sk-ant-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "sk-ant-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "anthropic/claude-opus-4-7"
    assert "anthropic/claude-haiku-4-5" in config.models


@pytest.mark.asyncio
async def test_login_anthropic_falls_back_on_non_auth_response_error(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.anthropic.com/v1/models"),
            (),
            status=503,
            message="Service Unavailable",
        )

    monkeypatch.setattr(
        "pythinker_code.auth.anthropic_direct._discover_anthropic_models", fake_discover
    )

    events = [event async for event in login_anthropic_api_key(config, "sk-ant-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert config.default_model == "anthropic/claude-opus-4-7"


@pytest.mark.asyncio
async def test_login_anthropic_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.anthropic.com/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr(
        "pythinker_code.auth.anthropic_direct._discover_anthropic_models", fake_discover
    )

    events = [event async for event in login_anthropic_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid Anthropic API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_anthropic_uses_discovered_context_length(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import (
        AnthropicModel,
        login_anthropic_api_key,
    )

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            AnthropicModel(
                model_id="claude-opus-4-7",
                alias_suffix="claude-opus-4-7",
                display_name="Claude Opus 4.7",
                max_context_size=2_000_000,
            ),
        )

    monkeypatch.setattr(
        "pythinker_code.auth.anthropic_direct._discover_anthropic_models", fake_discover
    )

    events = [event async for event in login_anthropic_api_key(config, "sk-ant-test")]

    assert events[-1].type == "success"
    assert config.models["anthropic/claude-opus-4-7"].max_context_size == 2_000_000


@pytest.mark.asyncio
async def test_login_anthropic_requires_key(tmp_path):
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_anthropic_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "Anthropic API key is required."


@pytest.mark.parametrize(
    "payload, expected_aliases",
    [
        (None, set()),
        ({}, set()),
        ({"data": "not a list"}, set()),
        ({"data": [{"context_length": 1000}]}, set()),
        ({"data": [{"id": "unknown-model"}]}, set()),
        ({"data": [{"id": "claude-opus-4-7"}]}, {"anthropic/claude-opus-4-7"}),
        (
            {"data": [{"id": "claude-haiku-4-5-20251001"}]},
            {"anthropic/claude-haiku-4-5"},
        ),
    ],
)
def test_parse_discovered_anthropic_models_handles_malformed_payloads(payload, expected_aliases):
    from pythinker_code.auth.anthropic_direct import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert {m.alias for m in result} == expected_aliases


def test_parse_discovered_anthropic_models_overrides_context_length_only_for_positive_int():
    from pythinker_code.auth.anthropic_direct import _parse_discovered_models

    payload = {
        "data": [
            {"id": "claude-opus-4-7", "context_length": "bogus"},
            {"id": "claude-sonnet-4-6", "context_length": -5},
            {"id": "claude-haiku-4-5-20251001", "context_length": 256_000},
        ]
    }
    result = _parse_discovered_models(payload)
    by_id = {m.model_id: m for m in result}
    assert by_id["claude-opus-4-7"].max_context_size == 1_000_000
    assert by_id["claude-sonnet-4-6"].max_context_size == 200_000
    assert by_id["claude-haiku-4-5-20251001"].max_context_size == 256_000


@pytest.mark.asyncio
async def test_logout_anthropic_removes_only_anthropic(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import (
        ANTHROPIC_PROVIDER_KEY,
        _apply_anthropic_config,
        logout_anthropic,
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
    _apply_anthropic_config(config, SecretStr("sk-ant-test"))

    events = [event async for event in logout_anthropic(config)]

    assert events[-1].type == "success"
    assert ANTHROPIC_PROVIDER_KEY not in config.providers
    assert "anthropic/claude-opus-4-7" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_anthropic_preserves_non_anthropic_default(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import _apply_anthropic_config, logout_anthropic
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
    _apply_anthropic_config(config, SecretStr("sk-ant-test"))
    config.default_model = "openai/gpt-5.2"

    events = [event async for event in logout_anthropic(config)]

    assert events[-1].type == "success"
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_anthropic_rejects_non_default_config_location():
    from pythinker_code.auth.anthropic_direct import logout_anthropic

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_anthropic(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
