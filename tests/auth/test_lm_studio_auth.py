from __future__ import annotations

from typing import Any, cast

import aiohttp
import pytest
from pydantic import SecretStr

from pythinker_code.config import Config


def test_lm_studio_constants():
    from pythinker_code.auth.lm_studio import (
        LM_STUDIO_BASE_URL,
        LM_STUDIO_PROVIDER_KEY,
    )

    assert LM_STUDIO_BASE_URL == "http://localhost:1234/v1"
    assert LM_STUDIO_PROVIDER_KEY == "managed:lm-studio"


def test_lm_studio_env_resolution(monkeypatch):
    from pythinker_code.auth.lm_studio import (
        get_lm_studio_api_key_from_env,
        get_lm_studio_base_url_from_env,
    )

    monkeypatch.delenv("LM_STUDIO_API_KEY", raising=False)
    monkeypatch.delenv("LM_STUDIO_BASE_URL", raising=False)
    assert get_lm_studio_api_key_from_env() is None
    assert get_lm_studio_base_url_from_env() is None

    monkeypatch.setenv("LM_STUDIO_API_KEY", "  k  ")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://10.0.0.5:1234/v1")
    assert get_lm_studio_api_key_from_env() == "k"
    assert get_lm_studio_base_url_from_env() == "http://10.0.0.5:1234/v1"


def test_apply_lm_studio_config_writes_provider_and_models():
    from pythinker_code.auth.lm_studio import (
        LM_STUDIO_BASE_URL,
        LM_STUDIO_PROVIDER_KEY,
        LMStudioModel,
        _apply_lm_studio_config,
    )

    config = Config(is_from_default_location=True)
    models = (
        LMStudioModel(
            model_id="qwen2.5-coder-32b",
            display_name="Qwen2.5 Coder 32B (Q4_K_M)",
            max_context_size=32768,
        ),
        LMStudioModel(
            model_id="llama-3.1-8b",
            display_name="Llama 3.1 8B",
            max_context_size=131072,
        ),
    )

    _apply_lm_studio_config(
        config,
        SecretStr("local"),
        base_url=LM_STUDIO_BASE_URL,
        models=models,
    )

    assert config.providers[LM_STUDIO_PROVIDER_KEY].type == "openai_legacy"
    assert config.providers[LM_STUDIO_PROVIDER_KEY].base_url == LM_STUDIO_BASE_URL
    assert "lm-studio/llama-3.1-8b" in config.models
    # Default picks largest context window
    assert config.default_model == "lm-studio/llama-3.1-8b"


@pytest.mark.asyncio
async def test_login_emits_error_when_server_unreachable(monkeypatch):
    from pythinker_code.auth.lm_studio import login_lm_studio

    async def _raise(*args, **kwargs):
        raise aiohttp.ClientConnectorError(  # type: ignore[arg-type]
            connection_key=cast(Any, None), os_error=OSError("no")
        )

    monkeypatch.setattr("pythinker_code.auth.lm_studio._discover_lm_studio_models", _raise)

    config = Config(is_from_default_location=True)
    events = [event async for event in login_lm_studio(config)]
    assert any(e.type == "error" and "not reachable" in e.message for e in events)
    # No provider written when server is down
    assert "managed:lm-studio" not in config.providers


def test_apply_lm_studio_config_tiebreak_picks_alphabetically_first():
    from pythinker_code.auth.lm_studio import LMStudioModel, _apply_lm_studio_config

    config = Config(is_from_default_location=True)
    models = (
        LMStudioModel(model_id="zebra", display_name="Z", max_context_size=8192),
        LMStudioModel(model_id="alpha", display_name="A", max_context_size=8192),
    )
    _apply_lm_studio_config(
        config,
        SecretStr("local"),
        base_url="http://localhost:1234/v1",
        models=models,
    )
    assert config.default_model == "lm-studio/alpha"


@pytest.mark.asyncio
async def test_login_emits_error_when_base_url_is_blank():
    from pythinker_code.auth.lm_studio import login_lm_studio

    config = Config(is_from_default_location=True)
    events = [event async for event in login_lm_studio(config, base_url="   ")]
    assert any(e.type == "error" and "base URL is empty" in e.message for e in events)
    assert "managed:lm-studio" not in config.providers


@pytest.mark.asyncio
async def test_login_emits_error_on_401(monkeypatch):
    import aiohttp

    from pythinker_code.auth.lm_studio import login_lm_studio

    async def _raise(*args, **kwargs):
        raise aiohttp.ClientResponseError(
            request_info=None,  # type: ignore[arg-type]
            history=(),
            status=401,
            message="unauthorized",
        )

    monkeypatch.setattr("pythinker_code.auth.lm_studio._discover_lm_studio_models", _raise)
    config = Config(is_from_default_location=True)
    events = [event async for event in login_lm_studio(config)]
    assert any(e.type == "error" and "rejected the API key" in e.message for e in events)
    assert "managed:lm-studio" not in config.providers


def test_parse_native_lm_studio_models_skips_embeddings():
    from pythinker_code.auth.lm_studio import _parse_native_lm_studio_models

    payload = {
        "data": [
            {"id": "qwen2.5-coder", "type": "llm", "max_context_length": 32768, "arch": "qwen2"},
            {"id": "nomic-embed", "type": "embeddings", "max_context_length": 8192},
            {"id": "qwen-vl", "type": "vlm", "max_context_length": 16384, "arch": "qwen"},
        ]
    }
    parsed = _parse_native_lm_studio_models(payload)
    ids = {m.model_id for m in parsed}
    assert ids == {"qwen2.5-coder", "qwen-vl"}


