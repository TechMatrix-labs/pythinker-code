from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import secrets
import time
import webbrowser
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import OPENAI_API_PLATFORM_ID, OPENAI_CHATGPT_PLATFORM_ID
from pythinker_code.auth.oauth import (
    OAuthError,
    OAuthEvent,
    OAuthToken,
    OAuthUnauthorized,
    delete_tokens,
    save_tokens,
)
from pythinker_code.auth.platforms import (
    ModelInfo,
    Platform,
    list_models,
    managed_model_key,
    managed_provider_key,
)
from pythinker_code.config import Config, LLMModel, LLMProvider, OAuthRef, save_config
from pythinker_code.utils.aiohttp import new_client_session

OPENAI_API_BASE_URL = "https://api.openai.com/v1"
OPENAI_CHATGPT_BASE_URL = "https://chatgpt.com/backend-api/codex"
OPENAI_AUTH_ISSUER = "https://auth.openai.com"
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_BROWSER_PORT = 1455
OPENAI_BROWSER_FALLBACK_PORT = 1457
OPENAI_BROWSER_REDIRECT_PATH = "/auth/callback"
OPENAI_DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
OPENAI_DEVICE_VERIFICATION_URL = "https://auth.openai.com/codex/device"
OPENAI_CHATGPT_OAUTH_KEY = "oauth/openai-chatgpt"

OPENAI_CHATGPT_FALLBACK_MODELS = [
    ModelInfo(
        id="gpt-5.5",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5.5",
    ),
    ModelInfo(
        id="gpt-5.4",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5.4",
    ),
    ModelInfo(
        id="gpt-5.4-mini",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5.4 Mini",
    ),
    ModelInfo(
        id="gpt-5.3-codex",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5.3 Codex",
    ),
    ModelInfo(
        id="gpt-5.3-codex-spark",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5.3 Codex Spark",
    ),
    ModelInfo(
        id="gpt-5.2",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5.2",
    ),
]

OPENAI_API_FALLBACK_MODELS = [
    *OPENAI_CHATGPT_FALLBACK_MODELS,
    ModelInfo(
        id="gpt-5.4-nano",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5.4 Nano",
    ),
    ModelInfo(
        id="gpt-5.1",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5.1",
    ),
    ModelInfo(
        id="gpt-5",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5",
    ),
    ModelInfo(
        id="gpt-5-codex",
        context_length=400000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-5 Codex",
    ),
    ModelInfo(
        id="gpt-4.1",
        context_length=1047576,
        supports_reasoning=False,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-4.1",
    ),
    ModelInfo(
        id="gpt-4.1-mini",
        context_length=1047576,
        supports_reasoning=False,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-4.1 Mini",
    ),
    ModelInfo(
        id="gpt-4.1-nano",
        context_length=1047576,
        supports_reasoning=False,
        supports_image_in=True,
        supports_video_in=False,
        display_name="GPT-4.1 Nano",
    ),
    ModelInfo(
        id="o3",
        context_length=200000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="o3",
    ),
    ModelInfo(
        id="o4-mini",
        context_length=200000,
        supports_reasoning=True,
        supports_image_in=True,
        supports_video_in=False,
        display_name="o4-mini",
    ),
]


@dataclass(frozen=True, slots=True)
class PkceCodes:
    code_verifier: str
    code_challenge: str


@dataclass(frozen=True, slots=True)
class DeviceCode:
    device_auth_id: str
    user_code: str
    interval: int = 5


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _generate_pkce() -> PkceCodes:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode(encoding="utf-8")).digest())
    return PkceCodes(code_verifier=verifier, code_challenge=challenge)


def _generate_state() -> str:
    return secrets.token_urlsafe(32)


def _build_authorize_url(
    *,
    redirect_uri: str,
    pkce: PkceCodes,
    state: str,
    authorize_url: str = f"{OPENAI_AUTH_ISSUER}/oauth/authorize",
    client_id: str = OPENAI_CLIENT_ID,
    scope: str = "openid profile email offline_access api.connectors.read api.connectors.invoke",
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "code_challenge": pkce.code_challenge,
            "code_challenge_method": "S256",
            "codex_cli_simplified_flow": "true",
            "id_token_add_organizations": "true",
            "originator": "codex_cli_rs",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
        }
    )
    return f"{authorize_url}?{query}"


