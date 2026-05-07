from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import OLLAMA_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.auth.platforms import LOCAL_API_KEY_PLACEHOLDER, bearer_headers
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_PROVIDER_KEY = "managed:ollama"
OLLAMA_DEFAULT_CONTEXT_SIZE = 32768

_EMBEDDING_FAMILIES = frozenset({"bert", "nomic-bert", "mxbai-embed", "all-minilm"})


@dataclass(frozen=True, slots=True)
class OllamaModel:
    model_id: str
    display_name: str
    max_context_size: int = OLLAMA_DEFAULT_CONTEXT_SIZE
    provider_key: str = OLLAMA_PROVIDER_KEY

    @property
    def alias(self) -> str:
        return f"{OLLAMA_PLATFORM_ID}/{self.model_id}"


def get_ollama_api_key_from_env() -> str | None:
    value = os.getenv("OLLAMA_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def get_ollama_base_url_from_env() -> str | None:
    value = os.getenv("OLLAMA_BASE_URL")
    if value and value.strip():
        return value.strip()
    return None


def _root_url(base_url: str) -> str:
    """Strip trailing /v1 (or /v1/) so we can hit /api/* on the same host."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed[: -len("/v1")]
    return trimmed


def _parse_tags_payload(payload: object) -> tuple[OllamaModel, ...]:
    if not isinstance(payload, dict):
        return ()
    payload = cast(dict[str, Any], payload)
    raw_items = payload.get("models")
    if not isinstance(raw_items, list):
        return ()

    result: list[OllamaModel] = []
    for item in cast(list[Any], raw_items):
        if not isinstance(item, dict):
            continue
        item = cast(dict[str, Any], item)
        name = item.get("name")
        if not isinstance(name, str):
            continue

        details_raw = item.get("details")
        if isinstance(details_raw, dict):
            details = cast(dict[str, Any], details_raw)
            family = details.get("family", "")
            if isinstance(family, str) and family.lower() in _EMBEDDING_FAMILIES:
                continue
            parameter_size = details.get("parameter_size", "")
            quantization_level = details.get("quantization_level", "")
        else:
            parameter_size = ""
            quantization_level = ""

        if (
            isinstance(parameter_size, str)
            and parameter_size
            and isinstance(quantization_level, str)
            and quantization_level
        ):
            display_name = f"{name} — {parameter_size} {quantization_level}"
        else:
            display_name = name

        result.append(
            OllamaModel(
                model_id=name,
                display_name=display_name,
                max_context_size=OLLAMA_DEFAULT_CONTEXT_SIZE,
            )
        )
    return tuple(result)


async def _enrich_with_show(
    session: aiohttp.ClientSession,
    *,
    root: str,
    headers: dict[str, str],
    model: OllamaModel,
    timeout: aiohttp.ClientTimeout,
) -> OllamaModel:
    try:
        async with session.post(
            f"{root}/api/show",
            json={"name": model.model_id},
            headers=headers,
            timeout=timeout,
            raise_for_status=True,
        ) as response:
            payload: object = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError):
        return model

    if not isinstance(payload, dict):
        return model

    payload = cast(dict[str, Any], payload)
    model_info = payload.get("model_info")
    if not isinstance(model_info, dict):
        return model

    for key, value in cast(dict[str, Any], model_info).items():
        if key.endswith(".context_length") and isinstance(value, int) and value > 0:
            return OllamaModel(
                model_id=model.model_id,
                display_name=model.display_name,
                max_context_size=value,
                provider_key=model.provider_key,
            )

    return model


async def _discover_ollama_models(
    base_url: str,
    api_key: str,
) -> tuple[OllamaModel, ...]:
    headers = bearer_headers(api_key)
    root = _root_url(base_url)
    timeout = aiohttp.ClientTimeout(total=5)

    async with new_client_session() as session:
        async with session.get(
            f"{root}/api/tags",
            headers=headers,
            timeout=timeout,
            raise_for_status=True,
        ) as response:
            payload = await response.json(content_type=None)

        base_models = _parse_tags_payload(payload)
        if not base_models:
            return ()

        enriched = await asyncio.gather(
            *(
                _enrich_with_show(session, root=root, headers=headers, model=m, timeout=timeout)
                for m in base_models
            ),
            return_exceptions=False,
        )
    return tuple(enriched)


def _apply_ollama_config(
    config: Config,
    api_key: SecretStr,
    *,
    base_url: str,
    models: tuple[OllamaModel, ...],
) -> None:
    config.providers[OLLAMA_PROVIDER_KEY] = LLMProvider(
        type="openai_legacy",
        base_url=base_url,
        api_key=api_key,
    )

    # Replace any prior Ollama aliases.
    for key, model in list(config.models.items()):
        if model.provider == OLLAMA_PROVIDER_KEY:
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


async def login_ollama(
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

    resolved_url = (base_url or get_ollama_base_url_from_env() or OLLAMA_BASE_URL).strip()
    if not resolved_url:
        yield OAuthEvent(
            "error",
            "Ollama base URL is empty; pass a non-empty --base-url or set OLLAMA_BASE_URL.",
        )
        return
    resolved_key = (api_key or get_ollama_api_key_from_env() or LOCAL_API_KEY_PLACEHOLDER).strip()

    try:
        models = await _discover_ollama_models(resolved_url, resolved_key)
    except aiohttp.ClientResponseError as exc:
        if exc.status in (401, 403):
            yield OAuthEvent("error", "Ollama rejected the API key; the key was not saved.")
            return
        yield OAuthEvent(
            "error",
            f"Ollama model listing failed ({exc.status}); the provider was not saved.",
        )
        return
    except (aiohttp.ClientError, TimeoutError, ConnectionError) as exc:
        try:
            detail = str(exc)
        except Exception:
            detail = type(exc).__name__
        yield OAuthEvent(
            "error",
            f"Ollama server is not reachable at {resolved_url}; start it and retry. ({detail})",
        )
        return

    if not models:
        yield OAuthEvent(
            "error",
            "Ollama has no chat models pulled; run `ollama pull <model>` and retry.",
        )
        return

    _apply_ollama_config(
        config,
        SecretStr(resolved_key),
        base_url=resolved_url,
        models=models,
    )
    save_config(config)
    yield OAuthEvent(
        "success",
        f"Ollama configured at {resolved_url} with {len(models)} model(s); "
        f"default = {config.default_model}.",
    )


async def logout_ollama(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    config.providers.pop(OLLAMA_PROVIDER_KEY, None)
    for key, model in list(config.models.items()):
        if model.provider == OLLAMA_PROVIDER_KEY:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of Ollama successfully.")
