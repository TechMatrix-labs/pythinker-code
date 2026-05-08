from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from rich.status import Status

from pythinker_code.auth import (
    ANTHROPIC_PLATFORM_ID,
    DEEPSEEK_PLATFORM_ID,
    LM_STUDIO_PLATFORM_ID,
    MINIMAX_PLATFORM_ID,
    OLLAMA_PLATFORM_ID,
    OPENCODE_GO_PLATFORM_ID,
    OPENROUTER_PLATFORM_ID,
)
from pythinker_code.auth.anthropic_direct import (
    login_anthropic_api_key,
    logout_anthropic,
)
from pythinker_code.auth.deepseek import (
    login_deepseek_api_key,
    logout_deepseek,
)
from pythinker_code.auth.lm_studio import (
    login_lm_studio,
    logout_lm_studio,
)
from pythinker_code.auth.minimax import (
    login_minimax_api_key,
    logout_minimax,
)
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.auth.ollama import (
    login_ollama,
    logout_ollama,
)
from pythinker_code.auth.openai import (
    login_openai_api_key,
    login_openai_browser,
    login_openai_headless,
    logout_openai,
)
from pythinker_code.auth.opencode_go import (
    login_opencode_go_api_key,
    logout_opencode_go,
)
from pythinker_code.auth.openrouter import (
    login_openrouter_api_key,
    logout_openrouter,
)
from pythinker_code.cli import Reload
from pythinker_code.ui.shell.console import console
from pythinker_code.ui.shell.selectors.oauth import (
    OAuthProviderEntry,
    OAuthProviderStatus,
    run_oauth_selector,
)
from pythinker_code.ui.shell.slash import ensure_pythinker_soul, registry

if TYPE_CHECKING:
    from pythinker_code.soul.pythinkersoul import PythinkerSoul
    from pythinker_code.ui.shell import Shell


async def _render_oauth_events(events: AsyncIterator[OAuthEvent]) -> bool:
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
    finally:
        if status is not None:
            status.stop()
    return ok


async def _prompt_api_key(label: str) -> str | None:
    session = PromptSession[str]()
    try:
        value = await session.prompt_async(f" {label} API key: ", is_password=True)
    except (EOFError, KeyboardInterrupt):
        return None
    return value.strip() or None


_SELECTOR_PROVIDER_ENTRIES: list[OAuthProviderEntry] = [
    OAuthProviderEntry(id="browser", name="OpenAI ChatGPT (browser)", auth_type="oauth"),
    OAuthProviderEntry(id="headless", name="OpenAI ChatGPT (device code)", auth_type="oauth"),
    OAuthProviderEntry(id="api-key", name="OpenAI API key", auth_type="api_key"),
    OAuthProviderEntry(id="opencode-go", name="OpenCode Go", auth_type="api_key"),
    OAuthProviderEntry(id="minimax", name="MiniMax", auth_type="api_key"),
    OAuthProviderEntry(id="deepseek", name="DeepSeek", auth_type="api_key"),
    OAuthProviderEntry(id="anthropic", name="Anthropic", auth_type="api_key"),
    OAuthProviderEntry(id="openrouter", name="OpenRouter", auth_type="api_key"),
    OAuthProviderEntry(id="lm-studio", name="LM Studio", auth_type="api_key"),
    OAuthProviderEntry(id="ollama", name="Ollama", auth_type="api_key"),
]


def _get_provider_status(provider_id: str) -> OAuthProviderStatus:
    return OAuthProviderStatus(source="unconfigured")


def current_model_key(soul: PythinkerSoul) -> str | None:
    config = soul.runtime.config
    curr_model_cfg = soul.runtime.llm.model_config if soul.runtime.llm else None
    if curr_model_cfg is not None:
        for name, model_cfg in config.models.items():
            if model_cfg == curr_model_cfg:
                return name
    return config.default_model or None


