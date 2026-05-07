from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import LM_STUDIO_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.auth.platforms import LOCAL_API_KEY_PLACEHOLDER, bearer_headers
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
LM_STUDIO_PROVIDER_KEY = "managed:lm-studio"
LM_STUDIO_DEFAULT_CONTEXT_SIZE = 32768
# The agent's system prompt + tool schemas + skills already runs ~16k tokens
# before any user input. Anything below this on the LM Studio side will fail
# on the first chat with `n_keep:N >= n_ctx:M`.
LM_STUDIO_MIN_RECOMMENDED_LOADED_CONTEXT = 32768


@dataclass(frozen=True, slots=True)
class LMStudioModel:
    model_id: str
    display_name: str
    max_context_size: int = LM_STUDIO_DEFAULT_CONTEXT_SIZE
    provider_key: str = LM_STUDIO_PROVIDER_KEY
    # Native v0 metadata used for the smart context-length warning. Both are 0
    # when discovery falls back to OpenAI-compat /v1/models.
    state: str = ""  # "loaded" | "not-loaded" | ""
    max_context_length: int = 0  # the model's hard ceiling
    loaded_context_length: int = 0  # what LM Studio actually loaded the model with

    @property
    def alias(self) -> str:
        return f"{LM_STUDIO_PLATFORM_ID}/{self.model_id}"


