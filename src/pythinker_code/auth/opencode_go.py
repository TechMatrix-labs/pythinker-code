from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import OPENCODE_GO_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session

OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
OPENCODE_GO_OPENAI_PROVIDER_KEY = "managed:opencode-go-openai"
OPENCODE_GO_ANTHROPIC_PROVIDER_KEY = "managed:opencode-go-anthropic"
OPENCODE_GO_DEFAULT_MODEL_ALIAS = "opencode-go/kimi-k2.6"


@dataclass(frozen=True, slots=True)
class OpenCodeGoModel:
    model_id: str
    display_name: str
    provider_key: str
    max_context_size: int = 262_000

    @property
    def alias(self) -> str:
        return f"{OPENCODE_GO_PLATFORM_ID}/{self.model_id}"


OPENCODE_GO_MODELS: tuple[OpenCodeGoModel, ...] = (
    OpenCodeGoModel("glm-5", "GLM-5", OPENCODE_GO_OPENAI_PROVIDER_KEY),
    OpenCodeGoModel("glm-5.1", "GLM-5.1", OPENCODE_GO_OPENAI_PROVIDER_KEY),
    OpenCodeGoModel("kimi-k2.5", "Kimi K2.5", OPENCODE_GO_OPENAI_PROVIDER_KEY),
    OpenCodeGoModel("kimi-k2.6", "Kimi K2.6", OPENCODE_GO_OPENAI_PROVIDER_KEY),
    OpenCodeGoModel("deepseek-v4-pro", "DeepSeek V4 Pro", OPENCODE_GO_OPENAI_PROVIDER_KEY),
    OpenCodeGoModel("deepseek-v4-flash", "DeepSeek V4 Flash", OPENCODE_GO_OPENAI_PROVIDER_KEY),
    OpenCodeGoModel("mimo-v2-pro", "MiMo-V2-Pro", OPENCODE_GO_OPENAI_PROVIDER_KEY),
    OpenCodeGoModel("mimo-v2-omni", "MiMo-V2-Omni", OPENCODE_GO_OPENAI_PROVIDER_KEY),
    OpenCodeGoModel("mimo-v2.5-pro", "MiMo-V2.5-Pro", OPENCODE_GO_OPENAI_PROVIDER_KEY, 1_000_000),
    OpenCodeGoModel("mimo-v2.5", "MiMo-V2.5", OPENCODE_GO_OPENAI_PROVIDER_KEY, 1_000_000),
    OpenCodeGoModel("qwen3.5-plus", "Qwen3.5 Plus", OPENCODE_GO_OPENAI_PROVIDER_KEY, 262_000),
    OpenCodeGoModel("qwen3.6-plus", "Qwen3.6 Plus", OPENCODE_GO_OPENAI_PROVIDER_KEY, 262_000),
    OpenCodeGoModel("minimax-m2.5", "MiniMax M2.5", OPENCODE_GO_ANTHROPIC_PROVIDER_KEY, 205_000),
    OpenCodeGoModel("minimax-m2.7", "MiniMax M2.7", OPENCODE_GO_ANTHROPIC_PROVIDER_KEY, 205_000),
)


def get_opencode_go_api_key_from_env() -> str | None:
    for name in ("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY", "OPENCODE_ZEN_API_KEY"):
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _apply_opencode_go_config(
    config: Config,
    api_key: SecretStr,
    models: tuple[OpenCodeGoModel, ...] = OPENCODE_GO_MODELS,
) -> None:
    config.providers[OPENCODE_GO_OPENAI_PROVIDER_KEY] = LLMProvider(
        type="openai_legacy",
        base_url=OPENCODE_GO_BASE_URL,
        api_key=api_key,
    )
    config.providers[OPENCODE_GO_ANTHROPIC_PROVIDER_KEY] = LLMProvider(
        type="anthropic",
        base_url=OPENCODE_GO_BASE_URL,
        api_key=api_key,
    )

    provider_keys = {OPENCODE_GO_OPENAI_PROVIDER_KEY, OPENCODE_GO_ANTHROPIC_PROVIDER_KEY}
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

    if OPENCODE_GO_DEFAULT_MODEL_ALIAS in config.models:
        config.default_model = OPENCODE_GO_DEFAULT_MODEL_ALIAS
    else:
        fallback = next((model.alias for model in models), next(iter(config.models), ""))
        config.default_model = fallback
    config.default_thinking = False


def _model_by_id() -> dict[str, OpenCodeGoModel]:
    return {model.model_id: model for model in OPENCODE_GO_MODELS}


def _parse_discovered_models(data: object) -> tuple[OpenCodeGoModel, ...]:
    if not isinstance(data, dict):
        return ()
    payload = cast(dict[str, Any], data)
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return ()

    known = _model_by_id()
    result: list[OpenCodeGoModel] = []
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
        display_name = str(display_name_raw) if display_name_raw else current.display_name
        result.append(
            OpenCodeGoModel(
                current.model_id,
                display_name,
                current.provider_key,
                max_context_size,
            )
        )
    return tuple(result)


async def _discover_opencode_go_models(api_key: str) -> tuple[OpenCodeGoModel, ...]:
    async with (
        new_client_session() as session,
        session.get(
            f"{OPENCODE_GO_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            raise_for_status=True,
        ) as response,
    ):
        payload = await response.json(content_type=None)
    return _parse_discovered_models(payload)


async def login_opencode_go_api_key(
    config: Config, api_key: str | None = None
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    resolved_key = (api_key or get_opencode_go_api_key_from_env() or "").strip()
    if not resolved_key:
        yield OAuthEvent("error", "OpenCode Go API key is required.")
        return

    models = OPENCODE_GO_MODELS
    try:
        discovered = await _discover_opencode_go_models(resolved_key)
        if discovered:
            models = discovered
    except aiohttp.ClientResponseError as exc:
        if exc.status in {401, 403}:
            yield OAuthEvent("error", "Invalid OpenCode Go API key; the key was not saved.")
            return
        yield OAuthEvent(
            "info",
            "OpenCode Go model listing is unavailable; using the built-in model list.",
        )
    except (TimeoutError, aiohttp.ClientError, ValueError):
        yield OAuthEvent(
            "info",
            "OpenCode Go model listing is unavailable; using the built-in model list.",
        )

    _apply_opencode_go_config(config, SecretStr(resolved_key), models=models)
    save_config(config)
    yield OAuthEvent("success", f"OpenCode Go configured with model {config.default_model}.")


async def logout_opencode_go(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    provider_keys = {OPENCODE_GO_OPENAI_PROVIDER_KEY, OPENCODE_GO_ANTHROPIC_PROVIDER_KEY}
    for provider_key in provider_keys:
        config.providers.pop(provider_key, None)
    for key, model in list(config.models.items()):
        if model.provider in provider_keys:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of OpenCode Go successfully.")
