from __future__ import annotations

from typing import Any, cast

import aiohttp
import pytest
from pydantic import SecretStr

from pythinker_code.config import Config


def test_ollama_constants():
    from pythinker_code.auth.ollama import OLLAMA_BASE_URL, OLLAMA_PROVIDER_KEY

    assert OLLAMA_BASE_URL == "http://localhost:11434/v1"
    assert OLLAMA_PROVIDER_KEY == "managed:ollama"


def test_ollama_env_resolution(monkeypatch):
    from pythinker_code.auth.ollama import (
        get_ollama_api_key_from_env,
        get_ollama_base_url_from_env,
    )

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert get_ollama_api_key_from_env() is None
    assert get_ollama_base_url_from_env() is None

    monkeypatch.setenv("OLLAMA_API_KEY", " k ")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.5:11434/v1")
    assert get_ollama_api_key_from_env() == "k"
    assert get_ollama_base_url_from_env() == "http://192.168.0.5:11434/v1"


def test_parse_tags_payload_extracts_chat_models():
    from pythinker_code.auth.ollama import _parse_tags_payload

    payload = {
        "models": [
            {
                "name": "llama3.1:8b",
                "size": 4_000_000_000,
                "details": {
                    "family": "llama",
                    "parameter_size": "8B",
                    "quantization_level": "Q4_K_M",
                },
            },
            {"name": "mxbai-embed-large", "details": {"family": "bert"}},
        ]
    }
    parsed = _parse_tags_payload(payload)
    assert {m.model_id for m in parsed} == {"llama3.1:8b"}
    only = parsed[0]
    assert only.display_name == "llama3.1:8b — 8B Q4_K_M"


def test_parse_tags_payload_handles_malformed_payload():
    from pythinker_code.auth.ollama import _parse_tags_payload

    assert _parse_tags_payload(None) == ()
    assert _parse_tags_payload({}) == ()
    assert _parse_tags_payload({"models": "not a list"}) == ()
    assert _parse_tags_payload({"models": [{"name": 123}]}) == ()


def test_apply_ollama_config_writes_provider_and_models():
    from pythinker_code.auth.ollama import (
        OLLAMA_BASE_URL,
        OLLAMA_PROVIDER_KEY,
        OllamaModel,
        _apply_ollama_config,
    )

    config = Config(is_from_default_location=True)
    models = (
        OllamaModel(
            model_id="llama3.1:8b",
            display_name="llama3.1:8b — 8B Q4_K_M",
            max_context_size=131072,
        ),
        OllamaModel(
            model_id="qwen2.5-coder:7b",
            display_name="qwen2.5-coder:7b — 7B Q4_K_M",
            max_context_size=32768,
        ),
    )
    _apply_ollama_config(
        config,
        SecretStr("local"),
        base_url=OLLAMA_BASE_URL,
        models=models,
    )
    assert config.providers[OLLAMA_PROVIDER_KEY].type == "openai_legacy"
    assert config.providers[OLLAMA_PROVIDER_KEY].base_url == OLLAMA_BASE_URL
    assert config.default_model == "ollama/llama3.1:8b"


def test_apply_ollama_config_tiebreak_picks_alphabetically_first():
    from pythinker_code.auth.ollama import OllamaModel, _apply_ollama_config

    config = Config(is_from_default_location=True)
    models = (
        OllamaModel(model_id="zebra:7b", display_name="z", max_context_size=8192),
        OllamaModel(model_id="alpha:7b", display_name="a", max_context_size=8192),
    )
    _apply_ollama_config(
        config,
        SecretStr("local"),
        base_url="http://localhost:11434/v1",
        models=models,
    )
    assert config.default_model == "ollama/alpha:7b"


@pytest.mark.asyncio
async def test_login_emits_error_when_server_unreachable(monkeypatch):
    from pythinker_code.auth.ollama import login_ollama

    async def _raise(*args, **kwargs):
        raise aiohttp.ClientConnectorError(  # type: ignore[arg-type]
            connection_key=cast(Any, None), os_error=OSError("no")
        )

    monkeypatch.setattr("pythinker_code.auth.ollama._discover_ollama_models", _raise)

    config = Config(is_from_default_location=True)
    events = [event async for event in login_ollama(config)]
    assert any(e.type == "error" and "not reachable" in e.message for e in events)
    assert "managed:ollama" not in config.providers


@pytest.mark.asyncio
async def test_login_emits_error_when_base_url_is_blank():
    from pythinker_code.auth.ollama import login_ollama

    config = Config(is_from_default_location=True)
    events = [event async for event in login_ollama(config, base_url="   ")]
    assert any(e.type == "error" and "base URL is empty" in e.message for e in events)
    assert "managed:ollama" not in config.providers


@pytest.mark.asyncio
async def test_login_emits_error_on_401(monkeypatch):
    from pythinker_code.auth.ollama import login_ollama

    async def _raise(*args, **kwargs):
        raise aiohttp.ClientResponseError(
            request_info=None,  # type: ignore[arg-type]
            history=(),
            status=401,
            message="unauthorized",
        )

    monkeypatch.setattr("pythinker_code.auth.ollama._discover_ollama_models", _raise)
    config = Config(is_from_default_location=True)
    events = [event async for event in login_ollama(config)]
    assert any(e.type == "error" and "rejected the API key" in e.message for e in events)
    assert "managed:ollama" not in config.providers


@pytest.mark.asyncio
async def test_login_emits_error_when_no_models_pulled(monkeypatch):
    from pythinker_code.auth.ollama import login_ollama

    async def _no_models(*args, **kwargs):
        return ()

    monkeypatch.setattr("pythinker_code.auth.ollama._discover_ollama_models", _no_models)
    config = Config(is_from_default_location=True)
    events = [event async for event in login_ollama(config)]
    assert any(e.type == "error" and "ollama pull" in e.message for e in events)
    assert "managed:ollama" not in config.providers


@pytest.mark.asyncio
async def test_logout_ollama_clears_provider_and_models(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))

    from pythinker_code.auth.ollama import (
        OLLAMA_PROVIDER_KEY,
        OllamaModel,
        _apply_ollama_config,
        logout_ollama,
    )

    config = Config(is_from_default_location=True)
    _apply_ollama_config(
        config,
        SecretStr("local"),
        base_url="http://localhost:11434/v1",
        models=(OllamaModel(model_id="m", display_name="m", max_context_size=4096),),
    )
    assert OLLAMA_PROVIDER_KEY in config.providers

    events = [event async for event in logout_ollama(config)]
    assert any(e.type == "success" for e in events)
    assert OLLAMA_PROVIDER_KEY not in config.providers
    assert all(m.provider != OLLAMA_PROVIDER_KEY for m in config.models.values())