def get_lm_studio_api_key_from_env() -> str | None:
    value = os.getenv("LM_STUDIO_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def get_lm_studio_base_url_from_env() -> str | None:
    value = os.getenv("LM_STUDIO_BASE_URL")
    if value and value.strip():
        return value.strip()
    return None


def _root_url(base_url: str) -> str:
    """Strip trailing /v1 (or /v1/) so we can hit /api/v0/* on the same host."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed[: -len("/v1")]
    return trimmed


async def _discover_lm_studio_models(
    base_url: str,
    api_key: str,
) -> tuple[LMStudioModel, ...]:
    """Prefer the native v0 endpoint (richer metadata); fall back to /v1/models."""
    headers = bearer_headers(api_key)
    root = _root_url(base_url)
    timeout = aiohttp.ClientTimeout(total=5)

    async with new_client_session() as session:
        # Path A: native enrichment.
        try:
            async with session.get(
                f"{root}/api/v0/models",
                headers=headers,
                timeout=timeout,
                raise_for_status=True,
            ) as response:
                payload = await response.json(content_type=None)
            return _parse_native_lm_studio_models(payload)
        except (aiohttp.ClientResponseError, aiohttp.ClientError, TimeoutError):
            pass

        # Path B: OpenAI-compat fallback.
        async with session.get(
            f"{base_url.rstrip('/')}/models",
            headers=headers,
            timeout=timeout,
            raise_for_status=True,
        ) as response:
            payload = await response.json(content_type=None)
        return _parse_openai_compat_models(payload)


def _parse_native_lm_studio_models(payload: object) -> tuple[LMStudioModel, ...]:
    if not isinstance(payload, dict):
        return ()
    payload = cast(dict[str, Any], payload)
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return ()

    result: list[LMStudioModel] = []
    for item in cast(list[dict[str, Any]], raw_items):
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        if item.get("type") not in (None, "llm", "vlm"):
            # Skip embedding models; they are not chat-capable.
            continue
        max_ctx_raw = item.get("max_context_length")
        max_ctx = max_ctx_raw if isinstance(max_ctx_raw, int) and max_ctx_raw > 0 else 0
        loaded_ctx_raw = item.get("loaded_context_length")
        loaded_ctx = loaded_ctx_raw if isinstance(loaded_ctx_raw, int) and loaded_ctx_raw > 0 else 0
        state_raw = item.get("state")
        state = state_raw if isinstance(state_raw, str) else ""
        # Effective max_context_size for the agent:
        #   - if loaded → the actual loaded ceiling (what the model can really handle now)
        #   - if not-loaded → the model's max (will be capped by JIT-load default)
        if state == "loaded" and loaded_ctx > 0:
            effective_ctx = loaded_ctx
        elif max_ctx > 0:
            effective_ctx = max_ctx
        else:
            effective_ctx = LM_STUDIO_DEFAULT_CONTEXT_SIZE
        arch = item.get("arch") if isinstance(item.get("arch"), str) else None
        quant = item.get("quantization") if isinstance(item.get("quantization"), str) else None
        display = (
            " ".join(part for part in (arch, f"({quant})" if quant else None) if part) or model_id
        )
        result.append(
            LMStudioModel(
                model_id=model_id,
                display_name=display,
                max_context_size=effective_ctx,
                state=state,
                max_context_length=max_ctx,
                loaded_context_length=loaded_ctx,
            )
        )
    return tuple(result)


def _parse_openai_compat_models(payload: object) -> tuple[LMStudioModel, ...]:
    if not isinstance(payload, dict):
        return ()
    payload = cast(dict[str, Any], payload)
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return ()
    result: list[LMStudioModel] = []
    for item in cast(list[dict[str, Any]], raw_items):
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        result.append(
            LMStudioModel(
                model_id=model_id,
                display_name=model_id,
                max_context_size=LM_STUDIO_DEFAULT_CONTEXT_SIZE,
            )
        )
    return tuple(result)


def _apply_lm_studio_config(
    config: Config,
    api_key: SecretStr,
    *,
    base_url: str,
    models: tuple[LMStudioModel, ...],
) -> None:
    config.providers[LM_STUDIO_PROVIDER_KEY] = LLMProvider(
        type="openai_legacy",
        base_url=base_url,
        api_key=api_key,
    )

    # Replace any prior LM Studio aliases.
    for key, model in list(config.models.items()):
        if model.provider == LM_STUDIO_PROVIDER_KEY:
            del config.models[key]

    for model in models:
        config.models[model.alias] = LLMModel(
            provider=model.provider_key,
            model=model.model_id,
            max_context_size=model.max_context_size,
            display_name=model.display_name,
        )

    if not models:
        return

    # Pick the model with the largest context, ties broken alphabetically (first wins).
    best = min(models, key=lambda m: (-m.max_context_size, m.alias))
    config.default_model = best.alias


@dataclass(frozen=True, slots=True)
class LMStudioLoadResult:
    model_id: str
    status: str
    load_time_seconds: float
    instance_id: str | None = None


async def _is_lm_studio_model_loaded(
    session: aiohttp.ClientSession,
    *,
    root: str,
    headers: dict[str, str],
    model_id: str,
    timeout: aiohttp.ClientTimeout,
) -> bool:
    """Check `state` on /api/v0/models; True if the model is already loaded."""
    try:
        async with session.get(
            f"{root}/api/v0/models",
            headers=headers,
            timeout=timeout,
            raise_for_status=True,
        ) as response:
            payload: object = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError):
        return False

    if not isinstance(payload, dict):
        return False
    payload = cast(dict[str, Any], payload)
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return False
    for item in cast(list[dict[str, Any]], raw_items):
        if item.get("id") == model_id and item.get("state") == "loaded":
            return True
    return False


async def request_lm_studio_load(
    *,
    base_url: str,
    model_id: str,
    api_key: str,
    timeout_s: float = 180.0,
) -> LMStudioLoadResult:
    """Ask LM Studio to load a model.

    Checks /api/v0/models first; if the model is already `state=loaded`,
    returns immediately without a redundant /api/v1/models/load call (which
    would otherwise spawn an additional instance).

    Long timeout because cold-loading a large model can take a while.

    Raises aiohttp.ClientError on transport failure. On HTTP errors from the
    load endpoint (e.g., VRAM exhaustion), reads the JSON error body and
    raises RuntimeError with the actual message instead of a bare status code.
    """
    headers = bearer_headers(api_key)
    root = _root_url(base_url)
    timeout = aiohttp.ClientTimeout(total=timeout_s)

    async with new_client_session() as session:
        if await _is_lm_studio_model_loaded(
            session, root=root, headers=headers, model_id=model_id, timeout=timeout
        ):
            return LMStudioLoadResult(
                model_id=model_id, status="already-loaded", load_time_seconds=0.0
            )

        async with session.post(
            f"{root}/api/v1/models/load",
            json={"model": model_id},
            headers=headers,
            timeout=timeout,
        ) as response:
            payload: object = await response.json(content_type=None)
            if response.status >= 400:
                msg = ""
                if isinstance(payload, dict):
                    payload_dict = cast(dict[str, Any], payload)
                    err = payload_dict.get("error")
                    if isinstance(err, dict):
                        err = cast(dict[str, Any], err)
                        msg = str(err.get("message") or err.get("type") or "")
                raise RuntimeError(
                    f"LM Studio refused to load {model_id} "
                    f"(HTTP {response.status}): {msg or 'no message'}"
                )

    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected /api/v1/models/load response: {payload!r}")
    payload = cast(dict[str, Any], payload)
    return LMStudioLoadResult(
        model_id=model_id,
        status=str(payload.get("status") or ""),
        load_time_seconds=float(payload.get("load_time_seconds") or 0.0),
        instance_id=(
            str(payload["instance_id"]) if isinstance(payload.get("instance_id"), str) else None
        ),
    )


async def login_lm_studio(
    config: Config,
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    resolved_url = (base_url or get_lm_studio_base_url_from_env() or LM_STUDIO_BASE_URL).strip()
    if not resolved_url:
        yield OAuthEvent(
            "error",
            "LM Studio base URL is empty; pass a non-empty --base-url or set LM_STUDIO_BASE_URL.",
        )
        return
    resolved_key = (
        api_key or get_lm_studio_api_key_from_env() or LOCAL_API_KEY_PLACEHOLDER
    ).strip()

    try:
        models = await _discover_lm_studio_models(resolved_url, resolved_key)
    except aiohttp.ClientResponseError as exc:
        if exc.status in (401, 403):
            yield OAuthEvent("error", "LM Studio rejected the API key; the key was not saved.")
            return
        yield OAuthEvent(
            "error",
            f"LM Studio model listing failed ({exc.status}); the provider was not saved.",
        )
        return
    except (aiohttp.ClientError, TimeoutError, ConnectionError) as exc:
        try:
            detail = str(exc)
        except Exception:
            detail = type(exc).__name__
        yield OAuthEvent(
            "error",
            f"LM Studio server is not reachable at {resolved_url}; start it and retry. ({detail})",
        )
        return

    if not models:
        yield OAuthEvent(
            "error",
            "LM Studio reported zero loaded chat models; "
            "load a model in the LM Studio UI and retry.",
        )
        return

    _apply_lm_studio_config(
        config,
        SecretStr(resolved_key),
        base_url=resolved_url,
        models=models,
    )
    save_config(config)
    yield OAuthEvent(
        "success",
        f"LM Studio configured at {resolved_url} with {len(models)} model(s); "
        f"default = {config.default_model}.",
    )

    # Smart context-length check: any currently-loaded model whose actual
    # `loaded_context_length` is below what the agent's system prompt needs
    # will fail on first chat. Emit an info event with a concrete fix path
    # so the user discovers this BEFORE they hit the cryptic n_keep/n_ctx
    # error.
    for m in models:
        if (
            m.state == "loaded"
            and 0 < m.loaded_context_length < LM_STUDIO_MIN_RECOMMENDED_LOADED_CONTEXT
        ):
            recommended = min(
                m.max_context_length or LM_STUDIO_MIN_RECOMMENDED_LOADED_CONTEXT,
                131072,
            )
            yield OAuthEvent(
                "info",
                (
                    f"⚠ {m.model_id} is loaded with only {m.loaded_context_length} "
                    f"tokens of context, but the agent's system prompt needs "
                    f"≥{LM_STUDIO_MIN_RECOMMENDED_LOADED_CONTEXT}. Chats will fail "
                    "on the first message. "
                    "In LM Studio: open the model → gear icon → Context Length → "
                    f"set to {recommended} (model max is "
                    f"{m.max_context_length or 'unknown'}) → reload the model."
                ),
            )


async def logout_lm_studio(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    config.providers.pop(LM_STUDIO_PROVIDER_KEY, None)
    for key, model in list(config.models.items()):
        if model.provider == LM_STUDIO_PROVIDER_KEY:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of LM Studio successfully.")
