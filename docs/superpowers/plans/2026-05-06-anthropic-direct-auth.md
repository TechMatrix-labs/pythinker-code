# Anthropic Direct Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated Anthropic (direct API) setup/logout path and configure the three current Claude frontier models in Pythinker Code.

**Architecture:** Add a focused `pythinker_code.auth.anthropic_direct` module that owns Anthropic constants, model metadata, env-key resolution, best-effort model discovery (using `x-api-key` + `anthropic-version` headers), login events, and logout events. Reuse the existing `anthropic` provider type at `https://api.anthropic.com` (single managed provider). Wire the module into existing `pythinker login`, `/login`, `pythinker logout`, and `/logout` routing without changing any current behavior. Append `Anthropic` to the `/login` shell chooser.

**Tech Stack:** Python 3.12+, Typer, pytest, pytest-asyncio, pydantic `SecretStr`, aiohttp, existing `OAuthEvent`, `Config`, `LLMProvider`, `LLMModel`, `save_config`, `_prompt_api_key`, and `_LOGIN_PROVIDER_OPTIONS`.

---

## File Structure

- Create: `src/pythinker_code/auth/anthropic_direct.py`
- Modify: `src/pythinker_code/auth/__init__.py` — exports `ANTHROPIC_PLATFORM_ID`.
- Modify: `src/pythinker_code/cli/__init__.py` — adds `--anthropic` flags.
- Modify: `src/pythinker_code/ui/shell/oauth.py` — adds `/login anthropic` / `/logout anthropic`; appends `Anthropic` to `_LOGIN_PROVIDER_OPTIONS`.
- Create: `tests/auth/test_anthropic_direct_auth.py`
- Modify: `tests/cli/test_openai_login_cli.py`
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`

## Task 1: Add Anthropic Constants And Config Helpers

**Files:**
- Create: `src/pythinker_code/auth/anthropic_direct.py`
- Modify: `src/pythinker_code/auth/__init__.py`
- Test: `tests/auth/test_anthropic_direct_auth.py`

- [ ] **Step 1: Write failing tests**

Create `tests/auth/test_anthropic_direct_auth.py`:

```python
from __future__ import annotations

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.config import Config


def test_anthropic_model_catalog_contains_three_frontier_models():
    from pythinker_code.auth.anthropic_direct import ANTHROPIC_MODELS

    aliases = {model.alias for model in ANTHROPIC_MODELS}
    assert aliases == {
        "anthropic/claude-opus-4-7",
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-haiku-4-5",
    }

    api_ids = {m.alias: m.model_id for m in ANTHROPIC_MODELS}
    assert api_ids == {
        "anthropic/claude-opus-4-7": "claude-opus-4-7",
        "anthropic/claude-sonnet-4-6": "claude-sonnet-4-6",
        "anthropic/claude-haiku-4-5": "claude-haiku-4-5-20251001",
    }

    assert all(m.provider_key == "managed:anthropic" for m in ANTHROPIC_MODELS)


def test_anthropic_env_key_uses_anthropic_api_key(monkeypatch):
    from pythinker_code.auth.anthropic_direct import get_anthropic_api_key_from_env

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert get_anthropic_api_key_from_env() is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "  sk-ant-test  ")
    assert get_anthropic_api_key_from_env() == "sk-ant-test"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert get_anthropic_api_key_from_env() is None


def test_apply_anthropic_config_writes_provider_and_default():
    from pythinker_code.auth.anthropic_direct import (
        ANTHROPIC_BASE_URL,
        ANTHROPIC_PROVIDER_KEY,
        _apply_anthropic_config,
    )

    config = Config(is_from_default_location=True)

    _apply_anthropic_config(config, SecretStr("sk-ant-test"))

    assert set(config.providers) == {ANTHROPIC_PROVIDER_KEY}
    provider = config.providers[ANTHROPIC_PROVIDER_KEY]
    assert provider.type == "anthropic"
    assert provider.base_url == ANTHROPIC_BASE_URL
    assert provider.api_key.get_secret_value() == "sk-ant-test"
    assert config.models["anthropic/claude-opus-4-7"].provider == ANTHROPIC_PROVIDER_KEY
    assert config.models["anthropic/claude-opus-4-7"].model == "claude-opus-4-7"
    assert config.models["anthropic/claude-opus-4-7"].max_context_size == 1_000_000
    assert config.default_model == "anthropic/claude-opus-4-7"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_anthropic_direct_auth.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'pythinker_code.auth.anthropic_direct'`.

- [ ] **Step 3: Export the platform ID**

Modify `src/pythinker_code/auth/__init__.py`. Add `ANTHROPIC_PLATFORM_ID` to the existing exports:

```python
PYTHINKER_CODE_PLATFORM_ID = "pythinker-code"
OPENAI_API_PLATFORM_ID = "openai"
OPENAI_CHATGPT_PLATFORM_ID = "openai-chatgpt"
OPENCODE_GO_PLATFORM_ID = "opencode-go"
MINIMAX_PLATFORM_ID = "minimax"
DEEPSEEK_PLATFORM_ID = "deepseek"
ANTHROPIC_PLATFORM_ID = "anthropic"