def test_parse_native_lm_studio_models_handles_malformed_payload():
    from pythinker_code.auth.lm_studio import _parse_native_lm_studio_models

    assert _parse_native_lm_studio_models(None) == ()
    assert _parse_native_lm_studio_models({}) == ()
    assert _parse_native_lm_studio_models({"data": "not a list"}) == ()
    assert _parse_native_lm_studio_models({"data": [{"id": 123}]}) == ()  # non-string id skipped


@pytest.mark.asyncio
async def test_logout_lm_studio_clears_provider_and_models(monkeypatch, tmp_path):
    from pythinker_code.auth.lm_studio import (
        LM_STUDIO_PROVIDER_KEY,
        LMStudioModel,
        _apply_lm_studio_config,
        logout_lm_studio,
    )

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)
    _apply_lm_studio_config(
        config,
        SecretStr("local"),
        base_url="http://localhost:1234/v1",
        models=(LMStudioModel(model_id="m", display_name="M", max_context_size=4096),),
    )
    assert LM_STUDIO_PROVIDER_KEY in config.providers

    events = [event async for event in logout_lm_studio(config)]
    assert any(e.type == "success" for e in events)
    assert LM_STUDIO_PROVIDER_KEY not in config.providers
    assert all(m.provider != LM_STUDIO_PROVIDER_KEY for m in config.models.values())


@pytest.mark.asyncio
async def test_request_lm_studio_load_short_circuits_when_already_loaded(monkeypatch):
    """If /api/v0/models reports state='loaded', skip the /api/v1/models/load call."""
    from pythinker_code.auth.lm_studio import LMStudioLoadResult, request_lm_studio_load

    captured: dict[str, list[tuple[str, str]]] = {"urls": []}

    class _Resp:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def json(self, content_type=None):
            return self._payload

    class _Sess:
        def get(self, url, *, headers, timeout, raise_for_status):
            captured["urls"].append(("GET", url))
            return _Resp({"data": [{"id": "google/gemma-4-e4b", "state": "loaded", "type": "llm"}]})

        def post(self, url, *, json, headers, timeout):
            captured["urls"].append(("POST", url))
            return _Resp({"status": "loaded", "load_time_seconds": 0.0})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr("pythinker_code.auth.lm_studio.new_client_session", lambda: _Sess())

    result = await request_lm_studio_load(
        base_url="http://localhost:1234/v1",
        model_id="google/gemma-4-e4b",
        api_key="local",
    )
    assert isinstance(result, LMStudioLoadResult)
    assert result.status == "already-loaded"
    # Only the v0 GET fired — POST /api/v1/models/load was skipped.
    assert captured["urls"] == [("GET", "http://localhost:1234/api/v0/models")]


@pytest.mark.asyncio
async def test_request_lm_studio_load_surfaces_error_body(monkeypatch):
    """When LM Studio returns 500 with a JSON error body, raise with the actual message."""
    from pythinker_code.auth.lm_studio import request_lm_studio_load

    class _Resp:
        def __init__(self, payload, status):
            self._payload = payload
            self.status = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def json(self, content_type=None):
            return self._payload

    class _Sess:
        def get(self, url, *, headers, timeout, raise_for_status):
            # No model is loaded → falls through to POST.
            return _Resp({"data": []}, status=200)

        def post(self, url, *, json, headers, timeout):
            return _Resp(
                {"error": {"type": "model_load_failed", "message": "VRAM exhausted"}},
                status=500,
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr("pythinker_code.auth.lm_studio.new_client_session", lambda: _Sess())

    with pytest.raises(RuntimeError, match="VRAM exhausted"):
        await request_lm_studio_load(
            base_url="http://localhost:1234/v1",
            model_id="qwen/qwen3.6-35b-a3b",
            api_key="local",
        )


@pytest.mark.asyncio
async def test_login_warns_when_loaded_context_is_too_small(monkeypatch):
    """If a model is loaded in LM Studio with insufficient context, login emits
    an info event guiding the user to bump it before they hit a runtime error."""
    from pythinker_code.auth.lm_studio import LMStudioModel, login_lm_studio

    async def _fake_discover(*args, **kwargs):
        return (
            LMStudioModel(
                model_id="big-model-but-small-load",
                display_name="big",
                max_context_size=4096,
                state="loaded",
                max_context_length=262144,
                loaded_context_length=4096,
            ),
        )

    monkeypatch.setattr("pythinker_code.auth.lm_studio._discover_lm_studio_models", _fake_discover)
    monkeypatch.setattr("pythinker_code.auth.lm_studio.save_config", lambda c: None)

    config = Config(is_from_default_location=True)
    events = [event async for event in login_lm_studio(config)]
    info_events = [e for e in events if e.type == "info"]
    assert info_events, "expected an info event warning about small loaded context"
    msg = info_events[0].message
    assert "loaded with only 4096" in msg
    assert "Context Length" in msg
    assert "131072" in msg or "262144" in msg


@pytest.mark.asyncio
async def test_login_does_not_warn_for_unloaded_models(monkeypatch):
    """Unloaded models don't trigger the warning (their loaded ctx is 0)."""
    from pythinker_code.auth.lm_studio import LMStudioModel, login_lm_studio

    async def _fake_discover(*args, **kwargs):
        return (
            LMStudioModel(
                model_id="m",
                display_name="m",
                max_context_size=131072,
                state="not-loaded",
                max_context_length=131072,
                loaded_context_length=0,
            ),
        )

    monkeypatch.setattr("pythinker_code.auth.lm_studio._discover_lm_studio_models", _fake_discover)
    monkeypatch.setattr("pythinker_code.auth.lm_studio.save_config", lambda c: None)

    config = Config(is_from_default_location=True)
    events = [event async for event in login_lm_studio(config)]
    assert not [e for e in events if e.type == "info"]
