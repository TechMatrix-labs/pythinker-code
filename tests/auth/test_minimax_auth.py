from __future__ import annotations

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.config import Config


def test_minimax_model_catalog_contains_four_current_models():
    from pythinker_code.auth.minimax import MINIMAX_MODELS

    aliases = {model.alias for model in MINIMAX_MODELS}
    assert aliases == {
        "minimax/m2.7",
        "minimax/m2.7-highspeed",
        "minimax/m2.5",
        "minimax/m2.5-highspeed",
    }

    api_ids = {m.alias: m.model_id for m in MINIMAX_MODELS}
    assert api_ids == {
        "minimax/m2.7": "MiniMax-M2.7",
        "minimax/m2.7-highspeed": "MiniMax-M2.7-highspeed",
        "minimax/m2.5": "MiniMax-M2.5",
        "minimax/m2.5-highspeed": "MiniMax-M2.5-highspeed",
    }

    assert all(m.provider_key == "managed:minimax-anthropic" for m in MINIMAX_MODELS)


def test_minimax_env_key_uses_minimax_api_key(monkeypatch):
    from pythinker_code.auth.minimax import get_minimax_api_key_from_env

    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    assert get_minimax_api_key_from_env() is None

    monkeypatch.setenv("MINIMAX_API_KEY", "  mx-key  ")
    assert get_minimax_api_key_from_env() == "mx-key"

    monkeypatch.setenv("MINIMAX_API_KEY", "")
    assert get_minimax_api_key_from_env() is None


def test_apply_minimax_config_writes_provider_and_default():
    from pythinker_code.auth.minimax import (
        MINIMAX_ANTHROPIC_BASE_URL,
        MINIMAX_ANTHROPIC_PROVIDER_KEY,
        _apply_minimax_config,
    )

    config = Config(is_from_default_location=True)

    _apply_minimax_config(config, SecretStr("mx-test"))

    assert set(config.providers) == {MINIMAX_ANTHROPIC_PROVIDER_KEY}
    provider = config.providers[MINIMAX_ANTHROPIC_PROVIDER_KEY]
    assert provider.type == "anthropic"
    assert provider.base_url == MINIMAX_ANTHROPIC_BASE_URL
    assert provider.api_key.get_secret_value() == "mx-test"
    assert config.models["minimax/m2.7"].provider == MINIMAX_ANTHROPIC_PROVIDER_KEY
    assert config.models["minimax/m2.7"].model == "MiniMax-M2.7"
    assert config.default_model == "minimax/m2.7"


def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


@pytest.mark.asyncio
async def test_login_minimax_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "mx-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "mx-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "mx-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "minimax/m2.7"
    assert "minimax/m2.5-highspeed" in config.models
    assert (tmp_path / "config.toml").exists()


@pytest.mark.asyncio
async def test_login_minimax_falls_back_on_non_auth_response_error(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.minimax.io/v1/models"),
            (),
            status=503,
            message="Service Unavailable",
        )

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "mx-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert config.default_model == "minimax/m2.7"


@pytest.mark.asyncio
async def test_login_minimax_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.minimax.io/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid MiniMax API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_minimax_uses_discovered_context_length(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import MiniMaxModel, login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            MiniMaxModel(
                model_id="MiniMax-M2.7",
                alias_suffix="m2.7",
                display_name="MiniMax M2.7",
                max_context_size=512_000,
            ),
        )

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "mx-test")]

    assert events[-1].type == "success"
    assert config.models["minimax/m2.7"].max_context_size == 512_000


@pytest.mark.asyncio
async def test_login_minimax_requires_key(tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_minimax_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "MiniMax API key is required."


@pytest.mark.asyncio
async def test_login_minimax_emits_token_plan_event_for_sk_cp_prefix(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return ()

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "sk-cp-token-plan-abc")]

    types = [event.type for event in events]
    assert types[0] == "info"
    assert "Token Plan" in events[0].message
    assert types[-1] == "success"
    assert "sk-cp-token-plan-abc" not in "\n".join(event.json for event in events)


@pytest.mark.asyncio
async def test_login_minimax_does_not_emit_token_plan_event_for_pay_as_you_go(
    monkeypatch, tmp_path
):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return ()

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "sk-paygo-key")]

    types = [event.type for event in events]
    assert types == ["success"]


@pytest.mark.parametrize(
    "payload, expected_aliases",
    [
        (None, set()),
        ({}, set()),
        ({"data": "not a list"}, set()),
        ({"data": [{"context_length": 1000}]}, set()),
        ({"data": [{"id": "unknown-model"}]}, set()),
        ({"data": [{"id": "MiniMax-M2.7"}]}, {"minimax/m2.7"}),
    ],
)
def test_parse_discovered_minimax_models_handles_malformed_payloads(payload, expected_aliases):
    from pythinker_code.auth.minimax import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert {m.alias for m in result} == expected_aliases


def test_parse_discovered_minimax_models_overrides_context_length_only_for_positive_int():
    from pythinker_code.auth.minimax import _parse_discovered_models

    payload = {
        "data": [
            {"id": "MiniMax-M2.7", "context_length": "bogus"},
            {"id": "MiniMax-M2.5", "context_length": -5},
            {"id": "MiniMax-M2.5-highspeed", "context_length": 384_000},
        ]
    }
    result = _parse_discovered_models(payload)
    by_id = {m.model_id: m for m in result}
    assert by_id["MiniMax-M2.7"].max_context_size == 192_000
    assert by_id["MiniMax-M2.5"].max_context_size == 192_000
    assert by_id["MiniMax-M2.5-highspeed"].max_context_size == 384_000


@pytest.mark.asyncio
async def test_logout_minimax_removes_only_minimax(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import (
        MINIMAX_ANTHROPIC_PROVIDER_KEY,
        _apply_minimax_config,
        logout_minimax,
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
    _apply_minimax_config(config, SecretStr("mx-test"))

    events = [event async for event in logout_minimax(config)]

    assert events[-1].type == "success"
    assert MINIMAX_ANTHROPIC_PROVIDER_KEY not in config.providers
    assert "minimax/m2.7" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_minimax_preserves_non_minimax_default(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import _apply_minimax_config, logout_minimax
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
    _apply_minimax_config(config, SecretStr("mx-test"))
    config.default_model = "openai/gpt-5.2"

    events = [event async for event in logout_minimax(config)]

    assert events[-1].type == "success"
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_minimax_rejects_non_default_config_location():
    from pythinker_code.auth.minimax import logout_minimax

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_minimax(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
    assert config.providers == {}
    assert config.models == {}