async def _handle_browser_callback(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: str
) -> tuple[str | None, str | None]:
    line = await reader.readline()
    parts = line.decode("utf-8", errors="replace").strip().split()
    code: str | None = None
    error: str | None = None

    if len(parts) < 2:
        error = "Invalid OpenAI callback request."
    else:
        parsed = urlsplit(parts[1])
        params = parse_qs(parsed.query)
        if parsed.path != OPENAI_BROWSER_REDIRECT_PATH:
            error = "Invalid OpenAI callback path."
        elif params.get("state", [None])[0] != state:
            error = "Invalid OpenAI callback state."
        elif params.get("error", [None])[0]:
            error = params.get("error_description", params["error"])[0]
        else:
            code = params.get("code", [None])[0]
            if not code:
                error = "OpenAI callback did not include an authorization code."

    ok = code is not None and error is None
    title = "OpenAI login complete" if ok else "OpenAI login failed"
    body = "You can close this window and return to Pythinker." if ok else error
    html = f"<html><body><h1>{title}</h1><p>{body}</p></body></html>"
    status = "200 OK" if ok else "400 Bad Request"
    writer.write(
        bytes(
            f"HTTP/1.1 {status}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(html.encode('utf-8'))}\r\n"
            "Connection: close\r\n\r\n"
            f"{html}",
            encoding="utf-8",
        )
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()
    return code, error


async def _browser_callback_task(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: str,
    result: asyncio.Future[tuple[str | None, str | None]],
) -> None:
    try:
        code, error = await _handle_browser_callback(reader, writer, state)
    except asyncio.CancelledError:
        writer.close()
        await writer.wait_closed()
        raise
    if not result.done() and (code or error):
        result.set_result((code, error))


def _track_browser_callback_task(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: str,
    result: asyncio.Future[tuple[str | None, str | None]],
    callback_tasks: set[asyncio.Task[None]],
) -> None:
    task = asyncio.create_task(_browser_callback_task(reader, writer, state, result))
    callback_tasks.add(task)
    task.add_done_callback(callback_tasks.discard)


async def _wait_for_browser_code(open_browser: bool = True) -> tuple[str, str, str]:
    pkce = _generate_pkce()
    state = _generate_state()
    result: asyncio.Future[tuple[str | None, str | None]] = (
        asyncio.get_running_loop().create_future()
    )
    callback_tasks: set[asyncio.Task[None]] = set()
    server: asyncio.Server | None = None
    redirect_uri = ""

    for port in (OPENAI_BROWSER_PORT, OPENAI_BROWSER_FALLBACK_PORT):
        try:
            server = await asyncio.start_server(
                lambda reader, writer: _track_browser_callback_task(
                    reader, writer, state, result, callback_tasks
                ),
                "127.0.0.1",
                port,
            )
        except OSError:
            continue
        redirect_uri = f"http://localhost:{port}{OPENAI_BROWSER_REDIRECT_PATH}"
        break

    if server is None:
        raise OAuthError("Failed to start OpenAI browser callback server.")

    auth_url = _build_authorize_url(redirect_uri=redirect_uri, pkce=pkce, state=state)
    if open_browser:
        webbrowser.open(auth_url)

    try:
        code, error = await asyncio.wait_for(result, timeout=15 * 60)
    finally:
        server.close()
        for task in callback_tasks:
            task.cancel()
        if callback_tasks:
            await asyncio.gather(*callback_tasks, return_exceptions=True)
        await server.wait_closed()

    if error:
        raise OAuthError(error)
    if not code:
        raise OAuthError("OpenAI callback did not include an authorization code.")
    return code, pkce.code_verifier, redirect_uri


def _select_default_openai_model(models: list[ModelInfo]) -> tuple[ModelInfo, bool]:
    if not models:
        raise OAuthError("No OpenAI models available.")

    for model in models:
        if model.id.lower() == "gpt-5.5":
            return model, model.supports_reasoning

    for model in models:
        if "codex" in model.id.lower():
            return model, model.supports_reasoning
    for model in models:
        if model.id.lower().startswith("gpt-5"):
            return model, False
    for model in models:
        if model.id.lower().startswith("gpt"):
            return model, False
    return models[0], False


def _apply_openai_config(
    config: Config,
    *,
    platform_id: str,
    provider_type: str,
    base_url: str,
    api_key: SecretStr,
    oauth_ref: OAuthRef | None,
    models: list[ModelInfo],
    selected_model: ModelInfo,
    thinking: bool,
) -> None:
    provider_key = managed_provider_key(platform_id)
    config.providers[provider_key] = LLMProvider.model_construct(
        type=provider_type,
        base_url=base_url,
        api_key=api_key,
        oauth=oauth_ref,
    )

    for model in models:
        config.models[managed_model_key(platform_id, model.id)] = LLMModel(
            provider=provider_key,
            model=model.id,
            max_context_size=model.context_length,
            capabilities=model.capabilities or None,
            display_name=model.display_name,
        )

    config.default_model = managed_model_key(platform_id, selected_model.id)
    config.default_thinking = thinking


async def _request_device_code() -> DeviceCode:
    async with (
        new_client_session() as session,
        session.post(
            f"{OPENAI_AUTH_ISSUER}/api/accounts/deviceauth/usercode",
            json={"client_id": OPENAI_CLIENT_ID},
        ) as response,
    ):
        payload = await response.json(content_type=None)
        status = response.status

    if status != 200:
        raise OAuthError(f"Failed to request OpenAI device code: HTTP {status}")

    user_code = payload.get("user_code") or payload.get("usercode")
    device_auth_id = payload.get("device_auth_id")
    if not user_code or not device_auth_id:
        raise OAuthError("OpenAI device authorization response did not include a user code.")

    return DeviceCode(
        device_auth_id=str(device_auth_id),
        user_code=str(user_code),
        interval=int(payload.get("interval") or 5),
    )


async def _poll_device_code(device_code: DeviceCode) -> dict[str, str]:
    deadline = time.monotonic() + 15 * 60
    while time.monotonic() < deadline:
        await asyncio.sleep(max(device_code.interval, 1))
        async with (
            new_client_session() as session,
            session.post(
                f"{OPENAI_AUTH_ISSUER}/api/accounts/deviceauth/token",
                json={
                    "device_auth_id": device_code.device_auth_id,
                    "user_code": device_code.user_code,
                },
            ) as response,
        ):
            payload = await response.json(content_type=None)
            status = response.status

        if status == 200:
            authorization_code = payload.get("authorization_code")
            code_verifier = payload.get("code_verifier")
            if not authorization_code or not code_verifier:
                raise OAuthError("OpenAI device token response was incomplete.")
            return {
                "authorization_code": str(authorization_code),
                "code_verifier": str(code_verifier),
            }
        if status in {403, 404}:
            continue
        raise OAuthError(f"Failed to poll OpenAI device code: HTTP {status}")

    raise OAuthError("Timed out waiting for OpenAI device authorization.")


async def _exchange_code_for_tokens(
    authorization_code: str, code_verifier: str, redirect_uri: str
) -> dict[str, Any]:
    async with (
        new_client_session() as session,
        session.post(
            f"{OPENAI_AUTH_ISSUER}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": OPENAI_CLIENT_ID,
                "code": authorization_code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
        ) as response,
    ):
        payload = await response.json(content_type=None)
        status = response.status

    if status != 200:
        raise OAuthError(f"Failed to exchange OpenAI authorization code: HTTP {status}")
    return payload


async def _exchange_id_token_for_api_key(id_token: str) -> str:
    async with (
        new_client_session() as session,
        session.post(
            f"{OPENAI_AUTH_ISSUER}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": OPENAI_CLIENT_ID,
                "subject_token": id_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                "requested_token": "openai-api-key",
            },
        ) as response,
    ):
        payload = await response.json(content_type=None)
        status = response.status

    if status != 200:
        return ""
    return str(payload.get("access_token") or "")