@registry.command(aliases=["setup"])
async def login(app: Shell, args: str) -> None:
    """Login with OpenAI, OpenCode Go, MiniMax, DeepSeek, Anthropic, or local providers."""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    mode = args.strip().lower()
    if mode == "":
        chosen = await run_oauth_selector(
            _SELECTOR_PROVIDER_ENTRIES,
            _get_provider_status,
            action="login",
        )
        if chosen is None:
            return
        mode = chosen

    if mode == "browser":
        ok = await _render_oauth_events(login_openai_browser(soul.runtime.config))
        provider = "openai-chatgpt"
    elif mode in ("headless", "device", "device-code"):
        ok = await _render_oauth_events(login_openai_headless(soul.runtime.config))
        provider = "openai-chatgpt"
    elif mode in ("api-key", "apikey", "api"):
        api_key = await _prompt_api_key("OpenAI")
        if not api_key:
            console.print("[red]No OpenAI API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_openai_api_key(soul.runtime.config, api_key))
        provider = "openai"
    elif mode in ("opencode-go", "opencode", "go"):
        api_key = await _prompt_api_key("OpenCode Go")
        if not api_key:
            console.print("[red]No OpenCode Go API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_opencode_go_api_key(soul.runtime.config, api_key))
        provider = OPENCODE_GO_PLATFORM_ID
    elif mode == "minimax":
        api_key = await _prompt_api_key("MiniMax")
        if not api_key:
            console.print("[red]No MiniMax API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_minimax_api_key(soul.runtime.config, api_key))
        provider = MINIMAX_PLATFORM_ID
    elif mode == "deepseek":
        api_key = await _prompt_api_key("DeepSeek")
        if not api_key:
            console.print("[red]No DeepSeek API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_deepseek_api_key(soul.runtime.config, api_key))
        provider = DEEPSEEK_PLATFORM_ID
    elif mode == "anthropic":
        api_key = await _prompt_api_key("Anthropic")
        if not api_key:
            console.print("[red]No Anthropic API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_anthropic_api_key(soul.runtime.config, api_key))
        provider = ANTHROPIC_PLATFORM_ID
    elif mode == "openrouter":
        api_key = await _prompt_api_key("OpenRouter")
        if not api_key:
            console.print("[red]No OpenRouter API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_openrouter_api_key(soul.runtime.config, api_key))
        provider = OPENROUTER_PLATFORM_ID
    elif mode in ("lm-studio", "lmstudio"):
        ok = await _render_oauth_events(login_lm_studio(soul.runtime.config))
        provider = LM_STUDIO_PLATFORM_ID
    elif mode == "ollama":
        ok = await _render_oauth_events(login_ollama(soul.runtime.config))
        provider = OLLAMA_PLATFORM_ID
    else:
        console.print(
            "[red]Usage: /login "
            "[browser|headless|api-key|opencode-go|minimax|deepseek|anthropic|openrouter|"
            "lm-studio|ollama][/red]"
        )
        return
    if not ok:
        return
    from pythinker_code.telemetry import track

    track("login", provider=provider)
    await asyncio.sleep(1)
    console.clear()
    raise Reload


@registry.command
async def logout(app: Shell, args: str) -> None:
    """Logout from OpenAI, OpenCode Go, MiniMax, DeepSeek, Anthropic, or local providers."""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    config = soul.runtime.config
    if not config.is_from_default_location:
        console.print(
            "[red]Logout requires the default config file; "
            "restart without --config/--config-file.[/red]"
        )
        return
    mode = args.strip().lower()
    if mode == "openrouter":
        ok = await _render_oauth_events(logout_openrouter(config))
    elif mode == "anthropic":
        ok = await _render_oauth_events(logout_anthropic(config))
    elif mode == "deepseek":
        ok = await _render_oauth_events(logout_deepseek(config))
    elif mode == "minimax":
        ok = await _render_oauth_events(logout_minimax(config))
    elif mode in ("opencode-go", "opencode", "go"):
        ok = await _render_oauth_events(logout_opencode_go(config))
    elif mode in ("lm-studio", "lmstudio"):
        ok = await _render_oauth_events(logout_lm_studio(config))
    elif mode == "ollama":
        ok = await _render_oauth_events(logout_ollama(config))
    elif mode == "":
        ok = await _render_oauth_events(logout_openai(config))
    else:
        console.print(
            "[red]Usage: /logout "
            "[opencode-go|minimax|deepseek|anthropic|openrouter|lm-studio|ollama][/red]"
        )
        return
    if not ok:
        return

    from pythinker_code.telemetry import track

    track("logout")
    await asyncio.sleep(1)
    console.clear()
    raise Reload
