# OpenCode Go Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated OpenCode Go setup/logout path and configure all current OpenCode Go plan models in Pythinker Code.

**Architecture:** Add a focused `pythinker_code.auth.opencode_go` module that owns OpenCode Go constants, model metadata, config writes, best-effort model discovery, login events, and logout events. Reuse existing provider types: `openai_legacy` for `chat/completions` models and `anthropic` for `messages` models. Wire the module into existing `pythinker login`, `/login`, `pythinker logout`, and `/logout` routing without changing the default OpenAI behavior.

**Tech Stack:** Python 3.12+, Typer, pytest, pytest-asyncio, pydantic `SecretStr`, aiohttp, existing `OAuthEvent`, `Config`, `LLMProvider`, `LLMModel`, and `save_config` patterns.

---

## File Structure

- Create: `src/pythinker_code/auth/opencode_go.py`
  - Owns OpenCode Go constants, model metadata, env-key selection, discovery, config application, login, and logout.
- Modify: `src/pythinker_code/auth/__init__.py`
  - Exports `OPENCODE_GO_PLATFORM_ID`.
- Modify: `src/pythinker_code/cli/__init__.py`
  - Adds `--opencode-go` login/logout flags and routes to the new auth functions.
- Modify: `src/pythinker_code/ui/shell/oauth.py`
  - Adds `/login opencode-go`, `/logout opencode-go`, and an OpenCode Go API-key prompt.
- Create: `tests/auth/test_opencode_go_auth.py`
  - Covers model constants, env precedence, config writes, discovery fallback, auth failures, secret redaction, and logout.
- Modify: `tests/cli/test_openai_login_cli.py`
  - Adds CLI route tests for OpenCode Go login/logout and mode conflict handling.
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`
  - Adds shell route tests for `/login opencode-go` and `/logout opencode-go`.

## Task 1: Add OpenCode Go Constants And Config Helpers

**Files:**
- Create: `src/pythinker_code/auth/opencode_go.py`
- Modify: `src/pythinker_code/auth/__init__.py`
- Test: `tests/auth/test_opencode_go_auth.py`

- [ ] **Step 1: Write failing tests for metadata, env precedence, and config writes**

Add `tests/auth/test_opencode_go_auth.py`:

```python
from __future__ import annotations

from pydantic import SecretStr

from pythinker_code.config import Config


def test_opencode_go_model_catalog_contains_all_current_models():
    from pythinker_code.auth.opencode_go import OPENCODE_GO_MODELS

    aliases = {model.alias for model in OPENCODE_GO_MODELS}
    assert aliases == {
        "opencode-go/glm-5",
        "opencode-go/glm-5.1",
        "opencode-go/kimi-k2.5",
        "opencode-go/kimi-k2.6",
        "opencode-go/deepseek-v4-pro",
        "opencode-go/deepseek-v4-flash",
        "opencode-go/mimo-v2-pro",
        "opencode-go/mimo-v2-omni",
        "opencode-go/mimo-v2.5-pro",
        "opencode-go/mimo-v2.5",
        "opencode-go/qwen3.5-plus",
        "opencode-go/qwen3.6-plus",
        "opencode-go/minimax-m2.5",
        "opencode-go/minimax-m2.7",
    }

    minimax = {m.model_id: m.provider_key for m in OPENCODE_GO_MODELS if m.model_id.startswith("minimax-")}
    assert minimax == {
        "minimax-m2.5": "managed:opencode-go-anthropic",
        "minimax-m2.7": "managed:opencode-go-anthropic",
    }
    assert all(
        m.provider_key == "managed:opencode-go-openai"
        for m in OPENCODE_GO_MODELS
        if not m.model_id.startswith("minimax-")
    )


def test_opencode_go_env_key_precedence(monkeypatch):
    from pythinker_code.auth.opencode_go import get_opencode_go_api_key_from_env

    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "zen-key")
    assert get_opencode_go_api_key_from_env() == "zen-key"

    monkeypatch.setenv("OPENCODE_API_KEY", "api-key")
    assert get_opencode_go_api_key_from_env() == "api-key"

    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-key")
    assert get_opencode_go_api_key_from_env() == "go-key"


