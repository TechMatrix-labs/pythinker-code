# OpenAI Codex Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace user-facing Pythinker auth/setup with OpenAI Codex-compatible login and OpenAI API-key setup.

**Architecture:** Add a focused `pythinker_code.auth.openai` module that owns OpenAI/Codex auth flows, model selection, credential storage, and OpenAI managed config writes. Keep the existing `OAuthEvent` and token file primitives from `pythinker_code.auth.oauth`, but refactor runtime token refresh so provider OAuth refs are not hard-coded to `pythinker-code`. Wire CLI and shell `/login`/`/setup` to the new OpenAI module and remove the old platform picker from user-facing auth.

**Tech Stack:** Python 3.12+, Typer, aiohttp, pydantic `SecretStr`, pytest/pytest-asyncio, existing config models, existing Pythinker Core `OpenAIResponses` provider.

---

## File Structure

- Create `src/pythinker_code/auth/openai.py`: OpenAI constants, PKCE helpers, browser callback server, device-code flow, API-key flow, OpenAI model selection, OpenAI config apply/remove helpers, ChatGPT token refresh.
- Modify `src/pythinker_code/auth/__init__.py`: add OpenAI platform/auth constants.
- Modify `src/pythinker_code/auth/platforms.py`: add OpenAI platform labels for managed provider names and model refresh support.
- Modify `src/pythinker_code/auth/oauth.py`: keep shared `OAuthEvent`/`OAuthToken`/file storage; update `OAuthManager` to discover all provider OAuth refs and dispatch refresh/apply logic by OAuth key.
- Modify `src/pythinker_code/llm.py`: add `openai_codex` provider type that uses `OpenAIResponses` against the Codex backend and participates in OpenAI env overrides.
- Modify `src/pythinker_code/cli/__init__.py`: make `pythinker login` and `pythinker logout` call OpenAI auth/logout.
- Modify `src/pythinker_code/ui/shell/oauth.py`: make `/login`, `/login browser`, `/login headless`, `/login api-key`, `/setup`, and `/logout` call OpenAI auth/logout.
- Leave `src/pythinker_code/ui/shell/setup.py` in place for now, but stop importing/using `select_platform` and `setup_platform` from user-facing auth.
- Create `tests/auth/test_openai_auth.py`: OpenAI auth unit tests with mocked sessions and temp share dir.
- Create `tests/core/test_openai_provider.py`: provider type/config/runtime refresh tests.
- Create `tests/cli/test_openai_login_cli.py`: Typer command routing tests.
- Create `tests/ui_and_conv/test_openai_shell_login.py`: shell slash routing tests with mocked auth flows.

## Researched Auth Details To Use

- Browser OAuth issuer: `https://auth.openai.com`.
- Browser client id: `app_EMoamEEZ73f0CkXaXp7hrann`.
- Browser authorize endpoint: `https://auth.openai.com/oauth/authorize`.
- Browser token endpoint: `https://auth.openai.com/oauth/token`.
- Browser redirect URI: `http://localhost:{port}/auth/callback`, preferred port `1455`, fallback port `1457`.
- Browser authorize params: `response_type=code`, `client_id`, `redirect_uri`, `scope=openid profile email offline_access api.connectors.read api.connectors.invoke`, `code_challenge`, `code_challenge_method=S256`, `id_token_add_organizations=true`, `codex_cli_simplified_flow=true`, `state`, `originator=codex_cli_rs`.
- Device user-code endpoint: `POST https://auth.openai.com/api/accounts/deviceauth/usercode` JSON `{"client_id": "app_EMoamEEZ73f0CkXaXp7hrann"}`.
- Device verification URL: `https://auth.openai.com/codex/device`.
- Device polling endpoint: `POST https://auth.openai.com/api/accounts/deviceauth/token` JSON with the `device_auth_id` returned by `/deviceauth/usercode` and the displayed `user_code` value.
- Device token exchange endpoint: `POST https://auth.openai.com/oauth/token` form `grant_type=authorization_code`, `client_id`, `code`, `code_verifier`, `redirect_uri=https://auth.openai.com/deviceauth/callback`.
- ChatGPT token API-key exchange endpoint: `POST https://auth.openai.com/oauth/token` form `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`, `client_id`, `requested_token=openai-api-key`, `subject_token=<id_token>`, `subject_token_type=urn:ietf:params:oauth:token-type:id_token`.
- OpenAI API-key base URL: `https://api.openai.com/v1`.
- ChatGPT/Codex backend base URL for Responses provider: `https://chatgpt.com/backend-api/codex` so the OpenAI SDK calls `https://chatgpt.com/backend-api/codex/responses`.

### Task 1: Constants And OpenAI Config Helpers

**Files:**
- Modify: `src/pythinker_code/auth/__init__.py`
- Create: `src/pythinker_code/auth/openai.py`
- Modify: `src/pythinker_code/auth/platforms.py`
- Test: `tests/auth/test_openai_auth.py`

- [ ] **Step 1: Write failing tests for model selection and config writes**

Create `tests/auth/test_openai_auth.py` with these tests first:

```python
from __future__ import annotations

from pydantic import SecretStr

from pythinker_code.auth import OPENAI_API_PLATFORM_ID, OPENAI_CHATGPT_PLATFORM_ID
from pythinker_code.auth.openai import (
    OPENAI_API_BASE_URL,
    OPENAI_CHATGPT_BASE_URL,
    OPENAI_CHATGPT_OAUTH_KEY,
    _apply_openai_config,
    _select_default_openai_model,
)
from pythinker_code.auth.platforms import ModelInfo, managed_model_key, managed_provider_key
from pythinker_code.config import Config, OAuthRef


def _model(model_id: str, *, reasoning: bool = False, image: bool = False) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        context_length=128000,
        supports_reasoning=reasoning,
        supports_image_in=image,
        supports_video_in=False,
        display_name=None,
    )


def test_select_default_openai_model_prefers_codex_model():
    models = [_model("gpt-5.2"), _model("gpt-5.1-codex", reasoning=True), _model("gpt-4.1")]

    selected, thinking = _select_default_openai_model(models)

    assert selected.id == "gpt-5.1-codex"
    assert thinking is True


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_openai_auth.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'pythinker_code.auth.openai'`.

- [ ] **Step 3: Add OpenAI constants**

Update `src/pythinker_code/auth/__init__.py` to:

```python
from __future__ import annotations

PYTHINKER_CODE_PLATFORM_ID = "pythinker-code"
OPENAI_API_PLATFORM_ID = "openai"
OPENAI_CHATGPT_PLATFORM_ID = "openai-chatgpt"

__all__ = [
    "OPENAI_API_PLATFORM_ID",
    "OPENAI_CHATGPT_PLATFORM_ID",
    "PYTHINKER_CODE_PLATFORM_ID",
]
```

- [ ] **Step 4: Add OpenAI platforms for labels/model refresh**

In `src/pythinker_code/auth/platforms.py`, import the new constants and add these two `Platform` entries after Pythinker:

```python
from pythinker_code.auth import (
    OPENAI_API_PLATFORM_ID,
    OPENAI_CHATGPT_PLATFORM_ID,
    PYTHINKER_CODE_PLATFORM_ID,
)
```

```python
    Platform(
        id=OPENAI_API_PLATFORM_ID,
        name="OpenAI API",
        base_url="https://api.openai.com/v1",
    ),
    Platform(
        id=OPENAI_CHATGPT_PLATFORM_ID,
        name="OpenAI ChatGPT Codex",
        base_url="https://chatgpt.com/backend-api/codex",
    ),
```

- [ ] **Step 5: Create OpenAI auth helper module**

Create `src/pythinker_code/auth/openai.py` with:

```python
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import OPENAI_API_PLATFORM_ID, OPENAI_CHATGPT_PLATFORM_ID
from pythinker_code.auth.oauth import (
    OAuthError,
    OAuthEvent,
    OAuthRef,
    OAuthToken,
    OAuthUnauthorized,
    delete_tokens,
    save_tokens,
)
from pythinker_code.auth.platforms import ModelInfo, list_models, managed_model_key, managed_provider_key
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session
from pythinker_code.utils.logging import logger

OPENAI_AUTH_ISSUER = "https://auth.openai.com"
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_BROWSER_PORT = 1455
OPENAI_BROWSER_FALLBACK_PORT = 1457
OPENAI_BROWSER_REDIRECT_PATH = "/auth/callback"
OPENAI_DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
OPENAI_DEVICE_VERIFICATION_URL = "https://auth.openai.com/codex/device"
OPENAI_API_BASE_URL = "https://api.openai.com/v1"
OPENAI_CHATGPT_BASE_URL = "https://chatgpt.com/backend-api/codex"
OPENAI_CHATGPT_OAUTH_KEY = "oauth/openai-chatgpt"

OpenAIProviderType = Literal["openai_responses", "openai_codex"]


@dataclass(slots=True, frozen=True)
class PkceCodes:
    code_verifier: str
    code_challenge: str


@dataclass(slots=True, frozen=True)
class DeviceCode:
    device_auth_id: str
    user_code: str
    interval: int


def _generate_pkce() -> PkceCodes:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode(
        "ascii"
    ).rstrip("=")
    return PkceCodes(code_verifier=verifier, code_challenge=challenge)


def _generate_state() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def _build_authorize_url(*, redirect_uri: str, pkce: PkceCodes, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": OPENAI_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email offline_access api.connectors.read api.connectors.invoke",
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": "codex_cli_rs",
    }
    return f"{OPENAI_AUTH_ISSUER}/oauth/authorize?{urlencode(params)}"


def _select_default_openai_model(models: list[ModelInfo]) -> tuple[ModelInfo, bool]:
    if not models:
        raise OAuthError("No OpenAI models available.")

    def score(model: ModelInfo) -> tuple[int, int]:
        model_id = model.id.lower()
        if "codex" in model_id or ("coding" in model_id and model_id.startswith("gpt")):
            return (0, 0)
        if model_id.startswith("gpt-5"):
            return (1, 0)
        if model_id.startswith("gpt"):
            return (2, 0)
        return (3, 0)

    selected = sorted(enumerate(models), key=lambda item: (score(item[1]), item[0]))[0][1]
    capabilities = selected.capabilities
    thinking = "thinking" in capabilities or "always_thinking" in capabilities
    return selected, thinking


def _apply_openai_config(
    config: Config,
    *,
    platform_id: str,
    provider_type: OpenAIProviderType,
    base_url: str,
    api_key: SecretStr,
    oauth_ref: OAuthRef | None,
    models: list[ModelInfo],
    selected_model: ModelInfo,
    thinking: bool,
) -> None:
    provider_key = managed_provider_key(platform_id)
    config.providers[provider_key] = LLMProvider(
        type=provider_type,
        base_url=base_url,
        api_key=api_key,
        oauth=oauth_ref,
    )
    for key, model in list(config.models.items()):
        if model.provider == provider_key:
            del config.models[key]
    for model_info in models:
        capabilities = model_info.capabilities or None
        config.models[managed_model_key(platform_id, model_info.id)] = LLMModel(
            provider=provider_key,
            model=model_info.id,
            max_context_size=model_info.context_length or 128000,
            capabilities=capabilities,
            display_name=model_info.display_name,
        )
    config.default_model = managed_model_key(platform_id, selected_model.id)
    config.default_thinking = thinking
```

- [ ] **Step 6: Run tests to verify helpers pass**

Run: `uv run pytest tests/auth/test_openai_auth.py -q`

Expected: PASS for the four helper tests.

- [ ] **Step 7: Commit task 1**

```bash
git add src/pythinker_code/auth/__init__.py src/pythinker_code/auth/openai.py src/pythinker_code/auth/platforms.py tests/auth/test_openai_auth.py
git commit -m "feat(auth): add OpenAI auth config helpers"
```

### Task 2: OpenAI API-Key Login

**Files:**
- Modify: `src/pythinker_code/auth/openai.py`
- Test: `tests/auth/test_openai_auth.py`

- [ ] **Step 1: Add failing tests for API-key login success/failure**

Append to `tests/auth/test_openai_auth.py`:

```python
import aiohttp
import pytest

from pythinker_code.auth.openai import login_openai_api_key


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
        request_info = aiohttp.RequestInfo(
            url=aiohttp.client_reqrep.URL("https://api.openai.com/v1/models"),
            method="GET",
            headers={},
            real_url=aiohttp.client_reqrep.URL("https://api.openai.com/v1/models"),
        )
        raise aiohttp.ClientResponseError(request_info, (), status=401, message="Unauthorized")

    monkeypatch.setattr("pythinker_code.auth.openai.list_models", fake_list_models)

    events = [event async for event in login_openai_api_key(config, api_key="sk-bad")]

    assert events[-1].type == "error"
    assert "Invalid OpenAI API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_openai_auth.py::test_login_openai_api_key_saves_config_on_model_discovery tests/auth/test_openai_auth.py::test_login_openai_api_key_does_not_save_on_401 -q`

