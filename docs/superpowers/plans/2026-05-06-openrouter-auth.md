# OpenRouter Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated OpenRouter setup/logout path and configure six curated popular models (OpenAI, Anthropic, DeepSeek, Google, OpenRouter Auto) routed through OpenRouter's unified API.

**Architecture:** Add a focused `pythinker_code.auth.openrouter` module that owns OpenRouter constants, model metadata, env-key resolution, best-effort model discovery (override-only — does not add new aliases), login events, and logout events. Reuse the existing `openai_legacy` provider type at `https://openrouter.ai/api/v1` (single managed provider). Wire the module into existing `pythinker login`, `/login`, `pythinker logout`, and `/logout` routing without changing any current behavior. Append `OpenRouter` to the `/login` shell chooser.

**Tech Stack:** Python 3.12+, Typer, pytest, pytest-asyncio, pydantic `SecretStr`, aiohttp, existing `OAuthEvent`, `Config`, `LLMProvider`, `LLMModel`, `save_config`, `_prompt_api_key`, and `_LOGIN_PROVIDER_OPTIONS`.

---

## File Structure

- Create: `src/pythinker_code/auth/openrouter.py`
- Modify: `src/pythinker_code/auth/__init__.py` — exports `OPENROUTER_PLATFORM_ID`.
- Modify: `src/pythinker_code/cli/__init__.py` — adds `--openrouter` flags.
- Modify: `src/pythinker_code/ui/shell/oauth.py` — adds `/login openrouter` / `/logout openrouter`; appends `OpenRouter` to `_LOGIN_PROVIDER_OPTIONS`.
- Create: `tests/auth/test_openrouter_auth.py`
- Modify: `tests/cli/test_openai_login_cli.py`
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`

## Task 1: Add OpenRouter Constants And Config Helpers

**Files:**
- Create: `src/pythinker_code/auth/openrouter.py`
- Modify: `src/pythinker_code/auth/__init__.py`
- Test: `tests/auth/test_openrouter_auth.py`

- [ ] **Step 1: Write failing tests**

Create `tests/auth/test_openrouter_auth.py`:

```python
from __future__ import annotations

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.config import Config


def test_openrouter_model_catalog_contains_six_curated_models():
    from pythinker_code.auth.openrouter import OPENROUTER_MODELS

    aliases = {model.alias for model in OPENROUTER_MODELS}
    assert aliases == {
        "openrouter/openai/gpt-5.2",
        "openrouter/anthropic/claude-sonnet-4.6",
        "openrouter/anthropic/claude-opus-4.7",
        "openrouter/deepseek/deepseek-v4-pro",
        "openrouter/google/gemini-2.5-pro",
        "openrouter/openrouter/auto",
    }

    # Each alias model_id must be the upstream OpenRouter slug (no `openrouter/` prefix).
    for m in OPENROUTER_MODELS:
        assert "/" in m.model_id  # vendor/model format
        assert not m.model_id.startswith("openrouter/") or m.model_id == "openrouter/auto"

    assert all(m.provider_key == "managed:openrouter" for m in OPENROUTER_MODELS)


def test_openrouter_env_key_uses_openrouter_api_key(monkeypatch):
    from pythinker_code.auth.openrouter import get_openrouter_api_key_from_env

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert get_openrouter_api_key_from_env() is None

    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-or-test  ")
    assert get_openrouter_api_key_from_env() == "sk-or-test"

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert get_openrouter_api_key_from_env() is None


def test_apply_openrouter_config_writes_provider_and_default():
    from pythinker_code.auth.openrouter import (
        OPENROUTER_BASE_URL,
        OPENROUTER_PROVIDER_KEY,
        _apply_openrouter_config,
    )

    config = Config(is_from_default_location=True)

    _apply_openrouter_config(config, SecretStr("sk-or-test"))

    assert set(config.providers) == {OPENROUTER_PROVIDER_KEY}
    provider = config.providers[OPENROUTER_PROVIDER_KEY]
    assert provider.type == "openai_legacy"
    assert provider.base_url == OPENROUTER_BASE_URL
    assert provider.api_key.get_secret_value() == "sk-or-test"
    # Six curated models, all assigned to the OpenRouter provider key.
    assert len([m for m in config.models.values() if m.provider == OPENROUTER_PROVIDER_KEY]) == 6
    assert config.models["openrouter/openai/gpt-5.2"].model == "openai/gpt-5.2"
    assert config.default_model == "openrouter/openai/gpt-5.2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_openrouter_auth.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'pythinker_code.auth.openrouter'`.

- [ ] **Step 3: Export the platform ID**