def test_apply_opencode_go_config_writes_two_providers_and_default():
    from pythinker_code.auth.opencode_go import (
        OPENCODE_GO_ANTHROPIC_PROVIDER_KEY,
        OPENCODE_GO_BASE_URL,
        OPENCODE_GO_OPENAI_PROVIDER_KEY,
        _apply_opencode_go_config,
    )

    config = Config(is_from_default_location=True)

    _apply_opencode_go_config(config, SecretStr("ocgo-test"))

    assert set(config.providers) == {
        OPENCODE_GO_OPENAI_PROVIDER_KEY,
        OPENCODE_GO_ANTHROPIC_PROVIDER_KEY,
    }
    openai_provider = config.providers[OPENCODE_GO_OPENAI_PROVIDER_KEY]
    anthropic_provider = config.providers[OPENCODE_GO_ANTHROPIC_PROVIDER_KEY]
    assert openai_provider.type == "openai_legacy"
    assert anthropic_provider.type == "anthropic"
    assert openai_provider.base_url == OPENCODE_GO_BASE_URL
    assert anthropic_provider.base_url == OPENCODE_GO_BASE_URL
    assert openai_provider.api_key.get_secret_value() == "ocgo-test"
    assert anthropic_provider.api_key.get_secret_value() == "ocgo-test"
    assert config.models["opencode-go/kimi-k2.6"].provider == OPENCODE_GO_OPENAI_PROVIDER_KEY
    assert config.models["opencode-go/minimax-m2.7"].provider == OPENCODE_GO_ANTHROPIC_PROVIDER_KEY
    assert config.default_model == "opencode-go/kimi-k2.6"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_opencode_go_auth.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'pythinker_code.auth.opencode_go'`.

- [ ] **Step 3: Export the platform ID**

Modify `src/pythinker_code/auth/__init__.py`:

```python
PYTHINKER_CODE_PLATFORM_ID = "pythinker-code"
OPENAI_API_PLATFORM_ID = "openai"
OPENAI_CHATGPT_PLATFORM_ID = "openai-chatgpt"
OPENCODE_GO_PLATFORM_ID = "opencode-go"

__all__ = [
    "OPENAI_API_PLATFORM_ID",
    "OPENAI_CHATGPT_PLATFORM_ID",
    "OPENCODE_GO_PLATFORM_ID",
    "PYTHINKER_CODE_PLATFORM_ID",
]
```

- [ ] **Step 4: Implement constants and config helper**

Create `src/pythinker_code/auth/opencode_go.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import SecretStr

from pythinker_code.auth import OPENCODE_GO_PLATFORM_ID
from pythinker_code.config import Config, LLMModel, LLMProvider

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
        config.default_model = next((model.alias for model in models), next(iter(config.models), ""))
    config.default_thinking = False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_opencode_go_auth.py -v`

Expected: PASS for the three tests in this task.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/auth/__init__.py src/pythinker_code/auth/opencode_go.py tests/auth/test_opencode_go_auth.py
git commit -m "feat(auth): add opencode go config helpers"
```

## Task 2: Add Best-Effort Model Discovery And Login Events

**Files:**
- Modify: `src/pythinker_code/auth/opencode_go.py`
- Test: `tests/auth/test_opencode_go_auth.py`

- [ ] **Step 1: Add failing tests for login success, auth failure, fallback, and redaction**

Append to `tests/auth/test_opencode_go_auth.py`:

```python
import aiohttp
import pytest


def _request_info(url: str):
    return aiohttp.RequestInfo(
        url=aiohttp.client_reqrep.URL(url),
        method="GET",
        headers={},
        real_url=aiohttp.client_reqrep.URL(url),
    )


@pytest.mark.asyncio
async def test_login_opencode_go_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "ocgo-test"
        raise RuntimeError("models unavailable")

    monkeypatch.setattr("pythinker_code.auth.opencode_go._discover_opencode_go_models", fake_discover)

    events = [event async for event in login_opencode_go_api_key(config, "ocgo-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "ocgo-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "opencode-go/kimi-k2.6"
    assert "opencode-go/minimax-m2.5" in config.models
    assert (tmp_path / "config.toml").exists()


@pytest.mark.asyncio
async def test_login_opencode_go_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://opencode.ai/zen/go/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr("pythinker_code.auth.opencode_go._discover_opencode_go_models", fake_discover)

    events = [event async for event in login_opencode_go_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid OpenCode Go API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_opencode_go_uses_discovered_context_length(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import OpenCodeGoModel, login_opencode_go_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            OpenCodeGoModel(
                "kimi-k2.6",
                "Kimi K2.6",
                "managed:opencode-go-openai",
                512_000,
            ),
        )

    monkeypatch.setattr("pythinker_code.auth.opencode_go._discover_opencode_go_models", fake_discover)

    events = [event async for event in login_opencode_go_api_key(config, "ocgo-test")]

    assert events[-1].type == "success"
    assert config.models["opencode-go/kimi-k2.6"].max_context_size == 512_000


@pytest.mark.asyncio
async def test_login_opencode_go_requires_key(tmp_path):
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_opencode_go_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "OpenCode Go API key is required."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_opencode_go_auth.py -v`

Expected: FAIL with `ImportError` or `AttributeError` for `login_opencode_go_api_key` and `_discover_opencode_go_models`.

- [ ] **Step 3: Implement discovery and login**

Append and update `src/pythinker_code/auth/opencode_go.py`:

```python
from collections.abc import AsyncIterator
from typing import Any, cast

import aiohttp

from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import save_config
from pythinker_code.utils.aiohttp import new_client_session


def _model_by_id() -> dict[str, OpenCodeGoModel]:
    return {model.model_id: model for model in OPENCODE_GO_MODELS}


def _parse_discovered_models(data: object) -> tuple[OpenCodeGoModel, ...]:
    if not isinstance(data, dict):
        return ()
    raw_items = data.get("data")
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
    async with new_client_session() as session:
        async with session.get(
            f"{OPENCODE_GO_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            raise_for_status=True,
        ) as response:
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
    except Exception:
        yield OAuthEvent(
            "info",
            "OpenCode Go model listing is unavailable; using the built-in model list.",
        )

    _apply_opencode_go_config(config, SecretStr(resolved_key), models=models)
    save_config(config)
    yield OAuthEvent("success", f"OpenCode Go configured with model {config.default_model}.")
```

- [ ] **Step 4: Verify the key-required test is exact**

The final `test_login_opencode_go_requires_key` in `tests/auth/test_opencode_go_auth.py` must be:

```python
@pytest.mark.asyncio
async def test_login_opencode_go_requires_key(tmp_path):
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_opencode_go_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "OpenCode Go API key is required."
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_opencode_go_auth.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/auth/opencode_go.py tests/auth/test_opencode_go_auth.py
git commit -m "feat(auth): add opencode go login flow"
```

## Task 3: Add OpenCode Go Logout

**Files:**
- Modify: `src/pythinker_code/auth/opencode_go.py`
- Test: `tests/auth/test_opencode_go_auth.py`

- [ ] **Step 1: Add failing logout test**

Append to `tests/auth/test_opencode_go_auth.py`:

```python
@pytest.mark.asyncio
async def test_logout_opencode_go_removes_only_opencode_go(monkeypatch, tmp_path):
    from pythinker_code.auth.opencode_go import (
        OPENCODE_GO_ANTHROPIC_PROVIDER_KEY,
        OPENCODE_GO_OPENAI_PROVIDER_KEY,
        _apply_opencode_go_config,
        logout_opencode_go,
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
    _apply_opencode_go_config(config, SecretStr("ocgo-test"))

    events = [event async for event in logout_opencode_go(config)]

    assert events[-1].type == "success"
    assert OPENCODE_GO_OPENAI_PROVIDER_KEY not in config.providers
    assert OPENCODE_GO_ANTHROPIC_PROVIDER_KEY not in config.providers
    assert "opencode-go/kimi-k2.6" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/auth/test_opencode_go_auth.py::test_logout_opencode_go_removes_only_opencode_go -v`