Expected: FAIL with `ImportError` for `login_openai_api_key`.

- [ ] **Step 3: Implement API-key login**

Append to `src/pythinker_code/auth/openai.py`:

```python
async def login_openai_api_key(
    config: Config, api_key: str | None = None
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return
    if not api_key:
        yield OAuthEvent("error", "OpenAI API key is required.")
        return

    from pythinker_code.auth.platforms import get_platform_by_id

    platform = get_platform_by_id(OPENAI_API_PLATFORM_ID)
    if platform is None:
        yield OAuthEvent("error", "OpenAI API platform is unavailable.")
        return

    try:
        models = await list_models(platform, api_key)
    except aiohttp.ClientResponseError as exc:
        if exc.status == 401:
            yield OAuthEvent("error", "Invalid OpenAI API key; the key was not saved.")
            return
        yield OAuthEvent("error", f"Failed to validate OpenAI API key: {exc.message}")
        return
    except Exception as exc:
        yield OAuthEvent("error", f"Failed to validate OpenAI API key: {exc}")
        return

    if not models:
        yield OAuthEvent("error", "No OpenAI models are available for this API key.")
        return

    selected_model, thinking = _select_default_openai_model(models)
    _apply_openai_config(
        config,
        platform_id=OPENAI_API_PLATFORM_ID,
        provider_type="openai_responses",
        base_url=OPENAI_API_BASE_URL,
        api_key=SecretStr(api_key),
        oauth_ref=None,
        models=models,
        selected_model=selected_model,
        thinking=thinking,
    )
    save_config(config)
    yield OAuthEvent("success", f"OpenAI API key configured with model {selected_model.id}.")
```

- [ ] **Step 4: Run API-key tests**

Run: `uv run pytest tests/auth/test_openai_auth.py -q`

Expected: PASS.

- [ ] **Step 5: Commit task 2**

```bash
git add src/pythinker_code/auth/openai.py tests/auth/test_openai_auth.py
git commit -m "feat(auth): configure OpenAI API key login"
```

### Task 3: OpenAI ChatGPT Device-Code Login

**Files:**
- Modify: `src/pythinker_code/auth/openai.py`
- Test: `tests/auth/test_openai_auth.py`

- [ ] **Step 1: Add failing tests for device-code helpers and login**

Append to `tests/auth/test_openai_auth.py`:

```python
from pythinker_code.auth.oauth import load_tokens
from pythinker_code.config import OAuthRef


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
    monkeypatch.setattr("pythinker_code.auth.openai._exchange_code_for_tokens", fake_exchange_code_for_tokens)
    monkeypatch.setattr("pythinker_code.auth.openai._exchange_id_token_for_api_key", fake_exchange_id_token_for_api_key)
    monkeypatch.setattr("pythinker_code.auth.openai._discover_chatgpt_models", fake_discover_chatgpt_models)

    from pythinker_code.auth.openai import login_openai_headless

    events = [event async for event in login_openai_headless(config)]

    assert [event.type for event in events] == ["verification_url", "waiting", "success"]
    token = load_tokens(OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY))
    assert token is not None
    assert token.access_token == "access-token"
    provider = config.providers[managed_provider_key(OPENAI_CHATGPT_PLATFORM_ID)]
    assert provider.type == "openai_codex"
    assert provider.oauth == OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/auth/test_openai_auth.py::test_login_openai_headless_stores_chatgpt_tokens -q`

Expected: FAIL with missing `login_openai_headless` or helper attributes.

- [ ] **Step 3: Implement device-code HTTP helpers**

Append to `src/pythinker_code/auth/openai.py`:

```python
async def _request_device_code() -> DeviceCode:
    async with new_client_session() as session:
        async with session.post(
            f"{OPENAI_AUTH_ISSUER}/api/accounts/deviceauth/usercode",
            json={"client_id": OPENAI_CLIENT_ID},
            headers={"Accept": "application/json"},
        ) as response:
            data = await response.json(content_type=None)
            if response.status != 200:
                raise OAuthError(str(data))
    user_code = data.get("user_code") or data.get("usercode")
    if not user_code:
        raise OAuthError("Device-code response did not include a user code.")
    return DeviceCode(
        device_auth_id=str(data["device_auth_id"]),
        user_code=str(user_code),
        interval=int(data.get("interval") or 5),
    )


async def _poll_device_code(device_code: DeviceCode) -> dict[str, str]:
    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        await asyncio.sleep(max(device_code.interval, 1))
        async with new_client_session() as session:
            async with session.post(
                f"{OPENAI_AUTH_ISSUER}/api/accounts/deviceauth/token",
                json={"device_auth_id": device_code.device_auth_id, "user_code": device_code.user_code},
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 200:
                    payload = await response.json(content_type=None)
                    return {
                        "authorization_code": str(payload["authorization_code"]),
                        "code_verifier": str(payload["code_verifier"]),
                    }
                if response.status in (403, 404):
                    continue
                text = await response.text()
                raise OAuthError(f"Device-code authorization failed: {text}")
    raise OAuthError("Device-code authorization timed out.")


async def _exchange_code_for_tokens(
    authorization_code: str, code_verifier: str, redirect_uri: str
) -> dict[str, Any]:
    async with new_client_session() as session:
        async with session.post(
            f"{OPENAI_AUTH_ISSUER}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": OPENAI_CLIENT_ID,
                "code": authorization_code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            data = await response.json(content_type=None)
            if response.status != 200:
                raise OAuthError(str(data))
            return cast(dict[str, Any], data)


async def _exchange_id_token_for_api_key(id_token: str) -> str:
    async with new_client_session() as session:
        async with session.post(
            f"{OPENAI_AUTH_ISSUER}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": OPENAI_CLIENT_ID,
                "requested_token": "openai-api-key",
                "subject_token": id_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            if response.status != 200:
                return ""
            data = await response.json(content_type=None)
            return str(data.get("access_token") or "")


async def _discover_chatgpt_models(access_token: str) -> list[ModelInfo]:
    platform = type("PlatformLike", (), {"id": OPENAI_CHATGPT_PLATFORM_ID, "base_url": OPENAI_CHATGPT_BASE_URL, "allowed_prefixes": None})()
    try:
        return await list_models(platform, access_token)  # type: ignore[arg-type]
    except Exception:
        # The Codex backend may not expose /models consistently; seed known Codex-capable defaults.
        return [
            ModelInfo(
                id="gpt-5.1-codex",
                context_length=1050000,
                supports_reasoning=True,
                supports_image_in=True,
                supports_video_in=False,
                display_name="GPT-5.1 Codex",
            )
        ]
```