async def refresh_openai_chatgpt_token(refresh_token: str) -> OAuthToken:
    async with (
        new_client_session() as session,
        session.post(
            f"{OPENAI_AUTH_ISSUER}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": OPENAI_CLIENT_ID,
                "refresh_token": refresh_token,
            },
        ) as response,
    ):
        payload = await response.json(content_type=None)
        status = response.status

    if status != 200:
        error_description = str(payload.get("error_description") or "")
        if status in {401, 403}:
            raise OAuthUnauthorized(error_description or "OpenAI token refresh unauthorized.")
        raise OAuthError(error_description or f"OpenAI token refresh failed ({status}).")
    return _token_from_openai_response(payload)


async def _discover_chatgpt_models(access_token: str) -> list[ModelInfo]:
    platform = Platform(
        id=OPENAI_CHATGPT_PLATFORM_ID,
        name="OpenAI ChatGPT Codex",
        base_url=OPENAI_CHATGPT_BASE_URL,
        allowed_prefixes=None,
    )
    try:
        return await list_models(platform, access_token)
    except aiohttp.ClientResponseError as exc:
        if exc.status in {401, 403}:
            raise
        return list(OPENAI_CHATGPT_FALLBACK_MODELS)
    except Exception:
        return list(OPENAI_CHATGPT_FALLBACK_MODELS)


