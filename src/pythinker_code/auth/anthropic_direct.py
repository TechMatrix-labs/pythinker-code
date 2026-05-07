from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import ANTHROPIC_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_DISCOVERY_URL = "https://api.anthropic.com/v1/models"
ANTHROPIC_VERSION_HEADER = "2023-06-01"
ANTHROPIC_PROVIDER_KEY = "managed:anthropic"
ANTHROPIC_DEFAULT_MODEL_ALIAS = "anthropic/claude-opus-4-7"


@dataclass(frozen=True, slots=True)
class AnthropicModel:
    model_id: str
    alias_suffix: str
    display_name: str
    provider_key: str = ANTHROPIC_PROVIDER_KEY
    max_context_size: int = 200_000

    @property
    def alias(self) -> str:
        return f"{ANTHROPIC_PLATFORM_ID}/{self.alias_suffix}"


ANTHROPIC_MODELS: tuple[AnthropicModel, ...] = (
    AnthropicModel(
        "claude-opus-4-7",
        "claude-opus-4-7",
        "Claude Opus 4.7",
        max_context_size=1_000_000,
    ),
    AnthropicModel("claude-sonnet-4-6", "claude-sonnet-4-6", "Claude Sonnet 4.6"),
    AnthropicModel(
        "claude-haiku-4-5-20251001",
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
    ),
)


def get_anthropic_api_key_from_env() -> str | None:
    value = os.getenv("ANTHROPIC_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def _apply_anthropic_config(
    config: Config,
    api_key: SecretStr,
    models: tuple[AnthropicModel, ...] = ANTHROPIC_MODELS,
) -> None:
    config.providers[ANTHROPIC_PROVIDER_KEY] = LLMProvider(
        type="anthropic",
        base_url=ANTHROPIC_BASE_URL,
        api_key=api_key,
    )

    provider_keys = {ANTHROPIC_PROVIDER_KEY}
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
    if ANTHROPIC_DEFAULT_MODEL_ALIAS in config.models:
        config.default_model = ANTHROPIC_DEFAULT_MODEL_ALIAS
    else:
        config.default_model = fallback
    config.default_thinking = False


def _model_by_id() -> dict[str, AnthropicModel]:
    return {model.model_id: model for model in ANTHROPIC_MODELS}


def _parse_discovered_models(data: object) -> tuple[AnthropicModel, ...]:
    if not isinstance(data, dict):
        return ()
    data = cast(dict[str, Any], data)
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        return ()

    known = _model_by_id()
    result: list[AnthropicModel] = []
    for item in cast(list[dict[str, Any]], raw_items):
        model_id = item.get("id")
        if not isinstance(model_id, str) or model_id not in known:
            continue
        current = known[model_id]
        context_length = item.get("context_length")
        max_context_size = current.max_context_size
        if isinstance(context_length, int) and context_length > 0:
            max_context_size = context_length
        display_name_raw = item.get("display_name")
        display_name = (
            display_name_raw
            if isinstance(display_name_raw, str) and display_name_raw
            else current.display_name
        )
        result.append(
            AnthropicModel(
                model_id=current.model_id,
                alias_suffix=current.alias_suffix,
                display_name=display_name,
                provider_key=current.provider_key,
                max_context_size=max_context_size,
            )
        )
    return tuple(result)


async def _discover_anthropic_models(api_key: str) -> tuple[AnthropicModel, ...]:
    async with (
        new_client_session() as session,
        session.get(
            ANTHROPIC_DISCOVERY_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION_HEADER,
            },
            raise_for_status=True,
        ) as response,
    ):
        payload = await response.json(content_type=None)
    return _parse_discovered_models(payload)


async def login_anthropic_api_key(
    config: Config, api_key: str | None = None
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    resolved_key = (api_key or get_anthropic_api_key_from_env() or "").strip()
    if not resolved_key:
        yield OAuthEvent("error", "Anthropic API key is required.")
        return

    models = ANTHROPIC_MODELS
    try:
        discovered = await _discover_anthropic_models(resolved_key)
        if discovered:
            models = discovered
    except aiohttp.ClientResponseError as exc:
        if exc.status in {401, 403}:
            yield OAuthEvent("error", "Invalid Anthropic API key; the key was not saved.")
            return
        yield OAuthEvent(
            "info",
            "Anthropic model listing is unavailable; using the built-in model list.",
        )
    except (aiohttp.ClientError, TimeoutError, ValueError):
        yield OAuthEvent(
            "info",
            "Anthropic model listing is unavailable; using the built-in model list.",
        )

    _apply_anthropic_config(config, SecretStr(resolved_key), models=models)
    save_config(config)
    yield OAuthEvent("success", f"Anthropic configured with model {config.default_model}.")


async def logout_anthropic(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    provider_keys = {ANTHROPIC_PROVIDER_KEY}
    config.providers.pop(ANTHROPIC_PROVIDER_KEY, None)
    for key, model in list(config.models.items()):
        if model.provider in provider_keys:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of Anthropic successfully.")