- [ ] **Step 4: Implement headless login**

Append to `src/pythinker_code/auth/openai.py`:

```python
def _token_from_openai_response(payload: dict[str, Any]) -> OAuthToken:
    normalized = dict(payload)
    normalized.setdefault("token_type", "Bearer")
    normalized.setdefault("scope", "openid profile email offline_access")
    normalized.setdefault("expires_in", 3600)
    return OAuthToken.from_response(normalized)


async def _finish_chatgpt_login(config: Config, token_payload: dict[str, Any]) -> AsyncIterator[OAuthEvent]:
    token = _token_from_openai_response(token_payload)
    oauth_ref = save_tokens(OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY), token)
    try:
        models = await _discover_chatgpt_models(token.access_token)
    except Exception as exc:
        logger.error("Failed to discover OpenAI ChatGPT models: {error}", error=exc)
        yield OAuthEvent("error", f"Logged in, but failed to discover OpenAI models: {exc}")
        return
    if not models:
        yield OAuthEvent("error", "Logged in, but no OpenAI ChatGPT models were available.")
        return
    selected_model, thinking = _select_default_openai_model(models)
    _apply_openai_config(
        config,
        platform_id=OPENAI_CHATGPT_PLATFORM_ID,
        provider_type="openai_codex",
        base_url=OPENAI_CHATGPT_BASE_URL,
        api_key=SecretStr(""),
        oauth_ref=oauth_ref,
        models=models,
        selected_model=selected_model,
        thinking=thinking,
    )
    save_config(config)
    yield OAuthEvent("success", f"OpenAI ChatGPT Codex login configured with model {selected_model.id}.")


async def login_openai_headless(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return
    try:
        device_code = await _request_device_code()
        yield OAuthEvent(
            "verification_url",
            f"Open {OPENAI_DEVICE_VERIFICATION_URL} and enter code {device_code.user_code}.",
            data={"verification_url": OPENAI_DEVICE_VERIFICATION_URL, "user_code": device_code.user_code},
        )
        yield OAuthEvent("waiting", "Waiting for OpenAI device-code authorization.")
        code = await _poll_device_code(device_code)
        token_payload = await _exchange_code_for_tokens(
            code["authorization_code"], code["code_verifier"], OPENAI_DEVICE_REDIRECT_URI
        )
    except Exception as exc:
        yield OAuthEvent("error", f"OpenAI device-code login failed: {exc}")
        return
    async for event in _finish_chatgpt_login(config, token_payload):
        yield event
```

- [ ] **Step 5: Run device-code tests**

Run: `uv run pytest tests/auth/test_openai_auth.py::test_login_openai_headless_stores_chatgpt_tokens -q`
Expected: PASS.

- [ ] **Step 6: Commit task 3**

```bash
git add src/pythinker_code/auth/openai.py tests/auth/test_openai_auth.py
git commit -m "feat(auth): add OpenAI Codex device login"
```

### Task 4: OpenAI ChatGPT Browser Login

**Files:**
- Modify: `src/pythinker_code/auth/openai.py`
- Test: `tests/auth/test_openai_auth.py`

- [ ] **Step 1: Add failing tests for PKCE URL and browser login orchestration**

Append to `tests/auth/test_openai_auth.py`:

```python
from pythinker_code.auth.openai import PkceCodes, _build_authorize_url, login_openai_browser


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


@pytest.mark.asyncio
async def test_login_openai_browser_finishes_with_callback_code(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_wait_for_browser_code(open_browser):
        assert open_browser is False
        return "auth-code", "verifier"

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

    monkeypatch.setattr("pythinker_code.auth.openai._wait_for_browser_code", fake_wait_for_browser_code)
    monkeypatch.setattr("pythinker_code.auth.openai._exchange_code_for_tokens", fake_exchange_code_for_tokens)
    monkeypatch.setattr("pythinker_code.auth.openai._discover_chatgpt_models", fake_discover_chatgpt_models)

    events = [event async for event in login_openai_browser(config, open_browser=False)]

    assert events[0].type == "verification_url"
    assert events[-1].type == "success"
    assert config.default_model == managed_model_key(OPENAI_CHATGPT_PLATFORM_ID, "gpt-5.1-codex")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/auth/test_openai_auth.py::test_build_authorize_url_uses_codex_parameters tests/auth/test_openai_auth.py::test_login_openai_browser_finishes_with_callback_code -q`

Expected: FAIL with missing `login_openai_browser` or `_wait_for_browser_code`.

- [ ] **Step 3: Implement callback server and browser login**

Append to `src/pythinker_code/auth/openai.py`:

```python
async def _handle_browser_callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: str) -> tuple[str | None, str | None]:
    request_line = await reader.readline()
    try:
        _, raw_path, _ = request_line.decode("utf-8", errors="replace").split(" ", 2)
    except ValueError:
        writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\nBad Request")
        await writer.drain()
        writer.close()
        return None, "Bad callback request."
    parsed = urlparse(raw_path)
    params = parse_qs(parsed.query)
    if parsed.path != OPENAI_BROWSER_REDIRECT_PATH:
        writer.write(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\nNot Found")
        await writer.drain()
        writer.close()
        return None, None
    if params.get("state", [""])[0] != state:
        writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\nState mismatch")
        await writer.drain()
        writer.close()
        return None, "State mismatch."
    if error := params.get("error", [""])[0]:
        message = params.get("error_description", [error])[0]
        body = f"Sign-in failed: {message}".encode("utf-8")
        writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
        writer.close()
        return None, message
    code = params.get("code", [""])[0]
    writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n"
        b"<html><body><h1>OpenAI login complete</h1><p>You can return to Pythinker.</p></body></html>"
    )
    await writer.drain()
    writer.close()
    return code, None


async def _wait_for_browser_code(open_browser: bool = True) -> tuple[str, str]:
    pkce = _generate_pkce()
    state = _generate_state()
    result: asyncio.Future[tuple[str | None, str | None]] = asyncio.get_running_loop().create_future()
    server: asyncio.AbstractServer | None = None
    actual_port = OPENAI_BROWSER_PORT
    for port in (OPENAI_BROWSER_PORT, OPENAI_BROWSER_FALLBACK_PORT):
        try:
            server = await asyncio.start_server(
                lambda reader, writer: asyncio.create_task(
                    _browser_callback_task(reader, writer, state, result)
                ),
                host="127.0.0.1",
                port=port,
            )
            actual_port = port
            break
        except OSError:
            continue
    if server is None:
        raise OAuthError("Could not start OpenAI login callback server on ports 1455 or 1457.")
    redirect_uri = f"http://localhost:{actual_port}{OPENAI_BROWSER_REDIRECT_PATH}"
    auth_url = _build_authorize_url(redirect_uri=redirect_uri, pkce=pkce, state=state)
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception as exc:
            logger.warning("Failed to open OpenAI auth URL: {error}", error=exc)
    try:
        code, error = await asyncio.wait_for(result, timeout=15 * 60)
    finally:
        server.close()
        await server.wait_closed()
    if error:
        raise OAuthError(error)
    if not code:
        raise OAuthError("OpenAI login callback did not include an authorization code.")
    return code, pkce.code_verifier


async def _browser_callback_task(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: str,
    result: asyncio.Future[tuple[str | None, str | None]],
) -> None:
    code, error = await _handle_browser_callback(reader, writer, state)
    if (code or error) and not result.done():
        result.set_result((code, error))


async def login_openai_browser(
    config: Config, *, open_browser: bool = True
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return
    yield OAuthEvent("verification_url", "Opening OpenAI ChatGPT login in your browser.")
    try:
        code, verifier = await _wait_for_browser_code(open_browser=open_browser)
        token_payload = await _exchange_code_for_tokens(
            code, verifier, f"http://localhost:{OPENAI_BROWSER_PORT}{OPENAI_BROWSER_REDIRECT_PATH}"
        )
    except Exception as exc:
        yield OAuthEvent("error", f"OpenAI browser login failed: {exc}")
        return
    async for event in _finish_chatgpt_login(config, token_payload):
        yield event
```

- [ ] **Step 4: Fix redirect URI port preservation**

Adjust `_wait_for_browser_code` to return `(code, verifier, redirect_uri)` and update `login_openai_browser` to pass the exact redirect URI used. Replace those two functions with:

```python
async def _wait_for_browser_code(open_browser: bool = True) -> tuple[str, str, str]:
    pkce = _generate_pkce()
    state = _generate_state()
    result: asyncio.Future[tuple[str | None, str | None]] = asyncio.get_running_loop().create_future()
    server: asyncio.AbstractServer | None = None
    actual_port = OPENAI_BROWSER_PORT
    for port in (OPENAI_BROWSER_PORT, OPENAI_BROWSER_FALLBACK_PORT):
        try:
            server = await asyncio.start_server(
                lambda reader, writer: asyncio.create_task(
                    _browser_callback_task(reader, writer, state, result)
                ),
                host="127.0.0.1",
                port=port,
            )
            actual_port = port
            break
        except OSError:
            continue
    if server is None:
        raise OAuthError("Could not start OpenAI login callback server on ports 1455 or 1457.")
    redirect_uri = f"http://localhost:{actual_port}{OPENAI_BROWSER_REDIRECT_PATH}"
    auth_url = _build_authorize_url(redirect_uri=redirect_uri, pkce=pkce, state=state)
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception as exc:
            logger.warning("Failed to open OpenAI auth URL: {error}", error=exc)
    try:
        code, error = await asyncio.wait_for(result, timeout=15 * 60)
    finally:
        server.close()
        await server.wait_closed()
    if error:
        raise OAuthError(error)
    if not code:
        raise OAuthError("OpenAI login callback did not include an authorization code.")
    return code, pkce.code_verifier, redirect_uri


async def login_openai_browser(
    config: Config, *, open_browser: bool = True
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return
    yield OAuthEvent("verification_url", "Opening OpenAI ChatGPT login in your browser.")
    try:
        code, verifier, redirect_uri = await _wait_for_browser_code(open_browser=open_browser)
        token_payload = await _exchange_code_for_tokens(code, verifier, redirect_uri)
    except Exception as exc:
        yield OAuthEvent("error", f"OpenAI browser login failed: {exc}")
        return
    async for event in _finish_chatgpt_login(config, token_payload):
        yield event
```

Update the test fake to return three values:

```python
async def fake_wait_for_browser_code(open_browser):
    assert open_browser is False
    return "auth-code", "verifier", "http://localhost:1455/auth/callback"
```

- [ ] **Step 5: Run browser login tests**

Run: `uv run pytest tests/auth/test_openai_auth.py -q`
Expected: PASS.

- [ ] **Step 6: Commit task 4**

```bash
git add src/pythinker_code/auth/openai.py tests/auth/test_openai_auth.py
git commit -m "feat(auth): add OpenAI Codex browser login"
```

### Task 5: OpenAI Provider Type And OAuth Refresh

**Files:**
- Modify: `src/pythinker_code/llm.py`
- Modify: `src/pythinker_code/auth/oauth.py`
- Modify: `src/pythinker_code/auth/openai.py`
- Test: `tests/core/test_openai_provider.py`

- [ ] **Step 1: Write failing provider and refresh tests**

Create `tests/core/test_openai_provider.py`:

```python
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from pythinker_code.auth.openai import OPENAI_CHATGPT_BASE_URL, OPENAI_CHATGPT_OAUTH_KEY
from pythinker_code.auth.oauth import OAuthManager, OAuthToken, save_tokens
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


def test_create_llm_supports_openai_codex_provider(monkeypatch):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_openai_provider.py -q`
Expected: FAIL because `openai_codex` is not a valid provider type and `OAuthManager` does not refresh this ref.

- [ ] **Step 3: Add provider type in `llm.py`**

Update `ProviderType` in `src/pythinker_code/llm.py`:

