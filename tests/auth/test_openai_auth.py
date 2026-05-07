from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlsplit

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.auth import OPENAI_API_PLATFORM_ID, OPENAI_CHATGPT_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthError, load_tokens
from pythinker_code.auth.openai import (
    OPENAI_API_BASE_URL,
    OPENAI_AUTH_ISSUER,
    OPENAI_BROWSER_FALLBACK_PORT,
    OPENAI_BROWSER_PORT,
    OPENAI_BROWSER_REDIRECT_PATH,
    OPENAI_CHATGPT_BASE_URL,
    OPENAI_CHATGPT_OAUTH_KEY,
    OPENAI_CLIENT_ID,
    OPENAI_DEVICE_REDIRECT_URI,
    OPENAI_DEVICE_VERIFICATION_URL,
    PkceCodes,
    _apply_openai_config,
    _build_authorize_url,
    _discover_chatgpt_models,
    _exchange_id_token_for_api_key,
    _select_default_openai_model,
    _wait_for_browser_code,
    login_openai_api_key,
    login_openai_browser,
)
from pythinker_code.auth.platforms import (
    ModelInfo,
    managed_model_key,
    managed_provider_key,
    refresh_managed_models,
)
from pythinker_code.config import Config, LLMModel, LLMProvider, OAuthRef


def _model(model_id: str, *, reasoning: bool = False, image: bool = False) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        context_length=128000,
        supports_reasoning=reasoning,
        supports_image_in=image,
        supports_video_in=False,
        display_name=None,
    )


def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


def test_openai_auth_constants_match_codex_compatible_values():
    assert OPENAI_AUTH_ISSUER == "https://auth.openai.com"
    assert OPENAI_CLIENT_ID == "app_EMoamEEZ73f0CkXaXp7hrann"
    assert OPENAI_BROWSER_PORT == 1455
    assert OPENAI_BROWSER_FALLBACK_PORT == 1457
    assert OPENAI_BROWSER_REDIRECT_PATH == "/auth/callback"
    assert OPENAI_DEVICE_REDIRECT_URI == "https://auth.openai.com/deviceauth/callback"
    assert OPENAI_DEVICE_VERIFICATION_URL == "https://auth.openai.com/codex/device"
    assert OPENAI_CHATGPT_OAUTH_KEY == "oauth/openai-chatgpt"


def test_build_authorize_url_uses_codex_parameters():
    url = _build_authorize_url(
        redirect_uri="http://localhost:1455/auth/callback",
        pkce=PkceCodes(code_verifier="verifier", code_challenge="challenge"),
        state="state-123",
    )

    assert url.startswith("https://auth.openai.com/oauth/authorize?")
    assert "client_id=app_EMoamEEZ73f0CkXaXp7hrann" in url
    assert "code_challenge=challenge" in url
    assert "codex_cli_simplified_flow=true" in url
    assert "originator=codex_cli_rs" in url

    params = parse_qs(urlsplit(url).query)
    assert params["scope"] == [
        "openid profile email offline_access api.connectors.read api.connectors.invoke"
    ]
    assert params["id_token_add_organizations"] == ["true"]


