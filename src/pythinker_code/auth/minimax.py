from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import MINIMAX_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session

MINIMAX_ANTHROPIC_BASE_URL = "https://api.minimax.io/anthropic"
MINIMAX_OPENAI_BASE_URL = "https://api.minimax.io/v1"
MINIMAX_ANTHROPIC_PROVIDER_KEY = "managed:minimax-anthropic"
MINIMAX_DEFAULT_MODEL_ALIAS = "minimax/m2.7"
MINIMAX_TOKEN_PLAN_KEY_PREFIX = "sk-cp-"


@dataclass(frozen=True, slots=True)
class MiniMaxModel:
    model_id: str
    alias_suffix: str
    display_name: str
    provider_key: str = MINIMAX_ANTHROPIC_PROVIDER_KEY
    max_context_size: int = 192_000

    @property
    def alias(self) -> str:
        return f"{MINIMAX_PLATFORM_ID}/{self.alias_suffix}"


MINIMAX_MODELS: tuple[MiniMaxModel, ...] = (
    MiniMaxModel("MiniMax-M2.7", "m2.7", "MiniMax M2.7"),
    MiniMaxModel("MiniMax-M2.7-highspeed", "m2.7-highspeed", "MiniMax M2.7 High-Speed"),
    MiniMaxModel("MiniMax-M2.5", "m2.5", "MiniMax M2.5"),
    MiniMaxModel("MiniMax-M2.5-highspeed", "m2.5-highspeed", "MiniMax M2.5 High-Speed"),
)


def get_minimax_api_key_from_env() -> str | None:
    value = os.getenv("MINIMAX_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def _apply_minimax_config(
    config: Config,
    api_key: SecretStr,
    models: tuple[MiniMaxModel, ...] = MINIMAX_MODELS,
) -> None:
    config.providers[MINIMAX_ANTHROPIC_PROVIDER_KEY] = LLMProvider(
        type="anthropic",
        base_url=MINIMAX_ANTHROPIC_BASE_URL,
        api_key=api_key,
    )

    provider_keys = {MINIMAX_ANTHROPIC_PROVIDER_KEY}
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
    if MINIMAX_DEFAULT_MODEL_ALIAS in config.models:
        config.default_model = MINIMAX_DEFAULT_MODEL_ALIAS
    else:
        config.default_model = fallback
    config.default_thinking = False


def _model_by_id() -> dict[str, MiniMaxModel]:
    return {model.model_id: model for model in MINIMAX_MODELS}


def _parse_discovered_models(data: object) -> tuple[MiniMaxModel, ...]:
    if not isinstance(data, dict):
        return ()
    data = cast(dict[str, Any], data)
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        return ()

    known = _model_by_id()
    result: list[MiniMaxModel] = []
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
            MiniMaxModel(
                model_id=current.model_id,
                alias_suffix=current.alias_suffix,
                display_name=display_name,
                provider_key=current.provider_key,
                max_context_size=max_context_size,
            )
        )
    return tuple(result)


async def _discover_minimax_models(api_key: str) -> tuple[MiniMaxModel, ...]:
    async with (
        new_client_session() as session,
        session.get(
            f"{MINIMAX_OPENAI_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            raise_for_status=True,
        ) as response,
    ):
        payload = await response.json(content_type=None)
    return _parse_discovered_models(payload)


async def login_minimax_api_key(
    config: Config, api_key: str | None = None
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    resolved_key = (api_key or get_minimax_api_key_from_env() or "").strip()
    if not resolved_key:
        yield OAuthEvent("error", "MiniMax API key is required.")
        return

    if resolved_key.startswith(MINIMAX_TOKEN_PLAN_KEY_PREFIX):
        yield OAuthEvent(
            "info",
            "MiniMax Token Plan key detected; requests are quota-metered "
            "(5-hour rolling window for text), not per-token billed.",
        )

    models = MINIMAX_MODELS
    try:
        discovered = await _discover_minimax_models(resolved_key)
        if discovered:
            models = discovered
    except aiohttp.ClientResponseError as exc:
        if exc.status in {401, 403}:
            yield OAuthEvent("error", "Invalid MiniMax API key; the key was not saved.")
            return
        yield OAuthEvent(
            "info",
            "MiniMax model listing is unavailable; using the built-in model list.",
        )
    except (aiohttp.ClientError, TimeoutError, ValueError):
        yield OAuthEvent(
            "info",
            "MiniMax model listing is unavailable; using the built-in model list.",
        )

    _apply_minimax_config(config, SecretStr(resolved_key), models=models)
    save_config(config)
    yield OAuthEvent("success", f"MiniMax configured with model {config.default_model}.")


async def logout_minimax(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    provider_keys = {MINIMAX_ANTHROPIC_PROVIDER_KEY}
    config.providers.pop(MINIMAX_ANTHROPIC_PROVIDER_KEY, None)
    for key, model in list(config.models.items()):
        if model.provider in provider_keys:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of MiniMax successfully.")