```python
type ProviderType = Literal[
    "pythinker",
    "openai_legacy",
    "openai_responses",
    "openai_codex",
    "anthropic",
    "google_genai",
    "gemini",
    "vertexai",
    "_echo",
    "_scripted_echo",
    "_chaos",
]
```

Update env overrides:

```python
        case "openai_legacy" | "openai_responses" | "openai_codex":
            if base_url := os.getenv("OPENAI_BASE_URL"):
                provider.base_url = base_url
            if api_key := os.getenv("OPENAI_API_KEY"):
                provider.api_key = SecretStr(api_key)
```

Add a match arm next to `openai_responses`:

```python
        case "openai_codex":
            from pythinker_core.contrib.chat_provider.openai_responses import OpenAIResponses

            chat_provider = OpenAIResponses(
                model=model.model,
                base_url=provider.base_url,
                api_key=resolved_api_key,
                default_headers=dict(provider.custom_headers) if provider.custom_headers else None,
            )
```

- [ ] **Step 4: Add OpenAI token refresh function**

Append to `src/pythinker_code/auth/openai.py`:

```python
async def refresh_openai_chatgpt_token(refresh_token: str) -> OAuthToken:
    async with new_client_session() as session:
        async with session.post(
            f"{OPENAI_AUTH_ISSUER}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": OPENAI_CLIENT_ID,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            data = await response.json(content_type=None)
            if response.status in (401, 403):
                raise OAuthUnauthorized(data.get("error_description") or "OpenAI token refresh unauthorized.")
            if response.status != 200:
                raise OAuthError(data.get("error_description") or f"OpenAI token refresh failed ({response.status}).")
    return _token_from_openai_response(cast(dict[str, Any], data))
```

- [ ] **Step 5: Refactor `OAuthManager` to refresh all provider refs**

In `src/pythinker_code/auth/oauth.py`, change `ensure_fresh` from using `_pythinker_code_ref()` to iterating provider refs. Replace the first lines of `ensure_fresh` body with:

```python
        refs = self._iter_oauth_refs()
        if not refs:
            return
        for ref in refs:
            token = load_tokens(ref)
            if token is None:
                continue
            if self._should_suppress_persisted_token(ref, token):
                self._access_tokens.pop(ref.key, None)
                self._apply_access_token(runtime, ref, "")
                if not self._can_retry_rejected_refresh_token(ref, token.refresh_token):
                    if force:
                        raise OAuthUnauthorized("Refresh token was recently rejected.")
                    continue
            else:
                self._cache_access_token(ref, token)
                if token.access_token:
                    self._apply_access_token(runtime, ref, token.access_token)
            await self._refresh_tokens(ref, token, runtime, force=force)
```

Change `_refresh_tokens` to call a dispatcher:

```python
                    refreshed = await self._refresh_token_for_ref(ref, refresh_token_value)
```

Add the dispatcher method inside `OAuthManager`:

```python
    async def _refresh_token_for_ref(self, ref: OAuthRef, refresh_token_value: str) -> OAuthToken:
        if ref.key == "oauth/openai-chatgpt":
            from pythinker_code.auth.openai import refresh_openai_chatgpt_token

            return await refresh_openai_chatgpt_token(refresh_token_value)
        return await refresh_token(refresh_token_value)
```

Change `_apply_access_token` signature and body:

```python
    def _apply_access_token(self, runtime: Runtime | None, ref: OAuthRef, access_token: str) -> None:
        if runtime is None:
            return
        if runtime.llm is None or runtime.llm.model_config is None:
            return
        provider_key = runtime.llm.model_config.provider
        provider = runtime.config.providers.get(provider_key)
        if provider is None or provider.oauth != ref:
            return
        fallback_api_key = provider.api_key.get_secret_value()
        replacement = access_token or fallback_api_key
        chat_provider = runtime.llm.chat_provider
        if hasattr(chat_provider, "client") and hasattr(chat_provider.client, "api_key"):
            chat_provider.client.api_key = replacement
            return
        if hasattr(chat_provider, "_client") and hasattr(chat_provider._client, "api_key"):
            chat_provider._client.api_key = replacement
```

Update all internal calls from `_apply_access_token(runtime, value)` to `_apply_access_token(runtime, ref, value)`.

- [ ] **Step 6: Run provider tests and OAuth refresh regression tests**

Run: `uv run pytest tests/core/test_openai_provider.py tests/auth/test_oauth_refresh.py -q`
Expected: PASS.

- [ ] **Step 7: Commit task 5**

```bash
git add src/pythinker_code/llm.py src/pythinker_code/auth/oauth.py src/pythinker_code/auth/openai.py tests/core/test_openai_provider.py
git commit -m "feat(auth): refresh OpenAI managed tokens"
```

### Task 6: CLI Login And Logout Routing

**Files:**
- Modify: `src/pythinker_code/cli/__init__.py`
- Modify: `src/pythinker_code/auth/openai.py`
- Test: `tests/cli/test_openai_login_cli.py`

- [ ] **Step 1: Write failing CLI routing tests**

Create `tests/cli/test_openai_login_cli.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator

from unittest.mock import Mock

from typer.testing import CliRunner

from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.cli import cli


runner = CliRunner()


async def _success_event(*args, **kwargs) -> AsyncIterator[OAuthEvent]:
    yield OAuthEvent("success", "ok")


def test_cli_login_defaults_to_openai_browser(monkeypatch):
    browser = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.login_openai_browser", browser, raising=False)
    monkeypatch.setattr("pythinker_code.cli.load_config", lambda: __import__("pythinker_code.config").config.Config(is_from_default_location=True), raising=False)

    result = runner.invoke(cli, ["login"])

    assert result.exit_code == 0
    assert "ok" in result.output
    assert browser.called


def test_cli_login_headless_routes_to_openai_headless(monkeypatch):
    headless = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.login_openai_headless", headless, raising=False)
    monkeypatch.setattr("pythinker_code.cli.load_config", lambda: __import__("pythinker_code.config").config.Config(is_from_default_location=True), raising=False)

    result = runner.invoke(cli, ["login", "--headless"])

    assert result.exit_code == 0
    assert headless.called


def test_cli_login_api_key_routes_to_openai_api_key(monkeypatch):
    api_key = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.login_openai_api_key", api_key, raising=False)
    monkeypatch.setattr("pythinker_code.cli.load_config", lambda: __import__("pythinker_code.config").config.Config(is_from_default_location=True), raising=False)

    result = runner.invoke(cli, ["login", "--api-key"], input="sk-test\n")

    assert result.exit_code == 0
    assert api_key.call_args.args[1] == "sk-test"


def test_cli_logout_routes_to_openai_logout(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.logout_openai", logout, raising=False)
    monkeypatch.setattr("pythinker_code.cli.load_config", lambda: __import__("pythinker_code.config").config.Config(is_from_default_location=True), raising=False)

    result = runner.invoke(cli, ["logout"])

    assert result.exit_code == 0
    assert logout.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -q`