@pytest.mark.asyncio
async def test_exchange_id_token_for_api_key_uses_codex_requested_token(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def json(self, content_type=None):
            return {"access_token": "openai-api-key-token"}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def post(self, url, *, data):
            captured["url"] = url
            captured["data"] = data
            return FakeResponse()

    monkeypatch.setattr("pythinker_code.auth.openai.new_client_session", FakeSession)

    token = await _exchange_id_token_for_api_key("id-token")

    assert token == "openai-api-key-token"
    assert captured["url"] == "https://auth.openai.com/oauth/token"
    assert captured["data"]["requested_token"] == "openai-api-key"
    assert "requested_token_type" not in captured["data"]


@pytest.mark.asyncio
async def test_wait_for_browser_code_accepts_localhost_callback(monkeypatch):
    monkeypatch.setattr(
        "pythinker_code.auth.openai._generate_pkce",
        lambda: PkceCodes(code_verifier="verifier", code_challenge="challenge"),
    )
    monkeypatch.setattr("pythinker_code.auth.openai._generate_state", lambda: "state-123")

    task = asyncio.create_task(_wait_for_browser_code(open_browser=False))
    writer = None
    actual_port = None
    try:
        for port in (OPENAI_BROWSER_PORT, OPENAI_BROWSER_FALLBACK_PORT):
            deadline = asyncio.get_running_loop().time() + 2
            while asyncio.get_running_loop().time() < deadline:
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", port)
                    actual_port = port
                    break
                except OSError:
                    await asyncio.sleep(0.01)
            if writer is not None:
                break

        assert writer is not None
        assert actual_port is not None
        writer.write(
            b"GET /auth/callback?code=auth-code&state=state-123 HTTP/1.1\r\nHost: localhost\r\n\r\n"
        )
        await writer.drain()

        result = await asyncio.wait_for(task, timeout=2)
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert result == (
        "auth-code",
        "verifier",
        f"http://localhost:{actual_port}/auth/callback",
    )


@pytest.mark.asyncio
async def test_wait_for_browser_code_cleans_up_idle_callback_tasks(monkeypatch):
    monkeypatch.setattr(
        "pythinker_code.auth.openai._generate_pkce",
        lambda: PkceCodes(code_verifier="verifier", code_challenge="challenge"),
    )
    monkeypatch.setattr("pythinker_code.auth.openai._generate_state", lambda: "state-123")

    task = asyncio.create_task(_wait_for_browser_code(open_browser=False))
    writer = None
    try:
        for port in (OPENAI_BROWSER_PORT, OPENAI_BROWSER_FALLBACK_PORT):
            deadline = asyncio.get_running_loop().time() + 2
            while asyncio.get_running_loop().time() < deadline:
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", port)
                    break
                except OSError:
                    await asyncio.sleep(0.01)
            if writer is not None:
                break

        assert writer is not None
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0.05)
        assert task.done()

        pending_callbacks = [
            pending
            for pending in asyncio.all_tasks()
            if pending is not asyncio.current_task()
            and getattr(pending.get_coro(), "__name__", None) == "_browser_callback_task"
            and not pending.done()
        ]
        assert pending_callbacks == []
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await asyncio.gather(task, return_exceptions=True)


def test_select_default_openai_model_prefers_codex_model():
    models = [_model("gpt-5.2"), _model("gpt-5.1-codex", reasoning=True), _model("gpt-4.1")]

    selected, thinking = _select_default_openai_model(models)

    assert selected.id == "gpt-5.1-codex"
    assert thinking is True


def test_select_default_openai_model_prefers_gpt55_when_available():
    models = [_model("gpt-5.3-codex", reasoning=True), _model("gpt-5.5", reasoning=True)]

    selected, thinking = _select_default_openai_model(models)

    assert selected.id == "gpt-5.5"
    assert thinking is True


def test_select_default_openai_model_rejects_empty_model_list():
    with pytest.raises(OAuthError, match="No OpenAI models available"):
        _select_default_openai_model([])


def test_select_default_openai_model_falls_back_to_gpt5_then_gpt_then_first():
    selected, thinking = _select_default_openai_model([_model("o3"), _model("gpt-5.2")])
    assert selected.id == "gpt-5.2"
    assert thinking is False

    selected, thinking = _select_default_openai_model([_model("o3"), _model("gpt-4.1")])
    assert selected.id == "gpt-4.1"
    assert thinking is False

    selected, thinking = _select_default_openai_model([_model("o3")])
    assert selected.id == "o3"
    assert thinking is False


def test_apply_openai_api_key_config_sets_managed_openai_default():
    config = Config(is_from_default_location=True)
    models = [_model("gpt-5.2", reasoning=True), _model("gpt-4.1")]

    _apply_openai_config(
        config,
        platform_id=OPENAI_API_PLATFORM_ID,
        provider_type="openai_responses",
        base_url=OPENAI_API_BASE_URL,
        api_key=SecretStr("sk-test"),
        oauth_ref=None,
        models=models,
        selected_model=models[0],
        thinking=True,
    )

    provider_key = managed_provider_key(OPENAI_API_PLATFORM_ID)
    assert config.providers[provider_key].type == "openai_responses"
    assert config.providers[provider_key].base_url == "https://api.openai.com/v1"
    assert config.providers[provider_key].api_key.get_secret_value() == "sk-test"
    assert config.providers[provider_key].oauth is None
    assert config.default_model == managed_model_key(OPENAI_API_PLATFORM_ID, "gpt-5.2")
    assert config.default_thinking is True