Expected: FAIL with `ImportError` for `logout_opencode_go`.

- [ ] **Step 3: Implement logout**

Append to `src/pythinker_code/auth/opencode_go.py`:

```python
async def logout_opencode_go(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    provider_keys = {OPENCODE_GO_OPENAI_PROVIDER_KEY, OPENCODE_GO_ANTHROPIC_PROVIDER_KEY}
    removed_default = False
    for provider_key in provider_keys:
        config.providers.pop(provider_key, None)
    for key, model in list(config.models.items()):
        if model.provider not in provider_keys:
            continue
        del config.models[key]
        if config.default_model == key:
            removed_default = True

    if removed_default or config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of OpenCode Go successfully.")
```

- [ ] **Step 4: Run auth tests**

Run: `uv run pytest tests/auth/test_opencode_go_auth.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/opencode_go.py tests/auth/test_opencode_go_auth.py
git commit -m "feat(auth): add opencode go logout"
```

## Task 4: Wire CLI Login And Logout Flags

**Files:**
- Modify: `src/pythinker_code/cli/__init__.py`
- Modify: `tests/cli/test_openai_login_cli.py`

- [ ] **Step 1: Add failing CLI routing tests**

Append to `tests/cli/test_openai_login_cli.py`:

```python
def test_cli_login_opencode_go_routes_to_opencode_go(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.login_opencode_go_api_key", login, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["login", "--opencode-go"], input="ocgo-test\n")

    assert result.exit_code == 0
    assert login.call_args.args[1] == "ocgo-test"


def test_cli_login_rejects_opencode_go_with_openai_mode(monkeypatch):
    result = runner.invoke(cli, ["login", "--opencode-go", "--api-key"])

    assert result.exit_code == 1
    assert "Choose only one" in result.output


def test_cli_logout_opencode_go_routes_to_opencode_go_logout(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.logout_opencode_go", logout, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["logout", "--opencode-go"])

    assert result.exit_code == 0
    assert logout.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -v`

Expected: FAIL because `--opencode-go` does not exist.

- [ ] **Step 3: Import OpenCode Go functions in CLI**

Modify imports in `src/pythinker_code/cli/__init__.py`:

```python
from pythinker_code.auth.opencode_go import login_opencode_go_api_key, logout_opencode_go
```

- [ ] **Step 4: Add login flag and route**

Modify `login` signature and mode routing in `src/pythinker_code/cli/__init__.py`:

```python
    opencode_go: bool = typer.Option(
        False, "--opencode-go", help="Configure OpenCode Go with an API key."
    ),
) -> None:
    """Login with OpenAI or OpenCode Go."""
```

Replace selected mode logic:

```python
        selected_modes = sum(bool(value) for value in (browser, headless, api_key, opencode_go))
        if selected_modes > 1:
            typer.echo(
                "Choose only one of --browser, --headless, --api-key, or --opencode-go.",
                err=True,
            )
            return False

        config = load_config()
        if opencode_go:
            key = typer.prompt("OpenCode Go API key", hide_input=True).strip()
            events = login_opencode_go_api_key(config, key)
        elif api_key:
            key = typer.prompt("OpenAI API key", hide_input=True).strip()
            events = login_openai_api_key(config, key)
```

- [ ] **Step 5: Add logout flag and route**

Modify `logout` signature and routing in `src/pythinker_code/cli/__init__.py`:

```python
    opencode_go: bool = typer.Option(
        False, "--opencode-go", help="Logout from OpenCode Go."
    ),
) -> None:
    """Logout from OpenAI or OpenCode Go."""
```

Inside `_run`, select events once:

```python
        config = load_config()
        events = logout_opencode_go(config) if opencode_go else logout_openai(config)
```

Use `events` in both JSON and console loops instead of calling `logout_openai(load_config())` directly.

- [ ] **Step 6: Run CLI tests**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/pythinker_code/cli/__init__.py tests/cli/test_openai_login_cli.py
git commit -m "feat(cli): route opencode go auth commands"
```

## Task 5: Wire Shell Login And Logout Commands

**Files:**
- Modify: `src/pythinker_code/ui/shell/oauth.py`
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`

- [ ] **Step 1: Add failing shell route tests**

Append to `tests/ui_and_conv/test_openai_shell_login.py`:

```python
@pytest.mark.asyncio
async def test_shell_login_opencode_go_routes_to_opencode_go(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "login_opencode_go_api_key", login, raising=False)
    monkeypatch.setattr(shell_oauth, "_prompt_opencode_go_api_key", lambda: _async_value("ocgo-test"))

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.login)(_app(), "opencode-go")

    assert login.call_args.args[1] == "ocgo-test"


@pytest.mark.asyncio
async def test_shell_logout_opencode_go_routes_to_opencode_go(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "logout_opencode_go", logout, raising=False)

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.logout)(_app(), "opencode-go")

    assert logout.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v`

Expected: FAIL because shell routes do not know OpenCode Go.

- [ ] **Step 3: Import OpenCode Go functions**

Modify `src/pythinker_code/ui/shell/oauth.py` imports:

```python
from pythinker_code.auth.opencode_go import login_opencode_go_api_key, logout_opencode_go
```

- [ ] **Step 4: Add API key prompt**

Add below `_prompt_openai_api_key`:

```python
async def _prompt_opencode_go_api_key() -> str | None:
    session = PromptSession[str]()
    try:
        value = await session.prompt_async(" OpenCode Go API key: ", is_password=True)
    except (EOFError, KeyboardInterrupt):
        return None
    return value.strip() or None
```

- [ ] **Step 5: Add `/login opencode-go` route**

Modify `login` in `src/pythinker_code/ui/shell/oauth.py`:

```python
    elif mode in ("opencode-go", "opencode", "go"):
        api_key = await _prompt_opencode_go_api_key()
        ok = await _render_oauth_events(login_opencode_go_api_key(soul.runtime.config, api_key))
        provider = "opencode-go"
```

Update the usage error:

```python
        console.print("[red]Usage: /login [browser|headless|api-key|opencode-go][/red]")
```

- [ ] **Step 6: Add `/logout opencode-go` route**

Modify `logout` in `src/pythinker_code/ui/shell/oauth.py`:

```python
    mode = args.strip().lower()
    if mode in ("opencode-go", "opencode", "go"):
        ok = await _render_oauth_events(logout_opencode_go(config))
    elif mode == "":
        ok = await _render_oauth_events(logout_openai(config))
    else:
        console.print("[red]Usage: /logout [opencode-go][/red]")
        return
```

- [ ] **Step 7: Run shell tests**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py
git commit -m "feat(shell): route opencode go auth commands"
```

## Task 6: Verify LLM Provider Compatibility And Focused Suite

**Files:**
- Modify: `tests/core/test_openai_provider.py`
- Verify: `src/pythinker_code/llm.py`

- [ ] **Step 1: Add provider construction tests for both OpenCode Go provider types**

Append to `tests/core/test_openai_provider.py`:

```python
def test_create_llm_supports_opencode_go_openai_provider(monkeypatch):
    captured = {}

    class FakeOpenAILegacy:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.model_name = kwargs["model"]

    monkeypatch.setattr("pythinker_core.contrib.chat_provider.openai_legacy.OpenAILegacy", FakeOpenAILegacy)

    provider = LLMProvider(
        type="openai_legacy",
        base_url="https://opencode.ai/zen/go/v1",
        api_key=SecretStr("ocgo-test"),
    )
    model = LLMModel(
        provider="managed:opencode-go-openai",
        model="kimi-k2.6",
        max_context_size=262_000,
    )

    llm = create_llm(provider, model)

    assert llm is not None
    assert captured["model"] == "kimi-k2.6"
    assert captured["base_url"] == "https://opencode.ai/zen/go/v1"
    assert captured["api_key"] == "ocgo-test"


