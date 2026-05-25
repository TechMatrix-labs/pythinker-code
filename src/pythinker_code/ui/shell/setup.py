from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import aiohttp
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
from pydantic import SecretStr

from pythinker_code.auth import PYTHINKER_CODE_PLATFORM_ID
from pythinker_code.auth.platforms import (
    PLATFORMS,
    ModelInfo,
    Platform,
    get_platform_by_name,
    list_models,
    managed_model_key,
    managed_provider_key,
)
from pythinker_code.config import (
    LLMModel,
    LLMProvider,
    PythinkerAIFetchConfig,
    PythinkerAISearchConfig,
    load_config,
    save_config,
)
from pythinker_code.ui.shell.console import console
from pythinker_code.ui.shell.slash import registry
from pythinker_code.ui.theme import get_tui_tokens as _get_tui_tokens
from pythinker_code.utils.logging import logger

if TYPE_CHECKING:
    from pythinker_code.ui.shell import Shell


async def select_platform() -> Platform | None:
    platform_name = await _prompt_choice(
        header="Select a platform (↑↓ navigate, Enter select, Ctrl+C cancel):",
        choices=[platform.name for platform in PLATFORMS],
    )
    _t = _get_tui_tokens()
    if not platform_name:
        console.print(f"[{_t.error}]No platform selected[/]")
        return None

    platform = get_platform_by_name(platform_name)
    if platform is None:
        console.print(f"[{_t.error}]Unknown platform[/]")
        return None
    return platform


async def setup_platform(platform: Platform) -> bool:
    result = await _setup_platform(platform)
    if not result:
        # error message already printed
        return False

    _apply_setup_result(result)
    _t = _get_tui_tokens()
    thinking_label = "on" if result.thinking else "off"
    console.print(f"[{_t.success}]✓ Setup complete![/]")
    console.print(f"  Platform: [bold]{result.platform.name}[/bold]")
    console.print(f"  Model:    [bold]{result.selected_model.id}[/bold]")
    console.print(f"  Thinking: [bold]{thinking_label}[/bold]")
    console.print("  Reloading...")
    return True


class _SetupResult(NamedTuple):
    platform: Platform
    api_key: SecretStr
    selected_model: ModelInfo
    models: list[ModelInfo]
    thinking: bool


async def _setup_platform(platform: Platform) -> _SetupResult | None:
    # enter the API key
    api_key = await _prompt_text("Enter your API key", is_password=True)
    if not api_key:
        return None

    # list models
    _t = _get_tui_tokens()
    try:
        with console.status(f"[{_t.info}]Verifying API key...[/]"):
            models = await list_models(platform, api_key)
    except aiohttp.ClientResponseError as e:
        logger.error("Failed to get models: {error}", error=e)
        console.print(f"[{_t.error}]Failed to get models: {e.message}[/]")
        if e.status == 401 and platform.id != PYTHINKER_CODE_PLATFORM_ID:
            console.print(
                f"[{_t.warning}]Hint: If your API key was obtained from Pythinker, "
                'please select "Pythinker" instead.[/]'
            )
        return None
    except Exception as e:
        logger.error("Failed to get models: {error}", error=e)
        console.print(f"[{_t.error}]Failed to get models: {e}[/]")
        return None

    # select the model
    if not models:
        console.print(f"[{_t.error}]No models available for the selected platform[/]")
        return None

    model_map = {model.id: model for model in models}
    model_id = await _prompt_choice(
        header="Select a model (↑↓ navigate, Enter select, Ctrl+C cancel):",
        choices=list(model_map),
    )
    if not model_id:
        console.print(f"[{_t.error}]No model selected[/]")
        return None

    selected_model = model_map[model_id]

    # Determine thinking mode based on model capabilities
    capabilities = selected_model.capabilities
    thinking: bool

    if "always_thinking" in capabilities:
        thinking = True
    elif "thinking" in capabilities:
        thinking_selection = await _prompt_choice(
            header="Enable thinking mode? (↑↓ navigate, Enter select, Ctrl+C cancel):",
            choices=["on", "off"],
        )
        if not thinking_selection:
            return None
        thinking = thinking_selection == "on"
    else:
        thinking = False

    return _SetupResult(
        platform=platform,
        api_key=SecretStr(api_key),
        selected_model=selected_model,
        models=models,
        thinking=thinking,
    )


def _apply_setup_result(result: _SetupResult) -> None:
    config = load_config()
    provider_key = managed_provider_key(result.platform.id)
    model_key = managed_model_key(result.platform.id, result.selected_model.id)
    config.providers[provider_key] = LLMProvider(
        type="pythinker",
        base_url=result.platform.base_url,
        api_key=result.api_key,
    )
    for key, model in list(config.models.items()):
        if model.provider == provider_key:
            del config.models[key]
    for model_info in result.models:
        capabilities = model_info.capabilities or None
        config.models[managed_model_key(result.platform.id, model_info.id)] = LLMModel(
            provider=provider_key,
            model=model_info.id,
            max_context_size=model_info.context_length,
            capabilities=capabilities,
        )
    config.default_model = model_key
    config.default_thinking = result.thinking

    if result.platform.search_url:
        config.services.pythinker_ai_search = PythinkerAISearchConfig(
            base_url=result.platform.search_url,
            api_key=result.api_key,
        )

    if result.platform.fetch_url:
        config.services.pythinker_ai_fetch = PythinkerAIFetchConfig(
            base_url=result.platform.fetch_url,
            api_key=result.api_key,
        )

    save_config(config)


async def _prompt_choice(*, header: str, choices: list[str]) -> str | None:
    if not choices:
        return None

    try:
        return await ChoiceInput(
            message=header,
            options=[(choice, choice) for choice in choices],
            default=choices[0],
        ).prompt_async()
    except (EOFError, KeyboardInterrupt):
        return None


async def _prompt_text(prompt: str, *, is_password: bool = False) -> str | None:
    session = PromptSession[str]()
    try:
        return str(
            await session.prompt_async(
                f" {prompt}: ",
                is_password=is_password,
            )
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None


@registry.command
def reload(app: Shell, args: str):
    """Reload configuration"""
    from pythinker_code.cli import Reload

    raise Reload
