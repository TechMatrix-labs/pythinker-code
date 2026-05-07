from __future__ import annotations

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.config import Config


def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


def test_opencode_go_model_catalog_contains_all_current_models():
    from pythinker_code.auth.opencode_go import OPENCODE_GO_MODELS

    aliases = {model.alias for model in OPENCODE_GO_MODELS}
    assert aliases == {
        "opencode-go/glm-5",
        "opencode-go/glm-5.1",
        "opencode-go/kimi-k2.5",
        "opencode-go/kimi-k2.6",
        "opencode-go/deepseek-v4-pro",
        "opencode-go/deepseek-v4-flash",
        "opencode-go/mimo-v2-pro",
        "opencode-go/mimo-v2-omni",
        "opencode-go/mimo-v2.5-pro",
        "opencode-go/mimo-v2.5",
        "opencode-go/qwen3.5-plus",
        "opencode-go/qwen3.6-plus",
        "opencode-go/minimax-m2.5",
        "opencode-go/minimax-m2.7",
    }

    minimax = {
        m.model_id: m.provider_key for m in OPENCODE_GO_MODELS if m.model_id.startswith("minimax-")
    }
    assert minimax == {
        "minimax-m2.5": "managed:opencode-go-anthropic",
        "minimax-m2.7": "managed:opencode-go-anthropic",
    }
    assert all(
        m.provider_key == "managed:opencode-go-openai"
        for m in OPENCODE_GO_MODELS
        if not m.model_id.startswith("minimax-")
    )


def test_opencode_go_env_key_precedence(monkeypatch):
    from pythinker_code.auth.opencode_go import get_opencode_go_api_key_from_env

    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "zen-key")
    assert get_opencode_go_api_key_from_env() == "zen-key"

    monkeypatch.setenv("OPENCODE_API_KEY", "api-key")
    assert get_opencode_go_api_key_from_env() == "api-key"

    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-key")
    assert get_opencode_go_api_key_from_env() == "go-key"


def test_apply_opencode_go_config_writes_two_providers_and_default():
    from pythinker_code.auth.opencode_go import (
        OPENCODE_GO_ANTHROPIC_PROVIDER_KEY,
        OPENCODE_GO_BASE_URL,
        OPENCODE_GO_OPENAI_PROVIDER_KEY,
        _apply_opencode_go_config,
    )

    config = Config(is_from_default_location=True)

    _apply_opencode_go_config(config, SecretStr("ocgo-test"))

    assert set(config.providers) == {
        OPENCODE_GO_OPENAI_PROVIDER_KEY,
        OPENCODE_GO_ANTHROPIC_PROVIDER_KEY,
    }
    openai_provider = config.providers[OPENCODE_GO_OPENAI_PROVIDER_KEY]
    anthropic_provider = config.providers[OPENCODE_GO_ANTHROPIC_PROVIDER_KEY]
    assert openai_provider.type == "openai_legacy"
    assert anthropic_provider.type == "anthropic"
    assert openai_provider.base_url == OPENCODE_GO_BASE_URL
    assert anthropic_provider.base_url == OPENCODE_GO_BASE_URL
    assert openai_provider.api_key.get_secret_value() == "ocgo-test"
    assert anthropic_provider.api_key.get_secret_value() == "ocgo-test"
    assert config.models["opencode-go/kimi-k2.6"].provider == OPENCODE_GO_OPENAI_PROVIDER_KEY
    assert config.models["opencode-go/minimax-m2.7"].provider == OPENCODE_GO_ANTHROPIC_PROVIDER_KEY
    assert config.default_model == "opencode-go/kimi-k2.6"