def _token_from_openai_response(payload: dict[str, Any]) -> OAuthToken:
    normalized = {
        "token_type": "Bearer",
        "scope": "openid profile email offline_access",
        "expires_in": 3600,
        **payload,
    }
    # ChatGPT does not return `account_id` as a top-level OAuth response field;
    # it lives inside the id_token JWT claims under
    # `https://api.openai.com/auth.chatgpt_account_id`. Hoist it onto the
    # response so OAuthToken.from_response() picks it up. Without this the
    # ChatGPT usage adapter (and any other code calling
    # OAuthManager.get_chatgpt_account_id) sees None.
    if (
        "account_id" not in normalized
        and (id_token := payload.get("id_token"))
        and (account_id := _extract_chatgpt_account_id(str(id_token)))
    ):
        normalized["account_id"] = account_id
    return OAuthToken.from_response(normalized)


def _extract_chatgpt_account_id(id_token: str) -> str | None:
    """Decode the id_token JWT (without verifying the signature) and pull the
    ChatGPT account id out of the `https://api.openai.com/auth` claim. We do
    not verify the signature here because the token was just received over TLS
    from the OpenAI auth server in response to our PKCE/refresh exchange.
    """
    parts = id_token.split(".")
    if len(parts) < 2:
        return None
    try:
        # JWT segments are base64url without padding; pad before decoding.
        segment = parts[1]
        padded = segment + "=" * (-len(segment) % 4)
        claims_bytes = base64.urlsafe_b64decode(padded.encode("utf-8"))
    except (ValueError, binascii.Error):
        return None
    try:
        claims = json.loads(claims_bytes)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    claims_dict = cast(dict[str, Any], claims)
    auth_claim = claims_dict.get("https://api.openai.com/auth")
    if not isinstance(auth_claim, dict):
        return None
    auth_dict = cast(dict[str, Any], auth_claim)
    account_id = auth_dict.get("chatgpt_account_id")
    return str(account_id) if account_id else None


async def _finish_chatgpt_login(
    config: Config, token_payload: dict[str, Any]
) -> AsyncIterator[OAuthEvent]:
    token = _token_from_openai_response(token_payload)
    oauth_ref = save_tokens(OAuthRef(storage="file", key=OPENAI_CHATGPT_OAUTH_KEY), token)

    try:
        api_key = ""
        if id_token := token_payload.get("id_token"):
            api_key = await _exchange_id_token_for_api_key(str(id_token))
        models = await _discover_chatgpt_models(token.access_token)
        selected_model, thinking = _select_default_openai_model(models)
    except Exception as exc:
        yield OAuthEvent("error", f"Failed to discover OpenAI ChatGPT models: {exc}")
        return

    _apply_openai_config(
        config,
        platform_id=OPENAI_CHATGPT_PLATFORM_ID,
        provider_type="openai_codex",
        base_url=OPENAI_CHATGPT_BASE_URL,
        api_key=SecretStr(api_key),
        oauth_ref=oauth_ref,
        models=models,
        selected_model=selected_model,
        thinking=thinking,
    )
    save_config(config)
    yield OAuthEvent("success", f"OpenAI ChatGPT configured with model {selected_model.id}.")


async def login_openai_browser(
    config: Config, open_browser: bool = True
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    yield OAuthEvent(
        "verification_url",
        "Opening OpenAI ChatGPT login in your browser.",
    )

    try:
        code, verifier, redirect_uri = await _wait_for_browser_code(open_browser=open_browser)
        token_payload = await _exchange_code_for_tokens(code, verifier, redirect_uri)
    except Exception as exc:
        yield OAuthEvent("error", f"OpenAI browser login failed: {exc}")
        return

    async for event in _finish_chatgpt_login(config, token_payload):
        yield event


async def login_openai_headless(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    try:
        device_code = await _request_device_code()
    except Exception as exc:
        yield OAuthEvent("error", f"Failed to start OpenAI device login: {exc}")
        return

    yield OAuthEvent(
        "verification_url",
        f"Open {OPENAI_DEVICE_VERIFICATION_URL} and enter code {device_code.user_code}.",
        data={
            "verification_url": OPENAI_DEVICE_VERIFICATION_URL,
            "user_code": device_code.user_code,
        },
    )
    yield OAuthEvent("waiting", "Waiting for OpenAI device authorization...")

    try:
        code_payload = await _poll_device_code(device_code)
        token_payload = await _exchange_code_for_tokens(
            code_payload["authorization_code"],
            code_payload["code_verifier"],
            OPENAI_DEVICE_REDIRECT_URI,
        )
    except Exception as exc:
        yield OAuthEvent("error", f"OpenAI device login failed: {exc}")
        return

    async for event in _finish_chatgpt_login(config, token_payload):
        yield event


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
        models = list(OPENAI_API_FALLBACK_MODELS)
    except Exception:
        models = list(OPENAI_API_FALLBACK_MODELS)

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
            if model.provider != provider_key:
                continue
            del config.models[key]
            if config.default_model == key:
                removed_default = True

    if removed_default or config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of OpenAI successfully.")
