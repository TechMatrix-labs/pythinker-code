from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import OPENROUTER_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_PROVIDER_KEY = "managed:openrouter"
OPENROUTER_DEFAULT_MODEL_ALIAS = "openrouter/openai/gpt-5.2"


@dataclass(frozen=True, slots=True)
class OpenRouterModel:
    model_id: str  # upstream OpenRouter slug, e.g. "openai/gpt-5.2"
    display_name: str
    provider_key: str = OPENROUTER_PROVIDER_KEY
    max_context_size: int = 128_000

    @property
    def alias(self) -> str:
        return f"{OPENROUTER_PLATFORM_ID}/{self.model_id}"


OPENROUTER_MODELS: tuple[OpenRouterModel, ...] = (
    OpenRouterModel("openai/gpt-5.2", "GPT-5.2 (OpenRouter)", max_context_size=400_000),
    OpenRouterModel(
        "anthropic/claude-sonnet-4.6",
        "Claude Sonnet 4.6 (OpenRouter)",
        max_context_size=200_000,
    ),
    OpenRouterModel(
        "anthropic/claude-opus-4.7",
        "Claude Opus 4.7 (OpenRouter)",
        max_context_size=1_000_000,
    ),
    OpenRouterModel(
        "deepseek/deepseek-v4-pro",
        "DeepSeek V4 Pro (OpenRouter)",
        max_context_size=128_000,
    ),
    OpenRouterModel(
        "google/gemini-2.5-pro",
        "Gemini 2.5 Pro (OpenRouter)",
        max_context_size=1_000_000,
    ),
    OpenRouterModel(
        "openrouter/auto",
        "OpenRouter Auto (router)",
        max_context_size=1_000_000,
    ),
)


def get_openrouter_api_key_from_env() -> str | None:
    value = os.getenv("OPENROUTER_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def _apply_openrouter_config(
    config: Config,
    api_key: SecretStr,
    models: tuple[OpenRouterModel, ...] = OPENROUTER_MODELS,
) -> None:
    config.providers[OPENROUTER_PROVIDER_KEY] = LLMProvider(
        type="openai_legacy",
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
    )

    provider_keys = {OPENROUTER_PROVIDER_KEY}
    for key, model in list(config.models.items()):
        if model.provider in provider_keys:
            del config.models[key]

    for model in models:
        config.models[model.alias] = LLMModel(
            provider=model.provider_key,
            model=model.model_id,
            max_context_size=model.max_context_size,
            display_name=model.display_name,
        )

    fallback = next(
        (m.alias for m in models),
        next(iter(config.models), ""),
    )
    if OPENROUTER_DEFAULT_MODEL_ALIAS in config.models:
        config.default_model = OPENROUTER_DEFAULT_MODEL_ALIAS
    else:
        config.default_model = fallback
    config.default_thinking = False


def _model_by_id() -> dict[str, OpenRouterModel]:
    return {model.model_id: model for model in OPENROUTER_MODELS}


def _parse_discovered_models(data: object) -> tuple[OpenRouterModel, ...]:
    """Override-only parser: returns models for curated slugs found in the
    discovered payload, with metadata overrides applied. Unknown slugs are dropped."""
    if not isinstance(data, dict):
        return ()
    data = cast(dict[str, Any], data)
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        return ()

    known = _model_by_id()
    result: list[OpenRouterModel] = []
    for item in cast(list[dict[str, Any]], raw_items):
        model_id = item.get("id")
        if not isinstance(model_id, str) or model_id not in known:
            continue
        current = known[model_id]
        context_length = item.get("context_length")
        max_context_size = current.max_context_size
        if isinstance(context_length, int) and context_length > 0:
            max_context_size = context_length
        # OpenRouter's listing uses "name" rather than "display_name".
        display_name_raw = item.get("name") or item.get("display_name")
        display_name = (
            display_name_raw
            if isinstance(display_name_raw, str) and display_name_raw
            else current.display_name
        )
        result.append(
            OpenRouterModel(
                model_id=current.model_id,
                display_name=display_name,
                provider_key=current.provider_key,
                max_context_size=max_context_size,
            )
        )
    return tuple(result)


async def _discover_openrouter_models(api_key: str) -> tuple[OpenRouterModel, ...]:
    async with (
        new_client_session() as session,
        session.get(
            f"{OPENROUTER_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            raise_for_status=True,
        ) as response,
    ):
        payload = await response.json(content_type=None)
    return _parse_discovered_models(payload)


def _merge_overrides_into_static_catalog(
    discovered: tuple[OpenRouterModel, ...],
) -> tuple[OpenRouterModel, ...]:
    """Apply discovered metadata overrides on top of the static catalog.
    Models not present in the discovered set keep their static defaults."""
    overrides = {m.model_id: m for m in discovered}
    return tuple(overrides.get(m.model_id, m) for m in OPENROUTER_MODELS)


async def login_openrouter_api_key(
    config: Config, api_key: str | None = None
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    resolved_key = (api_key or get_openrouter_api_key_from_env() or "").strip()
    if not resolved_key:
        yield OAuthEvent("error", "OpenRouter API key is required.")
        return

    models = OPENROUTER_MODELS
    try:
        discovered = await _discover_openrouter_models(resolved_key)
        models = _merge_overrides_into_static_catalog(discovered)
    except aiohttp.ClientResponseError as exc:
        if exc.status in {401, 403}:
            yield OAuthEvent("error", "Invalid OpenRouter API key; the key was not saved.")
            return
        yield OAuthEvent(
            "info",
            "OpenRouter model listing is unavailable; using the built-in model list.",
        )
    except (aiohttp.ClientError, TimeoutError, ValueError):
        yield OAuthEvent(
            "info",
            "OpenRouter model listing is unavailable; using the built-in model list.",
        )

    _apply_openrouter_config(config, SecretStr(resolved_key), models=models)
    save_config(config)
    yield OAuthEvent("success", f"OpenRouter configured with model {config.default_model}.")


async def logout_openrouter(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    provider_keys = {OPENROUTER_PROVIDER_KEY}
    config.providers.pop(OPENROUTER_PROVIDER_KEY, None)
    for key, model in list(config.models.items()):
        if model.provider in provider_keys:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of OpenRouter successfully.")