@pytest.mark.asyncio
async def test_login_opencode_go_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "ocgo-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr(
        "pythinker_code.auth.opencode_go._discover_opencode_go_models", fake_discover
    )

    events = [event async for event in login_opencode_go_api_key(config, "ocgo-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "ocgo-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "opencode-go/kimi-k2.6"
    assert "opencode-go/minimax-m2.5" in config.models
    assert (tmp_path / "config.toml").exists()


@pytest.mark.asyncio
async def test_login_opencode_go_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://opencode.ai/zen/go/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr(
        "pythinker_code.auth.opencode_go._discover_opencode_go_models", fake_discover
    )

    events = [event async for event in login_opencode_go_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid OpenCode Go API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_opencode_go_uses_discovered_context_length(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import OpenCodeGoModel, login_opencode_go_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            OpenCodeGoModel(
                "kimi-k2.6",
                "Kimi K2.6",
                "managed:opencode-go-openai",
                512_000,
            ),
        )

    monkeypatch.setattr(
        "pythinker_code.auth.opencode_go._discover_opencode_go_models", fake_discover
    )

    events = [event async for event in login_opencode_go_api_key(config, "ocgo-test")]

    assert events[-1].type == "success"
    assert config.models["opencode-go/kimi-k2.6"].max_context_size == 512_000


@pytest.mark.asyncio
async def test_login_opencode_go_requires_key(tmp_path):
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_opencode_go_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "OpenCode Go API key is required."


@pytest.mark.asyncio
async def test_login_opencode_go_falls_back_on_non_auth_response_error(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://opencode.ai/zen/go/v1/models"),
            (),
            status=503,
            message="Service Unavailable",
        )

    monkeypatch.setattr(
        "pythinker_code.auth.opencode_go._discover_opencode_go_models", fake_discover
    )

    events = [event async for event in login_opencode_go_api_key(config, "ocgo-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert config.default_model == "opencode-go/kimi-k2.6"


@pytest.mark.parametrize(
    "payload, expected_aliases",
    [
        (None, set()),
        ({}, set()),
        ({"data": "not a list"}, set()),
        ({"data": [{"context_length": 1000}]}, set()),  # missing id
        ({"data": [{"id": "unknown-model"}]}, set()),  # unknown id dropped
        ({"data": [{"id": "kimi-k2.6"}]}, {"opencode-go/kimi-k2.6"}),
    ],
)
def test_parse_discovered_models_handles_malformed_payloads(payload, expected_aliases):
    from pythinker_code.auth.opencode_go import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert {m.alias for m in result} == expected_aliases


def test_parse_discovered_models_overrides_context_length_only_for_positive_int():
    from pythinker_code.auth.opencode_go import _parse_discovered_models

    payload = {
        "data": [
            {"id": "kimi-k2.6", "context_length": "bogus"},  # wrong type, ignored
            {"id": "glm-5", "context_length": -5},  # non-positive, ignored
            {"id": "deepseek-v4-pro", "context_length": 999_000},  # valid override
        ]
    }
    result = _parse_discovered_models(payload)
    by_id = {m.model_id: m for m in result}
    assert by_id["kimi-k2.6"].max_context_size == 262_000  # default preserved
    assert by_id["glm-5"].max_context_size == 262_000
    assert by_id["deepseek-v4-pro"].max_context_size == 999_000


@pytest.mark.asyncio
async def test_logout_opencode_go_removes_only_opencode_go(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import (
        OPENCODE_GO_ANTHROPIC_PROVIDER_KEY,
        OPENCODE_GO_OPENAI_PROVIDER_KEY,
        _apply_opencode_go_config,
        logout_opencode_go,
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
    _apply_opencode_go_config(config, SecretStr("ocgo-test"))

    events = [event async for event in logout_opencode_go(config)]

    assert events[-1].type == "success"
    assert OPENCODE_GO_OPENAI_PROVIDER_KEY not in config.providers
    assert OPENCODE_GO_ANTHROPIC_PROVIDER_KEY not in config.providers
    assert "opencode-go/kimi-k2.6" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_opencode_go_preserves_non_opencode_go_default(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import (
        _apply_opencode_go_config,
        logout_opencode_go,
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
    _apply_opencode_go_config(config, SecretStr("ocgo-test"))
    # The user explicitly set their default to a non-OpenCode-Go model.
    config.default_model = "openai/gpt-5.2"

    events = [event async for event in logout_opencode_go(config)]

    assert events[-1].type == "success"
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_opencode_go_rejects_non_default_config_location():
    from pythinker_code.auth.opencode_go import logout_opencode_go

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_opencode_go(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
    # No mutation must have occurred.
    assert config.providers == {}
    assert config.models == {}