def test_create_llm_supports_opencode_go_anthropic_provider(monkeypatch):
    captured = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.model_name = kwargs["model"]

    monkeypatch.setattr("pythinker_core.contrib.chat_provider.anthropic.Anthropic", FakeAnthropic)

    provider = LLMProvider(
        type="anthropic",
        base_url="https://opencode.ai/zen/go/v1",
        api_key=SecretStr("ocgo-test"),
    )
    model = LLMModel(
        provider="managed:opencode-go-anthropic",
        model="minimax-m2.7",
        max_context_size=205_000,
    )

    llm = create_llm(provider, model)

    assert llm is not None
    assert captured["model"] == "minimax-m2.7"
    assert captured["base_url"] == "https://opencode.ai/zen/go/v1"
    assert captured["api_key"] == "ocgo-test"
```

- [ ] **Step 2: Run provider tests**

Run: `uv run pytest tests/core/test_openai_provider.py -v`

Expected: PASS. A failure here means the existing provider wrappers do not support the configured OpenCode Go shape; stop, capture the failure, and revise the OpenCode Go provider design before continuing.

- [ ] **Step 3: Run focused auth and routing tests**

Run: `uv run pytest tests/auth/test_opencode_go_auth.py tests/cli/test_openai_login_cli.py tests/ui_and_conv/test_openai_shell_login.py tests/core/test_openai_provider.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/core/test_openai_provider.py
git commit -m "test(auth): cover opencode go provider construction"
```

## Task 7: Final Quality Checks

**Files:**
- Verify all touched files.

- [ ] **Step 1: Run formatting**

Run: `make format`

Expected: command exits 0. If formatting changes files, include those changes in the final commit.

- [ ] **Step 2: Run project checks**

Run: `make check`

Expected: command exits 0.

- [ ] **Step 3: Run tests**

Run: `make test`

Expected: command exits 0.

- [ ] **Step 4: Inspect git diff**

Run: `git diff -- src/pythinker_code/auth/__init__.py src/pythinker_code/auth/opencode_go.py src/pythinker_code/cli/__init__.py src/pythinker_code/ui/shell/oauth.py tests/auth/test_opencode_go_auth.py tests/cli/test_openai_login_cli.py tests/ui_and_conv/test_openai_shell_login.py tests/core/test_openai_provider.py`

Expected: diff only contains OpenCode Go auth/setup changes.

- [ ] **Step 5: Final commit if verification changed files**

```bash
git add src/pythinker_code/auth/__init__.py src/pythinker_code/auth/opencode_go.py src/pythinker_code/cli/__init__.py src/pythinker_code/ui/shell/oauth.py tests/auth/test_opencode_go_auth.py tests/cli/test_openai_login_cli.py tests/ui_and_conv/test_openai_shell_login.py tests/core/test_openai_provider.py
git commit -m "chore: finalize opencode go auth checks"
```

Only create this commit if Task 7 changed files that were not already committed.

## Self-Review Notes

- Spec coverage: The plan covers dedicated CLI/shell login, env key precedence, two-provider config, all current models, best-effort discovery, auth failure handling, secret redaction, logout, and tests with mocked network calls.
- Scope control: The plan excludes Tavily, Context7, generic OpenCode CLI integration, and external `opencode` binary usage.
- Type consistency: Provider keys are string constants, model aliases use `opencode-go/<model-id>`, `OAuthEvent` is reused for event rendering, and API keys use `SecretStr` in config writes.
- Implementation risk: MiniMax compatibility depends on the existing Anthropic provider working with `https://opencode.ai/zen/go/v1`; Task 6 verifies construction and defines the escalation path if the provider cannot support the endpoint.