Modify `src/pythinker_code/auth/__init__.py`. Add `OPENROUTER_PLATFORM_ID`:

```python
PYTHINKER_CODE_PLATFORM_ID = "pythinker-code"
OPENAI_API_PLATFORM_ID = "openai"
OPENAI_CHATGPT_PLATFORM_ID = "openai-chatgpt"
OPENCODE_GO_PLATFORM_ID = "opencode-go"
MINIMAX_PLATFORM_ID = "minimax"
DEEPSEEK_PLATFORM_ID = "deepseek"
ANTHROPIC_PLATFORM_ID = "anthropic"
OPENROUTER_PLATFORM_ID = "openrouter"

__all__ = [
    "ANTHROPIC_PLATFORM_ID",
    "DEEPSEEK_PLATFORM_ID",
    "MINIMAX_PLATFORM_ID",
    "OPENAI_API_PLATFORM_ID",
    "OPENAI_CHATGPT_PLATFORM_ID",
    "OPENCODE_GO_PLATFORM_ID",
    "OPENROUTER_PLATFORM_ID",
    "PYTHINKER_CODE_PLATFORM_ID",
]
```

- [ ] **Step 4: Implement constants and config helper**

Create `src/pythinker_code/auth/openrouter.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import SecretStr

from pythinker_code.auth import OPENROUTER_PLATFORM_ID
from pythinker_code.config import Config, LLMModel, LLMProvider

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


# Strict pyright reports this as unused until Task 2 adds an in-module caller
# (`login_openrouter_api_key`); the suppression is removed at that point.
def _apply_openrouter_config(  # pyright: ignore[reportUnusedFunction]
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
```

- [ ] **Step 5: Run tests + pyright**

Run: `uv run pytest tests/auth/test_openrouter_auth.py -v`

Expected: PASS.

Run: `uv run pyright src/pythinker_code/auth/openrouter.py tests/auth/test_openrouter_auth.py`

Expected: 0/0/0.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/auth/__init__.py src/pythinker_code/auth/openrouter.py tests/auth/test_openrouter_auth.py
git commit -m "feat(auth): add openrouter config helpers"
```

## Task 2: Add Best-Effort Model Discovery (Override-Only) And Login Events

**Files:**
- Modify: `src/pythinker_code/auth/openrouter.py`
- Test: `tests/auth/test_openrouter_auth.py`

**Important:** Unlike MiniMax/DeepSeek/Anthropic which REPLACE the catalog with discovered models, OpenRouter discovery only OVERRIDES metadata (`max_context_size`, `display_name`) for the six curated catalog entries. Discovered slugs not in the curated list are dropped. The reason: OpenRouter exposes 500+ models — adding them all would flood `config.toml`.

- [ ] **Step 1: Add failing tests**

Append to `tests/auth/test_openrouter_auth.py`:

```python
def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


@pytest.mark.asyncio
async def test_login_openrouter_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import login_openrouter_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "sk-or-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr(
        "pythinker_code.auth.openrouter._discover_openrouter_models", fake_discover
    )

    events = [event async for event in login_openrouter_api_key(config, "sk-or-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "sk-or-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "openrouter/openai/gpt-5.2"
    assert "openrouter/anthropic/claude-opus-4.7" in config.models


@pytest.mark.asyncio
async def test_login_openrouter_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import login_openrouter_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://openrouter.ai/api/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr(
        "pythinker_code.auth.openrouter._discover_openrouter_models", fake_discover
    )

    events = [event async for event in login_openrouter_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid OpenRouter API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_openrouter_uses_discovered_metadata_for_curated_only(
    monkeypatch, tmp_path
):
    from pythinker_code.auth.openrouter import login_openrouter_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    # Discovery returns an extended metadata for one curated slug AND an extra
    # uncurated slug. The extra slug must NOT be added to the config.
    async def fake_discover(api_key):
        from pythinker_code.auth.openrouter import OpenRouterModel

        return (
            OpenRouterModel(
                model_id="openai/gpt-5.2",
                display_name="OpenAI: GPT-5.2 (overridden)",
                max_context_size=512_000,
            ),
        )

    monkeypatch.setattr(
        "pythinker_code.auth.openrouter._discover_openrouter_models", fake_discover
    )

    events = [event async for event in login_openrouter_api_key(config, "sk-or-test")]

    assert events[-1].type == "success"
    # Override hit on the curated slug.
    assert config.models["openrouter/openai/gpt-5.2"].max_context_size == 512_000
    # Other curated entries still present at static defaults.
    assert "openrouter/anthropic/claude-opus-4.7" in config.models
    # Six curated, no more.
    openrouter_models = [
        m for m in config.models.values() if m.provider == "managed:openrouter"
    ]
    assert len(openrouter_models) == 6


@pytest.mark.asyncio
async def test_login_openrouter_requires_key(tmp_path):
    from pythinker_code.auth.openrouter import login_openrouter_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_openrouter_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "OpenRouter API key is required."


def test_parse_discovered_openrouter_models_drops_uncurated_and_keeps_curated_with_override():
    from pythinker_code.auth.openrouter import _parse_discovered_models

    payload = {
        "data": [
            {
                "id": "openai/gpt-5.2",
                "context_length": 700_000,
                "name": "OpenAI: GPT-5.2",
            },
            # Uncurated — must be dropped.
            {
                "id": "openai/gpt-3.5-turbo",
                "context_length": 16_385,
                "name": "OpenAI: GPT-3.5 Turbo",
            },
            # Malformed item — must be skipped.
            {"context_length": 999},
        ]
    }
    result = _parse_discovered_models(payload)
    aliases = {m.alias for m in result}
    assert aliases == {"openrouter/openai/gpt-5.2"}
    by_id = {m.model_id: m for m in result}
    assert by_id["openai/gpt-5.2"].max_context_size == 700_000


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"data": "not a list"}, {"data": [{"context_length": 1000}]}],
)
def test_parse_discovered_openrouter_models_handles_malformed_payloads(payload):
    from pythinker_code.auth.openrouter import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert result == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_openrouter_auth.py -v`

Expected: FAIL with `ImportError`/`AttributeError` for `login_openrouter_api_key`, `_discover_openrouter_models`, `_parse_discovered_models`.

- [ ] **Step 3: Implement discovery, parser, and login (and remove the pyright suppression)**

Add imports at the top of `src/pythinker_code/auth/openrouter.py`:

```python
from collections.abc import AsyncIterator
from typing import Any, cast