__all__ = [
    "ANTHROPIC_PLATFORM_ID",
    "DEEPSEEK_PLATFORM_ID",
    "MINIMAX_PLATFORM_ID",
    "OPENAI_API_PLATFORM_ID",
    "OPENAI_CHATGPT_PLATFORM_ID",
    "OPENCODE_GO_PLATFORM_ID",
    "PYTHINKER_CODE_PLATFORM_ID",
]
```

- [ ] **Step 4: Implement constants and config helper**

Create `src/pythinker_code/auth/anthropic_direct.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import SecretStr

from pythinker_code.auth import ANTHROPIC_PLATFORM_ID
from pythinker_code.config import Config, LLMModel, LLMProvider

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


# Strict pyright reports this as unused until Task 2 adds an in-module caller
# (`login_anthropic_api_key`); the suppression is removed at that point.
def _apply_anthropic_config(  # pyright: ignore[reportUnusedFunction]
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
```

- [ ] **Step 5: Run tests + pyright**

Run: `uv run pytest tests/auth/test_anthropic_direct_auth.py -v`

Expected: PASS for the three tests.

Run: `uv run pyright src/pythinker_code/auth/anthropic_direct.py tests/auth/test_anthropic_direct_auth.py`

Expected: 0/0/0.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/auth/__init__.py src/pythinker_code/auth/anthropic_direct.py tests/auth/test_anthropic_direct_auth.py
git commit -m "feat(auth): add anthropic config helpers"
```

## Task 2: Add Best-Effort Model Discovery And Login Events

**Files:**
- Modify: `src/pythinker_code/auth/anthropic_direct.py`
- Test: `tests/auth/test_anthropic_direct_auth.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/auth/test_anthropic_direct_auth.py`:

```python
def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


@pytest.mark.asyncio
async def test_login_anthropic_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "sk-ant-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr(
        "pythinker_code.auth.anthropic_direct._discover_anthropic_models", fake_discover
    )

    events = [event async for event in login_anthropic_api_key(config, "sk-ant-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "sk-ant-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "anthropic/claude-opus-4-7"
    assert "anthropic/claude-haiku-4-5" in config.models


@pytest.mark.asyncio
async def test_login_anthropic_falls_back_on_non_auth_response_error(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.anthropic.com/v1/models"),
            (),
            status=503,
            message="Service Unavailable",
        )

    monkeypatch.setattr(
        "pythinker_code.auth.anthropic_direct._discover_anthropic_models", fake_discover
    )

    events = [event async for event in login_anthropic_api_key(config, "sk-ant-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert config.default_model == "anthropic/claude-opus-4-7"


@pytest.mark.asyncio
async def test_login_anthropic_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.anthropic.com/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr(
        "pythinker_code.auth.anthropic_direct._discover_anthropic_models", fake_discover
    )

    events = [event async for event in login_anthropic_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid Anthropic API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_anthropic_uses_discovered_context_length(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import (
        AnthropicModel,
        login_anthropic_api_key,
    )

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            AnthropicModel(
                model_id="claude-opus-4-7",
                alias_suffix="claude-opus-4-7",
                display_name="Claude Opus 4.7",
                max_context_size=2_000_000,
            ),
        )

    monkeypatch.setattr(
        "pythinker_code.auth.anthropic_direct._discover_anthropic_models", fake_discover
    )

    events = [event async for event in login_anthropic_api_key(config, "sk-ant-test")]

    assert events[-1].type == "success"
    assert config.models["anthropic/claude-opus-4-7"].max_context_size == 2_000_000


@pytest.mark.asyncio
async def test_login_anthropic_requires_key(tmp_path):
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_anthropic_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "Anthropic API key is required."


@pytest.mark.parametrize(
    "payload, expected_aliases",
    [
        (None, set()),
        ({}, set()),
        ({"data": "not a list"}, set()),
        ({"data": [{"context_length": 1000}]}, set()),
        ({"data": [{"id": "unknown-model"}]}, set()),
        ({"data": [{"id": "claude-opus-4-7"}]}, {"anthropic/claude-opus-4-7"}),
        (
            {"data": [{"id": "claude-haiku-4-5-20251001"}]},
            {"anthropic/claude-haiku-4-5"},
        ),
    ],
)
def test_parse_discovered_anthropic_models_handles_malformed_payloads(payload, expected_aliases):
    from pythinker_code.auth.anthropic_direct import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert {m.alias for m in result} == expected_aliases
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_anthropic_direct_auth.py -v`

Expected: FAIL with `ImportError`/`AttributeError` for `login_anthropic_api_key`, `_discover_anthropic_models`, and `_parse_discovered_models`.

- [ ] **Step 3: Implement discovery, parser, and login (and remove the pyright suppression)**

Add imports at the top of `src/pythinker_code/auth/anthropic_direct.py`:

```python
from collections.abc import AsyncIterator
from typing import Any, cast

import aiohttp

from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import save_config
from pythinker_code.utils.aiohttp import new_client_session
```

Remove the `# Strict pyright reports this as unused...` 2-line comment block AND the `# pyright: ignore[reportUnusedFunction]` directive on `_apply_anthropic_config`.

Append below `_apply_anthropic_config`:

```python
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
```

- [ ] **Step 4: Run tests and pyright**

Run: `uv run pytest tests/auth/test_anthropic_direct_auth.py -v`

Expected: ALL pass.

Run: `uv run pyright src/pythinker_code/auth/anthropic_direct.py tests/auth/test_anthropic_direct_auth.py`

Expected: 0/0/0.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/anthropic_direct.py tests/auth/test_anthropic_direct_auth.py
git commit -m "feat(auth): add anthropic login flow"
```

## Task 3: Add Anthropic Logout

**Files:**
- Modify: `src/pythinker_code/auth/anthropic_direct.py`
- Test: `tests/auth/test_anthropic_direct_auth.py`

- [ ] **Step 1: Add failing logout tests**

Append to `tests/auth/test_anthropic_direct_auth.py`:

```python
@pytest.mark.asyncio
async def test_logout_anthropic_removes_only_anthropic(monkeypatch, tmp_path):
    from pythinker_code.auth.anthropic_direct import (
        ANTHROPIC_PROVIDER_KEY,
        _apply_anthropic_config,
        logout_anthropic,
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
    _apply_anthropic_config(config, SecretStr("sk-ant-test"))

    events = [event async for event in logout_anthropic(config)]

    assert events[-1].type == "success"
    assert ANTHROPIC_PROVIDER_KEY not in config.providers
    assert "anthropic/claude-opus-4-7" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_anthropic_rejects_non_default_config_location():
    from pythinker_code.auth.anthropic_direct import logout_anthropic

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_anthropic(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_anthropic_direct_auth.py -v -k logout`

Expected: FAIL with `ImportError` for `logout_anthropic`.

- [ ] **Step 3: Implement logout**

Append to `src/pythinker_code/auth/anthropic_direct.py`:

```python
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
```

- [ ] **Step 4: Run all tests + pyright**

Run: `uv run pytest tests/auth/test_anthropic_direct_auth.py -v`

Expected: ALL pass.

Run: `uv run pyright src/pythinker_code/auth/anthropic_direct.py tests/auth/test_anthropic_direct_auth.py`

Expected: 0/0/0.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/anthropic_direct.py tests/auth/test_anthropic_direct_auth.py
git commit -m "feat(auth): add anthropic logout"
```

## Task 4: Wire CLI Login And Logout Flags

**Files:**
- Modify: `src/pythinker_code/cli/__init__.py`
- Modify: `tests/cli/test_openai_login_cli.py`

- [ ] **Step 1: Inspect existing CLI patterns**

Read the current `login` and `logout` Typer commands. Note how the prior (`--minimax`, `--opencode-go`, `--deepseek`) flags are wired. The new `--anthropic` flag follows the same shape.

If the DeepSeek plan has not yet landed, the references below to `deepseek` flags must be omitted; this plan assumes DeepSeek is already wired.

- [ ] **Step 2: Add failing CLI routing tests**

Append to `tests/cli/test_openai_login_cli.py`:

```python
def test_cli_login_anthropic_routes_to_anthropic(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.login_anthropic_api_key", login, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["login", "--anthropic"], input="sk-ant-test\n")

    assert result.exit_code == 0
    assert login.call_args.args[1] == "sk-ant-test"


def test_cli_login_rejects_anthropic_with_other_modes(monkeypatch):
    result = runner.invoke(cli, ["login", "--anthropic", "--api-key"])

    assert result.exit_code == 1
    assert "Choose only one" in result.output


def test_cli_logout_anthropic_routes_to_anthropic_logout(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.logout_anthropic", logout, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["logout", "--anthropic"])

    assert result.exit_code == 0
    assert logout.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -v -k anthropic`

Expected: FAIL because `--anthropic` does not exist.

- [ ] **Step 4: Import Anthropic functions in CLI**

Add to `src/pythinker_code/cli/__init__.py`:

```python
from pythinker_code.auth.anthropic_direct import login_anthropic_api_key, logout_anthropic
```

- [ ] **Step 5: Add `--anthropic` flag to `login` and route**

Add the flag to the `login` command signature (placed after the `deepseek` flag, if present, otherwise after `minimax`):

```python
    anthropic: bool = typer.Option(
        False, "--anthropic", help="Configure Anthropic with an API key."
    ),
```

Update the docstring: `"""Login with OpenAI, OpenCode Go, MiniMax, DeepSeek, or Anthropic."""`.

Update the mode-conflict check:

```python
        selected_modes = sum(
            bool(value)
            for value in (browser, headless, api_key, opencode_go, minimax, deepseek, anthropic)
        )
        if selected_modes > 1:
            typer.echo(
                "Choose only one of --browser, --headless, --api-key, --opencode-go, --minimax, --deepseek, or --anthropic.",
                err=True,
            )
            return False
```

Insert the Anthropic branch BEFORE the existing `deepseek` branch:

```python
        if anthropic:
            key = typer.prompt("Anthropic API key", hide_input=True).strip()
            events = login_anthropic_api_key(config, key)
        elif deepseek:
            ...
```

- [ ] **Step 6: Add `--anthropic` flag to `logout` and route**

Add the flag (placed after the `deepseek` flag):

```python
    anthropic: bool = typer.Option(False, "--anthropic", help="Logout from Anthropic."),
```

Update the docstring: `"""Logout from OpenAI, OpenCode Go, MiniMax, DeepSeek, or Anthropic."""`.

Extend mode-conflict and `events` selection:

```python
        if sum(bool(v) for v in (opencode_go, minimax, deepseek, anthropic)) > 1:
            typer.echo(
                "Choose only one of --opencode-go, --minimax, --deepseek, or --anthropic.",
                err=True,
            )
            return False

        config = load_config()
        if anthropic:
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
git commit -m "feat(cli): route anthropic auth commands"
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
async def test_shell_login_anthropic_routes_to_anthropic(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "login_anthropic_api_key", login, raising=False)
    monkeypatch.setattr(
        shell_oauth, "_prompt_api_key", lambda label: _async_value("sk-ant-test")
    )

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.login)(_app(), "anthropic")

    assert login.call_args.args[1] == "sk-ant-test"


@pytest.mark.asyncio
async def test_shell_logout_anthropic_routes_to_anthropic(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "logout_anthropic", logout, raising=False)

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.logout)(_app(), "anthropic")

    assert logout.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v -k anthropic`

Expected: FAIL.

- [ ] **Step 4: Import Anthropic functions and platform ID**

Modify `src/pythinker_code/ui/shell/oauth.py`. Update the existing `from pythinker_code.auth import ...` line:

```python
from pythinker_code.auth import (
    ANTHROPIC_PLATFORM_ID,
    DEEPSEEK_PLATFORM_ID,
    MINIMAX_PLATFORM_ID,
    OPENCODE_GO_PLATFORM_ID,
)
```

Add:

```python
from pythinker_code.auth.anthropic_direct import (
    login_anthropic_api_key,
    logout_anthropic,
)
```

- [ ] **Step 5: Append Anthropic to the chooser**

Add a new entry to `_LOGIN_PROVIDER_OPTIONS` (sequential number after the prior providers — 7 if DeepSeek already landed):

```python
    ("7", "anthropic", "Anthropic"),
```

Update the prompt label in `_prompt_login_provider`:

```python
        choice = await session.prompt_async(" Enter [1-7] (default 1): ")
```

- [ ] **Step 6: Add `/login anthropic` route**

Insert a branch BEFORE the existing `deepseek` branch:

```python
    elif mode == "anthropic":
        api_key = await _prompt_api_key("Anthropic")
        if not api_key:
            console.print("[red]No Anthropic API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_anthropic_api_key(soul.runtime.config, api_key))
        provider = ANTHROPIC_PLATFORM_ID
```

Update the unknown-mode usage error to include the new mode:

```python
        console.print(
            "[red]Usage: /login [browser|headless|api-key|opencode-go|minimax|deepseek|anthropic][/red]"
        )
```

- [ ] **Step 7: Add `/logout anthropic` route**

Modify `logout` in `src/pythinker_code/ui/shell/oauth.py`:

```python
    mode = args.strip().lower()
    if mode == "anthropic":
        ok = await _render_oauth_events(logout_anthropic(config))
    elif mode == "deepseek":
        ok = await _render_oauth_events(logout_deepseek(config))
    elif mode == "minimax":
        ok = await _render_oauth_events(logout_minimax(config))
    elif mode in ("opencode-go", "opencode", "go"):
        ok = await _render_oauth_events(logout_opencode_go(config))
    elif mode == "":
        ok = await _render_oauth_events(logout_openai(config))
    else:
        console.print("[red]Usage: /logout [opencode-go|minimax|deepseek|anthropic][/red]")
        return
```

- [ ] **Step 8: Update docstrings**

```python
"""Login with OpenAI, OpenCode Go, MiniMax, DeepSeek, or Anthropic."""
"""Logout from OpenAI, OpenCode Go, MiniMax, DeepSeek, or Anthropic."""
```

- [ ] **Step 9: Run shell tests + pyright**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v`

Expected: PASS.

Run: `uv run pyright src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py`

Expected: 0/0/0.

- [ ] **Step 10: Commit**

```bash
git add src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py
git commit -m "feat(shell): route anthropic auth commands"
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

- [ ] **Step 3: Run focused Anthropic + integration test suite**

Run:

```bash
uv run pytest tests/auth/test_anthropic_direct_auth.py \
  tests/cli/test_openai_login_cli.py \
  tests/ui_and_conv/test_openai_shell_login.py -v
```

Expected: ALL pass.

- [ ] **Step 4: Inspect end-to-end diff**

Run: `git diff --stat <pre-feature-SHA>..HEAD` (use the commit immediately before Task 1's commit).

Expected: diff contains only the 7 files listed under "File Structure" plus this plan + spec doc.

Run: `git log --format='%H %s%n%b%n---' <pre-feature-SHA>..HEAD`

Expected: every commit body is empty (subject only). NO Co-Authored-By trailer. NO "Generated with Claude Code" footer.

- [ ] **Step 5: Final commit (only if Step 1 or Step 2 mutated files)**

If `make format` or `make check` modified any files:

```bash
git add <files-listed-by-status>
git commit -m "chore: finalize anthropic auth checks"
```

If nothing changed, do NOT create an empty commit.

## Self-Review Notes

- **Spec coverage:** The plan covers dedicated CLI/shell login, env-key resolution, single-provider config, all three frontier model aliases (Opus 4.7, Sonnet 4.6, Haiku 4.5), best-effort discovery using `x-api-key` + `anthropic-version` headers, auth-failure handling, secret redaction, logout, chooser update, and tests with mocked network calls. Provider construction (`anthropic` type at custom base URL) is pre-verified by OpenCode Go's Task 6.
- **Scope control:** Excludes third-party gateways (Bedrock, Vertex, Foundry), Anthropic OAuth, beta endpoints (Files, Skills, Agents, Sessions), and legacy Claude models.
- **Type consistency:** Provider key is `managed:anthropic` everywhere. Model alias format is `anthropic/<suffix>`. API model IDs preserve their dated suffix where Anthropic ships dated snapshots (`claude-haiku-4-5-20251001` while alias suffix drops the date for stability). `ANTHROPIC_PLATFORM_ID = "anthropic"` (note: same string as the `LLMProvider.type = "anthropic"` value, but they are independent identifiers used in different contexts). `OAuthEvent` is constructed positionally throughout.
- **Implementation risk:** Low. Header convention differs (`x-api-key` instead of `Authorization: Bearer`) but is fully encapsulated in `_discover_anthropic_models`; the `pythinker_core` `anthropic` provider already uses native Anthropic auth internally for chat traffic.