Expected: FAIL because CLI imports/calls old Pythinker auth inside functions.

- [ ] **Step 3: Implement OpenAI logout helper**

Append to `src/pythinker_code/auth/openai.py`:

```python
async def logout_openai(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return
    delete_tokens(OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY))
    removed_default = False
    for platform_id in (OPENAI_API_PLATFORM_ID, OPENAI_CHATGPT_PLATFORM_ID):
        provider_key = managed_provider_key(platform_id)
        config.providers.pop(provider_key, None)
        for key, model in list(config.models.items()):
            if model.provider == provider_key:
                del config.models[key]
                if config.default_model == key:
                    removed_default = True
    if removed_default or config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of OpenAI successfully.")
```

- [ ] **Step 4: Hoist imports for monkeypatchable CLI routing**

At module top of `src/pythinker_code/cli/__init__.py`, add safe placeholders after Typer setup imports:

```python
from pythinker_code.config import load_config
from pythinker_code.auth.openai import (
    login_openai_api_key,
    login_openai_browser,
    login_openai_headless,
    logout_openai,
)
```

- [ ] **Step 5: Replace CLI `login` command**

Replace the current `login` command function in `src/pythinker_code/cli/__init__.py` with:

```python
@cli.command()
def login(
    json: bool = typer.Option(False, "--json", help="Emit OAuth events as JSON lines."),
    browser: bool = typer.Option(False, "--browser", help="Use OpenAI ChatGPT browser login."),
    headless: bool = typer.Option(False, "--headless", help="Use OpenAI ChatGPT device-code login."),
    api_key: bool = typer.Option(False, "--api-key", help="Configure OpenAI with an API key."),
) -> None:
    """Login with OpenAI."""
    import asyncio

    from rich.console import Console
    from rich.status import Status

    async def _run() -> bool:
        selected_modes = sum(bool(value) for value in (browser, headless, api_key))
        if selected_modes > 1:
            typer.echo("Choose only one of --browser, --headless, or --api-key.", err=True)
            return False
        config = load_config()
        if api_key:
            key = typer.prompt("OpenAI API key", hide_input=True).strip()
            events = login_openai_api_key(config, key)
        elif headless:
            events = login_openai_headless(config)
        else:
            events = login_openai_browser(config, open_browser=True)

        if json:
            ok = True
            async for event in events:
                typer.echo(event.json)
                if event.type == "error":
                    ok = False
            return ok

        console = Console()
        ok = True
        status: Status | None = None
        try:
            async for event in events:
                if event.type == "waiting":
                    if status is None:
                        status = console.status("Waiting for OpenAI authorization.")
                        status.start()
                    continue
                if status is not None:
                    status.stop()
                    status = None
                style = "red" if event.type == "error" else "green" if event.type == "success" else None
                console.print(event.message, markup=False, style=style)
                if event.type == "error":
                    ok = False
        finally:
            if status is not None:
                status.stop()
        return ok

    ok = asyncio.run(_run())
    if not ok:
        raise typer.Exit(code=1)
```

- [ ] **Step 6: Replace CLI `logout` imports/body to OpenAI**

Inside `logout`, remove imports of `logout_pythinker_code` and use `logout_openai(load_config())` in both JSON and terminal branches. The loop shape remains the same:

```python
            async for event in logout_openai(load_config()):
                typer.echo(event.json)
```

```python
        async for event in logout_openai(load_config()):
            match event.type:
                case "error":
                    style = "red"
                case "success":
                    style = "green"
                case _:
                    style = None
            console.print(event.message, markup=False, style=style)
            if event.type == "error":
                ok = False
```

- [ ] **Step 7: Run CLI tests**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -q`
Expected: PASS.

- [ ] **Step 8: Commit task 6**

```bash
git add src/pythinker_code/cli/__init__.py src/pythinker_code/auth/openai.py tests/cli/test_openai_login_cli.py
git commit -m "feat(cli): route login to OpenAI auth"
```

### Task 7: Shell `/login`, `/setup`, And `/logout`

**Files:**
- Modify: `src/pythinker_code/ui/shell/oauth.py`
- Test: `tests/ui_and_conv/test_openai_shell_login.py`

- [ ] **Step 1: Write failing shell routing tests**

Create `tests/ui_and_conv/test_openai_shell_login.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.cli import Reload
from pythinker_code.config import Config
from pythinker_code.ui.shell import oauth as shell_oauth


async def _success_event(*args, **kwargs) -> AsyncIterator[OAuthEvent]:
    yield OAuthEvent("success", "ok")


def _app() -> SimpleNamespace:
    runtime = SimpleNamespace(config=Config(is_from_default_location=True), llm=None)
    soul = SimpleNamespace(runtime=runtime)
    return SimpleNamespace(soul=soul)


@pytest.mark.asyncio
async def test_shell_login_defaults_to_openai_browser(monkeypatch):
    browser = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "login_openai_browser", browser)
    with pytest.raises(Reload):
        await shell_oauth.login(_app(), "")
    assert browser.called


@pytest.mark.asyncio
async def test_shell_login_headless_routes_to_openai_headless(monkeypatch):
    headless = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "login_openai_headless", headless)
    with pytest.raises(Reload):
        await shell_oauth.login(_app(), "headless")
    assert headless.called


@pytest.mark.asyncio
async def test_shell_setup_routes_to_openai_api_key(monkeypatch):
    api_key = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "login_openai_api_key", api_key)
    monkeypatch.setattr(shell_oauth, "_prompt_openai_api_key", lambda: _async_value("sk-test"))
    with pytest.raises(Reload):
        await shell_oauth.login(_app(), "api-key")
    assert api_key.call_args.args[1] == "sk-test"


async def _async_value(value):
    return value

