from __future__ import annotations

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.config import Config


def test_deepseek_model_catalog_contains_two_current_models():
    from pythinker_code.auth.deepseek import DEEPSEEK_MODELS

    aliases = {model.alias for model in DEEPSEEK_MODELS}
    assert aliases == {"deepseek/v4-pro", "deepseek/v4-flash"}

    api_ids = {m.alias: m.model_id for m in DEEPSEEK_MODELS}
    assert api_ids == {
        "deepseek/v4-pro": "deepseek-v4-pro",
        "deepseek/v4-flash": "deepseek-v4-flash",
    }

    assert all(m.provider_key == "managed:deepseek" for m in DEEPSEEK_MODELS)


def test_deepseek_env_key_uses_deepseek_api_key(monkeypatch):
    from pythinker_code.auth.deepseek import get_deepseek_api_key_from_env

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert get_deepseek_api_key_from_env() is None

    monkeypatch.setenv("DEEPSEEK_API_KEY", "  ds-key  ")
    assert get_deepseek_api_key_from_env() == "ds-key"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    assert get_deepseek_api_key_from_env() is None


def test_apply_deepseek_config_writes_provider_and_default():
    from pythinker_code.auth.deepseek import (
        DEEPSEEK_BASE_URL,
        DEEPSEEK_PROVIDER_KEY,
        _apply_deepseek_config,
    )

    config = Config(is_from_default_location=True)

    _apply_deepseek_config(config, SecretStr("ds-test"))

    assert set(config.providers) == {DEEPSEEK_PROVIDER_KEY}
    provider = config.providers[DEEPSEEK_PROVIDER_KEY]
    assert provider.type == "openai_legacy"
    assert provider.base_url == DEEPSEEK_BASE_URL
    assert provider.api_key.get_secret_value() == "ds-test"
    assert config.models["deepseek/v4-pro"].provider == DEEPSEEK_PROVIDER_KEY
    assert config.models["deepseek/v4-pro"].model == "deepseek-v4-pro"
    assert config.default_model == "deepseek/v4-pro"


def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


@pytest.mark.asyncio
async def test_login_deepseek_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import login_deepseek_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "ds-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr("pythinker_code.auth.deepseek._discover_deepseek_models", fake_discover)

    events = [event async for event in login_deepseek_api_key(config, "ds-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "ds-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "deepseek/v4-pro"
    assert "deepseek/v4-flash" in config.models
    assert (tmp_path / "config.toml").exists()


@pytest.mark.asyncio
async def test_login_deepseek_falls_back_on_non_auth_response_error(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import login_deepseek_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.deepseek.com/v1/models"),
            (),
            status=503,
            message="Service Unavailable",
        )

    monkeypatch.setattr("pythinker_code.auth.deepseek._discover_deepseek_models", fake_discover)

    events = [event async for event in login_deepseek_api_key(config, "ds-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert config.default_model == "deepseek/v4-pro"


@pytest.mark.asyncio
async def test_login_deepseek_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import login_deepseek_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.deepseek.com/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr("pythinker_code.auth.deepseek._discover_deepseek_models", fake_discover)

    events = [event async for event in login_deepseek_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid DeepSeek API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_deepseek_uses_discovered_context_length(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import DeepSeekModel, login_deepseek_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            DeepSeekModel(
                model_id="deepseek-v4-pro",
                alias_suffix="v4-pro",
                display_name="DeepSeek V4 Pro",
                max_context_size=256_000,
            ),
        )

    monkeypatch.setattr("pythinker_code.auth.deepseek._discover_deepseek_models", fake_discover)

    events = [event async for event in login_deepseek_api_key(config, "ds-test")]

    assert events[-1].type == "success"
    assert config.models["deepseek/v4-pro"].max_context_size == 256_000


@pytest.mark.asyncio
async def test_login_deepseek_requires_key(tmp_path):
    from pythinker_code.auth.deepseek import login_deepseek_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_deepseek_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "DeepSeek API key is required."


@pytest.mark.parametrize(
    "payload, expected_aliases",
    [
        (None, set()),
        ({}, set()),
        ({"data": "not a list"}, set()),
        ({"data": [{"context_length": 1000}]}, set()),
        ({"data": [{"id": "unknown-model"}]}, set()),
        ({"data": [{"id": "deepseek-v4-pro"}]}, {"deepseek/v4-pro"}),
    ],
)
def test_parse_discovered_deepseek_models_handles_malformed_payloads(payload, expected_aliases):
    from pythinker_code.auth.deepseek import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert {m.alias for m in result} == expected_aliases


def test_parse_discovered_deepseek_models_overrides_context_length_only_for_positive_int():
    from pythinker_code.auth.deepseek import _parse_discovered_models

    payload = {
        "data": [
            {"id": "deepseek-v4-pro", "context_length": "bogus"},
            {"id": "deepseek-v4-flash", "context_length": -5},
        ]
    }
    result = _parse_discovered_models(payload)
    by_id = {m.model_id: m for m in result}
    assert by_id["deepseek-v4-pro"].max_context_size == 128_000
    assert by_id["deepseek-v4-flash"].max_context_size == 128_000


@pytest.mark.asyncio
async def test_logout_deepseek_removes_only_deepseek(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import (
        DEEPSEEK_PROVIDER_KEY,
        _apply_deepseek_config,
        logout_deepseek,
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
    _apply_deepseek_config(config, SecretStr("ds-test"))

    events = [event async for event in logout_deepseek(config)]

    assert events[-1].type == "success"
    assert DEEPSEEK_PROVIDER_KEY not in config.providers
    assert "deepseek/v4-pro" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_deepseek_preserves_non_deepseek_default(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import _apply_deepseek_config, logout_deepseek
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
    _apply_deepseek_config(config, SecretStr("ds-test"))
    config.default_model = "openai/gpt-5.2"

    events = [event async for event in logout_deepseek(config)]

    assert events[-1].type == "success"
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_deepseek_rejects_non_default_config_location():
    from pythinker_code.auth.deepseek import logout_deepseek

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_deepseek(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
    assert config.providers == {}
    assert config.models == {}