def test_apply_openai_chatgpt_config_stores_oauth_ref_not_token_in_config():
    config = Config(is_from_default_location=True)
    models = [_model("gpt-5.1-codex", reasoning=True)]
    oauth_ref = OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY)

    _apply_openai_config(
        config,
        platform_id=OPENAI_CHATGPT_PLATFORM_ID,
        provider_type="openai_codex",
        base_url=OPENAI_CHATGPT_BASE_URL,
        api_key=SecretStr(""),
        oauth_ref=oauth_ref,
        models=models,
        selected_model=models[0],
        thinking=True,
    )

    provider_key = managed_provider_key(OPENAI_CHATGPT_PLATFORM_ID)
    assert config.providers[provider_key].type == "openai_codex"
    assert config.providers[provider_key].base_url == "https://chatgpt.com/backend-api/codex"
    assert config.providers[provider_key].api_key.get_secret_value() == ""
    assert config.providers[provider_key].oauth == oauth_ref
    assert config.default_model == managed_model_key(OPENAI_CHATGPT_PLATFORM_ID, "gpt-5.1-codex")


@pytest.mark.asyncio
async def test_login_openai_api_key_saves_config_on_model_discovery(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_list_models(platform, api_key):
        assert platform.id == OPENAI_API_PLATFORM_ID
        assert api_key == "sk-test"
        return [_model("gpt-5.2", reasoning=True)]

    monkeypatch.setattr("pythinker_code.auth.openai.list_models", fake_list_models)

    events = [event async for event in login_openai_api_key(config, api_key="sk-test")]

    assert events[-1].type == "success"
    provider = config.providers[managed_provider_key(OPENAI_API_PLATFORM_ID)]
    assert provider.type == "openai_responses"
    assert provider.api_key.get_secret_value() == "sk-test"
    assert config.default_model == managed_model_key(OPENAI_API_PLATFORM_ID, "gpt-5.2")
    assert (tmp_path / "config.toml").exists()


@pytest.mark.asyncio
async def test_login_openai_api_key_does_not_save_on_401(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_list_models(platform, api_key):
        request_info = _request_info("https://api.openai.com/v1/models")
        raise aiohttp.ClientResponseError(request_info, (), status=401, message="Unauthorized")

    monkeypatch.setattr("pythinker_code.auth.openai.list_models", fake_list_models)

    events = [event async for event in login_openai_api_key(config, api_key="sk-bad")]
    assert events[-1].type == "error"
    assert "Invalid OpenAI API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_discover_chatgpt_models_reraises_401(monkeypatch):
    async def fake_list_models(platform, api_key):
        assert platform.id == OPENAI_CHATGPT_PLATFORM_ID
        assert api_key == "bad-token"
        request_info = _request_info("https://chatgpt.com/backend-api/codex/models")
        raise aiohttp.ClientResponseError(request_info, (), status=401, message="Unauthorized")

    monkeypatch.setattr("pythinker_code.auth.openai.list_models", fake_list_models)

    with pytest.raises(aiohttp.ClientResponseError) as exc_info:
        await _discover_chatgpt_models("bad-token")
    assert exc_info.value.status == 401


@pytest.mark.asyncio
async def test_discover_chatgpt_models_fallback_uses_current_supported_models(monkeypatch):
    async def fake_list_models(platform, api_key):
        raise RuntimeError("models endpoint unavailable")

    monkeypatch.setattr("pythinker_code.auth.openai.list_models", fake_list_models)

    models = await _discover_chatgpt_models("access-token")

    model_ids = [model.id for model in models]
    assert model_ids[:6] == [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2",
    ]
    assert "gpt-5.1-codex" not in model_ids


@pytest.mark.asyncio
async def test_login_openai_api_key_falls_back_to_public_models_on_non_auth_failure(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_list_models(platform, api_key):
        request_info = _request_info("https://api.openai.com/v1/models")
        raise aiohttp.ClientResponseError(
            request_info,
            (),
            status=500,
            message="Server error",
        )

    monkeypatch.setattr("pythinker_code.auth.openai.list_models", fake_list_models)

    events = [event async for event in login_openai_api_key(config, api_key="sk-test")]

    assert events[-1].type == "success"
    assert config.default_model == managed_model_key(OPENAI_API_PLATFORM_ID, "gpt-5.5")
    assert managed_model_key(OPENAI_API_PLATFORM_ID, "gpt-5-codex") in config.models


@pytest.mark.asyncio
async def test_refresh_managed_models_replaces_stale_chatgpt_codex_model_with_fallback(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    provider_key = managed_provider_key(OPENAI_CHATGPT_PLATFORM_ID)
    stale_model_key = managed_model_key(OPENAI_CHATGPT_PLATFORM_ID, "gpt-5.1-codex")
    config = Config(is_from_default_location=True)
    config.providers[provider_key] = LLMProvider(
        type="openai_codex",
        base_url=OPENAI_CHATGPT_BASE_URL,
        api_key=SecretStr("access-token"),
        oauth=OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY),
    )
    config.models[stale_model_key] = LLMModel(
        provider=provider_key,
        model="gpt-5.1-codex",
        max_context_size=1050000,
        capabilities={"thinking"},
    )
    config.default_model = stale_model_key

    async def fake_list_models(platform, api_key):
        raise RuntimeError("models endpoint unavailable")

    monkeypatch.setattr("pythinker_code.auth.platforms.list_models", fake_list_models)

    changed = await refresh_managed_models(config)

    assert changed is True
    assert config.default_model == managed_model_key(OPENAI_CHATGPT_PLATFORM_ID, "gpt-5.5")
    assert stale_model_key not in config.models
    assert managed_model_key(OPENAI_CHATGPT_PLATFORM_ID, "gpt-5.3-codex") in config.models


@pytest.mark.asyncio
async def test_login_openai_headless_stores_chatgpt_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_request_device_code():
        from pythinker_code.auth.openai import DeviceCode

        return DeviceCode(device_auth_id="dev-1", user_code="ABCD-1234", interval=1)

    async def fake_poll_device_code(device_code):
        assert device_code.device_auth_id == "dev-1"
        return {
            "authorization_code": "auth-code",
            "code_verifier": "verifier",
        }

    async def fake_exchange_code_for_tokens(code, verifier, redirect_uri):
        assert code == "auth-code"
        assert verifier == "verifier"
        assert redirect_uri == "https://auth.openai.com/deviceauth/callback"
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "openid profile email offline_access",
        }

    async def fake_exchange_id_token_for_api_key(id_token):
        return ""

    async def fake_discover_chatgpt_models(api_key):
        assert api_key == "access-token"
        return [_model("gpt-5.1-codex", reasoning=True)]

    monkeypatch.setattr("pythinker_code.auth.openai._request_device_code", fake_request_device_code)
    monkeypatch.setattr("pythinker_code.auth.openai._poll_device_code", fake_poll_device_code)
    monkeypatch.setattr(
        "pythinker_code.auth.openai._exchange_code_for_tokens", fake_exchange_code_for_tokens
    )
    monkeypatch.setattr(
        "pythinker_code.auth.openai._exchange_id_token_for_api_key",
        fake_exchange_id_token_for_api_key,
    )
    monkeypatch.setattr(
        "pythinker_code.auth.openai._discover_chatgpt_models",
        fake_discover_chatgpt_models,
    )

    from pythinker_code.auth.openai import login_openai_headless

    events = [event async for event in login_openai_headless(config)]

    assert [event.type for event in events] == ["verification_url", "waiting", "success"]
    token = load_tokens(OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY))
    assert token is not None
    assert token.access_token == "access-token"
    provider = config.providers[managed_provider_key(OPENAI_CHATGPT_PLATFORM_ID)]
    assert provider.type == "openai_codex"
    assert provider.oauth == OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY)
    Config.model_validate(config.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_login_openai_browser_finishes_with_callback_code(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_wait_for_browser_code(open_browser):
        assert open_browser is False
        return "auth-code", "verifier", "http://localhost:1455/auth/callback"

    async def fake_exchange_code_for_tokens(code, verifier, redirect_uri):
        assert code == "auth-code"
        assert verifier == "verifier"
        assert redirect_uri.startswith("http://localhost:")
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "openid profile email offline_access",
        }

    async def fake_discover_chatgpt_models(api_key):
        return [_model("gpt-5.1-codex", reasoning=True)]

    monkeypatch.setattr(
        "pythinker_code.auth.openai._wait_for_browser_code", fake_wait_for_browser_code
    )
    monkeypatch.setattr(
        "pythinker_code.auth.openai._exchange_code_for_tokens", fake_exchange_code_for_tokens
    )
    monkeypatch.setattr(
        "pythinker_code.auth.openai._discover_chatgpt_models", fake_discover_chatgpt_models
    )

    events = [event async for event in login_openai_browser(config, open_browser=False)]

    assert events[0].type == "verification_url"
    assert events[-1].type == "success"
    assert config.default_model == managed_model_key(OPENAI_CHATGPT_PLATFORM_ID, "gpt-5.1-codex")