import aiohttp

from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import save_config
from pythinker_code.utils.aiohttp import new_client_session
```

Remove the `# Strict pyright reports this as unused...` comment block AND the `# pyright: ignore[reportUnusedFunction]` directive on `_apply_openrouter_config`.

Append below `_apply_openrouter_config`:

```python
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
```

- [ ] **Step 4: Run tests + pyright**

Run: `uv run pytest tests/auth/test_openrouter_auth.py -v`

Expected: ALL pass.

Run: `uv run pyright src/pythinker_code/auth/openrouter.py tests/auth/test_openrouter_auth.py`

Expected: 0/0/0.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/openrouter.py tests/auth/test_openrouter_auth.py
git commit -m "feat(auth): add openrouter login flow with override-only discovery"
```

## Task 3: Add OpenRouter Logout

**Files:**
- Modify: `src/pythinker_code/auth/openrouter.py`
- Test: `tests/auth/test_openrouter_auth.py`

- [ ] **Step 1: Add failing logout tests**

Append to `tests/auth/test_openrouter_auth.py`:

```python
@pytest.mark.asyncio
async def test_logout_openrouter_removes_only_openrouter(monkeypatch, tmp_path):
    from pythinker_code.auth.openrouter import (
        OPENROUTER_PROVIDER_KEY,
        _apply_openrouter_config,
        logout_openrouter,
    )
    from pythinker_code.config import LLMModel, LLMProvider

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)
    config.providers["managed:openai"] = LLMProvider(
        type="openai_responses",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("sk-test"),
    )
    config.models["openai/gpt-5.2"] = LLMModel(
        provider="managed:openai",
        model="gpt-5.2",
        max_context_size=400_000,
    )
    _apply_openrouter_config(config, SecretStr("sk-or-test"))

    events = [event async for event in logout_openrouter(config)]

    assert events[-1].type == "success"
    assert OPENROUTER_PROVIDER_KEY not in config.providers
    assert "openrouter/openai/gpt-5.2" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_openrouter_rejects_non_default_config_location():
    from pythinker_code.auth.openrouter import logout_openrouter

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_openrouter(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_openrouter_auth.py -v -k logout`

Expected: FAIL with `ImportError` for `logout_openrouter`.

- [ ] **Step 3: Implement logout**

Append to `src/pythinker_code/auth/openrouter.py`:

```python
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
```

- [ ] **Step 4: Run all tests + pyright**

Run: `uv run pytest tests/auth/test_openrouter_auth.py -v`

Expected: ALL pass.

Run: `uv run pyright src/pythinker_code/auth/openrouter.py tests/auth/test_openrouter_auth.py`

Expected: 0/0/0.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/openrouter.py tests/auth/test_openrouter_auth.py
git commit -m "feat(auth): add openrouter logout"
```

## Task 4: Wire CLI Login And Logout Flags

**Files:**
- Modify: `src/pythinker_code/cli/__init__.py`
- Modify: `tests/cli/test_openai_login_cli.py`

- [ ] **Step 1: Inspect existing CLI patterns**

Read the current `login` and `logout` Typer commands. Note the prior provider flags (assumed: opencode-go, minimax, deepseek, anthropic). The new `--openrouter` flag follows the same shape.

If any of the prior provider plans haven't landed yet, the references below to those flags must be omitted.

- [ ] **Step 2: Add failing CLI routing tests**

Append to `tests/cli/test_openai_login_cli.py`:

```python
def test_cli_login_openrouter_routes_to_openrouter(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.login_openrouter_api_key", login, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["login", "--openrouter"], input="sk-or-test\n")

    assert result.exit_code == 0
    assert login.call_args.args[1] == "sk-or-test"


def test_cli_login_rejects_openrouter_with_other_modes(monkeypatch):
    result = runner.invoke(cli, ["login", "--openrouter", "--api-key"])

    assert result.exit_code == 1
    assert "Choose only one" in result.output


def test_cli_logout_openrouter_routes_to_openrouter_logout(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.logout_openrouter", logout, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["logout", "--openrouter"])

    assert result.exit_code == 0
    assert logout.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -v -k openrouter`

Expected: FAIL because `--openrouter` does not exist.

- [ ] **Step 4: Import OpenRouter functions in CLI**

Add to `src/pythinker_code/cli/__init__.py`:

```python
from pythinker_code.auth.openrouter import login_openrouter_api_key, logout_openrouter
```

- [ ] **Step 5: Add `--openrouter` flag to `login` and route**

Add to the `login` command signature (placed after the `anthropic` flag):

```python
    openrouter: bool = typer.Option(
        False, "--openrouter", help="Configure OpenRouter with an API key."
    ),
```

Update the docstring to include OpenRouter and update the mode-conflict check to include the new flag (extend the boolean tuple and the error message).

Insert the OpenRouter branch BEFORE the existing `anthropic` branch:

```python
        if openrouter:
            key = typer.prompt("OpenRouter API key", hide_input=True).strip()
            events = login_openrouter_api_key(config, key)
        elif anthropic:
            ...
```

- [ ] **Step 6: Add `--openrouter` flag to `logout` and route**

Add the flag (placed after the `anthropic` flag):

```python
    openrouter: bool = typer.Option(False, "--openrouter", help="Logout from OpenRouter."),
```

Update the docstring and extend the mode-conflict check and `events` selection chain (insert OpenRouter branch first):

```python
        if openrouter:
            events = logout_openrouter(config)
        elif anthropic:
            events = logout_anthropic(config)
        elif deepseek:
            events = logout_deepseek(config)
        elif minimax:
            events = logout_minimax(config)
        elif opencode_go:
            events = logout_opencode_go(config)
        else:
            events = logout_openai(config)
```

- [ ] **Step 7: Run CLI tests + pyright**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -v`

Expected: PASS (all existing + 3 new).

Run: `uv run pyright src/pythinker_code/cli/__init__.py tests/cli/test_openai_login_cli.py`

Expected: 0/0/0.

- [ ] **Step 8: Commit**

```bash
git add src/pythinker_code/cli/__init__.py tests/cli/test_openai_login_cli.py
git commit -m "feat(cli): route openrouter auth commands"
```

## Task 5: Wire Shell Login And Logout Commands

**Files:**
- Modify: `src/pythinker_code/ui/shell/oauth.py`
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`

- [ ] **Step 1: Inspect existing shell patterns**

Read `src/pythinker_code/ui/shell/oauth.py`. `_prompt_api_key`, `_LOGIN_PROVIDER_OPTIONS`, and `_prompt_login_provider` already exist; reuse them.

- [ ] **Step 2: Add failing shell route tests**

Append to `tests/ui_and_conv/test_openai_shell_login.py`:

```python
@pytest.mark.asyncio
async def test_shell_login_openrouter_routes_to_openrouter(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "login_openrouter_api_key", login, raising=False)
    monkeypatch.setattr(
        shell_oauth, "_prompt_api_key", lambda label: _async_value("sk-or-test")
    )

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.login)(_app(), "openrouter")

    assert login.call_args.args[1] == "sk-or-test"


@pytest.mark.asyncio
async def test_shell_logout_openrouter_routes_to_openrouter(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "logout_openrouter", logout, raising=False)

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.logout)(_app(), "openrouter")

    assert logout.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v -k openrouter`

Expected: FAIL.

- [ ] **Step 4: Import OpenRouter functions and platform ID**

Modify `src/pythinker_code/ui/shell/oauth.py`. Update the existing `from pythinker_code.auth import ...` line to include `OPENROUTER_PLATFORM_ID`.

Add:

```python
from pythinker_code.auth.openrouter import (
    login_openrouter_api_key,
    logout_openrouter,
)
```

- [ ] **Step 5: Append OpenRouter to the chooser**

Add a new entry to `_LOGIN_PROVIDER_OPTIONS` (sequential number after the prior providers — 8 if DeepSeek and Anthropic already landed):

```python
    ("8", "openrouter", "OpenRouter"),
```

Update the prompt label in `_prompt_login_provider`:

```python
        choice = await session.prompt_async(" Enter [1-8] (default 1): ")
```

- [ ] **Step 6: Add `/login openrouter` route**

Insert a branch BEFORE the existing `anthropic` branch:

```python
    elif mode == "openrouter":
        api_key = await _prompt_api_key("OpenRouter")
        if not api_key:
            console.print("[red]No OpenRouter API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_openrouter_api_key(soul.runtime.config, api_key))
        provider = OPENROUTER_PLATFORM_ID
```

Update the unknown-mode usage error to include the new mode (append `|openrouter`).

- [ ] **Step 7: Add `/logout openrouter` route**

Modify `logout` to add a new branch before `anthropic`:

```python
    if mode == "openrouter":
        ok = await _render_oauth_events(logout_openrouter(config))
    elif mode == "anthropic":
        ...  # existing anthropic branch
```

Update the usage error: `Usage: /logout [opencode-go|minimax|deepseek|anthropic|openrouter]`.

- [ ] **Step 8: Update docstrings**

Append `, or OpenRouter` to both the login and logout docstrings.

- [ ] **Step 9: Run shell tests + pyright**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v`

Expected: PASS.

Run: `uv run pyright src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py`

Expected: 0/0/0.

- [ ] **Step 10: Commit**

```bash
git add src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py
git commit -m "feat(shell): route openrouter auth commands"
```

## Task 6: Final Quality Checks

**Files:**
- Verify all touched files; commit only if quality gates mutate files.

- [ ] **Step 1: Run formatting**

Run: `cd /home/ai/Projects/pythinker-code-main && make format`

Expected: exit 0.

- [ ] **Step 2: Run project checks**

Run: `cd /home/ai/Projects/pythinker-code-main && make check`

Expected: exit 0. Note any pre-existing non-blocking warnings in unrelated files.

- [ ] **Step 3: Run focused OpenRouter + integration test suite**

Run:

```bash
uv run pytest tests/auth/test_openrouter_auth.py \
  tests/cli/test_openai_login_cli.py \
  tests/ui_and_conv/test_openai_shell_login.py -v
```

Expected: ALL pass.

- [ ] **Step 4: Inspect end-to-end diff**

Run: `git diff --stat <pre-feature-SHA>..HEAD`. Expected: only the 7 files in "File Structure" plus this plan + spec doc.

Run: `git log --format='%H %s%n%b%n---' <pre-feature-SHA>..HEAD`. Expected: every commit body is empty (subject only). NO Co-Authored-By trailer. NO "Generated with Claude Code" footer.

- [ ] **Step 5: Final commit (only if Step 1 or Step 2 mutated files)**

If `make format` or `make check` modified any files:

```bash
git add <files-listed-by-status>
git commit -m "chore: finalize openrouter auth checks"
```

If nothing changed, do NOT create an empty commit.

## Self-Review Notes

- **Spec coverage:** The plan covers dedicated CLI/shell login, env-key resolution, single-provider config, six curated model aliases, override-only discovery, auth-failure handling, secret redaction, logout, chooser update, and tests with mocked network calls.
- **Scope control:** Excludes uncurated model auto-add, OpenRouter routing parameters (`provider.order`, `allow_fallbacks`), ranking headers (`HTTP-Referer`, `X-OpenRouter-Title`), and free-tier-only model handling.
- **Type consistency:** Provider key is `managed:openrouter` everywhere. Model alias format is `openrouter/<vendor>/<model>` where `<vendor>/<model>` is the verbatim OpenRouter slug. `OPENROUTER_PLATFORM_ID = "openrouter"`. `OAuthEvent` constructed positionally throughout. Override-only discovery uses a separate `_merge_overrides_into_static_catalog` helper to keep the static catalog as the source of truth.
- **Implementation risk:** Low. The wire format is OpenAI-compatible and Pythinker's `openai_legacy` provider type is already wired. The override-only discovery semantics introduce one new helper (`_merge_overrides_into_static_catalog`) but the parser shape mirrors prior plans.