```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -q`
Expected: FAIL because shell OAuth module imports and calls old platform picker.

- [ ] **Step 3: Replace shell OAuth imports**

In `src/pythinker_code/ui/shell/oauth.py`, remove these imports:

```python
from pythinker_code.auth import PYTHINKER_CODE_PLATFORM_ID
from pythinker_code.auth.oauth import login_pythinker_code, logout_pythinker_code
from pythinker_code.ui.shell.setup import select_platform, setup_platform
```

Add:

```python
from prompt_toolkit import PromptSession
from pythinker_code.auth.openai import (
    login_openai_api_key,
    login_openai_browser,
    login_openai_headless,
    logout_openai,
)
from pythinker_code.auth.platforms import is_managed_provider_key
```

- [ ] **Step 4: Add shell event renderer and API-key prompt**

Replace `_login_pythinker_code` with:

```python
async def _render_oauth_events(events) -> bool:
    status: Status | None = None
    ok = True
    try:
        async for event in events:
            if event.type == "waiting":
                if status is None:
                    status = console.status("[cyan]Waiting for OpenAI authorization.[/cyan]")
                    status.start()
                continue
            if status is not None:
                status.stop()
                status = None
            style = "red" if event.type == "error" else "green" if event.type == "success" else None
            console.print(event.message, markup=False, style=style)
            if event.type == "error":
                ok = False
    finally:
        if status is not None:
            status.stop()
    return ok


async def _prompt_openai_api_key() -> str | None:
    session = PromptSession[str]()
    try:
        value = await session.prompt_async(" OpenAI API key: ", is_password=True)
    except (EOFError, KeyboardInterrupt):
        return None
    return value.strip() or None
```

- [ ] **Step 5: Replace shell `login` command body**

Replace `login(app, args)` with:

```python
@registry.command(aliases=["setup"])
async def login(app: Shell, args: str) -> None:
    """Login with OpenAI or configure an OpenAI API key."""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    mode = args.strip().lower()
    if mode in ("", "browser"):
        ok = await _render_oauth_events(login_openai_browser(soul.runtime.config))
        provider = "openai-chatgpt"
    elif mode in ("headless", "device", "device-code"):
        ok = await _render_oauth_events(login_openai_headless(soul.runtime.config))
        provider = "openai-chatgpt"
    elif mode in ("api-key", "apikey", "api"):
        api_key = await _prompt_openai_api_key()
        if not api_key:
            console.print("[red]No OpenAI API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_openai_api_key(soul.runtime.config, api_key))
        provider = "openai"
    else:
        console.print("[red]Usage: /login [browser|headless|api-key][/red]")
        return
    if not ok:
        return
    from pythinker_code.telemetry import track

    track("login", provider=provider)
    await asyncio.sleep(1)
    console.clear()
    raise Reload
```

- [ ] **Step 6: Replace shell `logout` old Pythinker branch**

Simplify `logout(app, args)` after default-location check:

```python
    ok = await _render_oauth_events(logout_openai(config))
    if not ok:
        return
    await asyncio.sleep(1)
    console.clear()
    raise Reload
```

Keep `current_model_key` only if other code still imports it; otherwise remove unused parse/provider old logic.

- [ ] **Step 7: Run shell tests**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -q`
Expected: PASS.

- [ ] **Step 8: Commit task 7**

```bash
git add src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py
git commit -m "feat(shell): route login setup to OpenAI"
```

### Task 8: Cleanup, Regression Tests, And Verification

**Files:**
- Modify: `src/pythinker_code/ui/shell/setup.py` only if lint reports unused user-facing setup imports elsewhere.
- Modify: docs/help text only where tests or grep finds old login wording.
- Test: existing auth/config/CLI tests.

- [ ] **Step 1: Search for remaining user-facing Pythinker auth references**

Run: `uv run python - <<'PY'
from pathlib import Path
patterns = ["login_pythinker_code", "logout_pythinker_code", "select_platform", "setup_platform", "auth.pythinker.com"]
for path in Path("src/pythinker_code").rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    for pattern in patterns:
        if pattern in text:
            print(f"{path}:{pattern}")
PY`

Expected: remaining matches are either inside `src/pythinker_code/auth/oauth.py` legacy internals or test files that explicitly verify old paths are not used. No match should remain in `src/pythinker_code/cli/__init__.py` or `src/pythinker_code/ui/shell/oauth.py`.

- [ ] **Step 2: Run targeted tests**

Run: `uv run pytest tests/auth/test_openai_auth.py tests/core/test_openai_provider.py tests/cli/test_openai_login_cli.py tests/ui_and_conv/test_openai_shell_login.py tests/auth/test_oauth_refresh.py tests/core/test_config.py -q`

Expected: PASS.

- [ ] **Step 3: Run format and checks**

Run: `make format`

Expected: command exits 0 and formats modified files.

Run: `make check`

Expected: command exits 0.

- [ ] **Step 4: Run full tests if targeted suite passes**

Run: `make test`

Expected: command exits 0. If unrelated pre-existing failures appear, capture the failing test names and verify the targeted OpenAI tests still pass.

- [ ] **Step 5: Manual smoke checks without real OpenAI network**

Run: `uv run pythinker login --help`

Expected: help mentions OpenAI login flags and does not describe Pythinker account OAuth.

Run: `uv run pythinker --print --prompt test`

Expected: no config validation crash. If no model is configured, it should still report that LLM is not set and suggest `/login`.

- [ ] **Step 6: Commit cleanup**

```bash
git add src tests docs/superpowers/specs/2026-05-05-openai-codex-auth-design.md docs/superpowers/plans/2026-05-05-openai-codex-auth.md
git commit -m "test(auth): verify OpenAI login replacement"
```

## Self-Review Checklist

- Spec coverage: Tasks cover default browser login, headless device-code login, API-key setup, credential storage, provider config, model selection, logout, removal of user-facing Pythinker OAuth, tests, and no external `codex` binary dependency.
- Placeholder scan: The plan contains no unfinished markers and no unspecified implementation slots.
- Type consistency: The plan consistently uses `OPENAI_API_PLATFORM_ID`, `OPENAI_CHATGPT_PLATFORM_ID`, `OPENAI_CHATGPT_OAUTH_KEY`, `login_openai_browser`, `login_openai_headless`, `login_openai_api_key`, `logout_openai`, and provider type `openai_codex`.
