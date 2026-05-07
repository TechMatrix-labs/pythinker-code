# DeepSeek Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated DeepSeek setup/logout path and configure the four current DeepSeek V4 text models in Pythinker Code.

**Architecture:** Add a focused `pythinker_code.auth.deepseek` module that owns DeepSeek constants, model metadata, env-key resolution, best-effort model discovery, login events, and logout events. Reuse the existing `openai_legacy` provider type at `https://api.deepseek.com/v1` (single managed provider). Wire the module into existing `pythinker login`, `/login`, `pythinker logout`, and `/logout` routing without changing any current behavior. Append `DeepSeek` to the `/login` shell chooser.

**Tech Stack:** Python 3.12+, Typer, pytest, pytest-asyncio, pydantic `SecretStr`, aiohttp, existing `OAuthEvent`, `Config`, `LLMProvider`, `LLMModel`, `save_config`, the shared `_prompt_api_key` shell helper, and the `_LOGIN_PROVIDER_OPTIONS` chooser tuple.

---

## File Structure

- Create: `src/pythinker_code/auth/deepseek.py`
  - Owns DeepSeek constants, model metadata, env-key resolution, discovery, config application, login, and logout.
- Modify: `src/pythinker_code/auth/__init__.py`
  - Exports `DEEPSEEK_PLATFORM_ID`.
- Modify: `src/pythinker_code/cli/__init__.py`
  - Adds `--deepseek` login/logout flags and routes to the new auth functions.
- Modify: `src/pythinker_code/ui/shell/oauth.py`
  - Adds `/login deepseek` and `/logout deepseek` routes; appends `DeepSeek` to `_LOGIN_PROVIDER_OPTIONS`.
- Create: `tests/auth/test_deepseek_auth.py`
  - Covers model constants, env resolution, config writes, discovery fallback, auth failures, secret redaction, parser malformed payloads, and logout.
- Modify: `tests/cli/test_openai_login_cli.py`
  - Adds CLI route tests for DeepSeek login/logout and mode-conflict handling.
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`
  - Adds shell route tests for `/login deepseek` and `/logout deepseek`.

## Task 1: Add DeepSeek Constants And Config Helpers

**Files:**
- Create: `src/pythinker_code/auth/deepseek.py`
- Modify: `src/pythinker_code/auth/__init__.py`
- Test: `tests/auth/test_deepseek_auth.py`

- [ ] **Step 1: Write failing tests for metadata, env resolution, and config writes**

Create `tests/auth/test_deepseek_auth.py`:

```python
from __future__ import annotations

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from pydantic import SecretStr
from yarl import URL

from pythinker_code.config import Config


def test_deepseek_model_catalog_contains_two_current_models():
    from pythinker_code.auth.deepseek import DEEPSEEK_MODELS

    aliases = {model.alias for model in DEEPSEEK_MODELS}
    assert aliases == {"deepseek/v4-pro", "deepseek/v4-flash"}

    api_ids = {m.alias: m.model_id for m in DEEPSEEK_MODELS}
    assert api_ids == {
        "deepseek/v4-pro": "deepseek-v4-pro",
        "deepseek/v4-flash": "deepseek-v4-flash",
    }

    assert all(m.provider_key == "managed:deepseek" for m in DEEPSEEK_MODELS)


def test_deepseek_env_key_uses_deepseek_api_key(monkeypatch):
    from pythinker_code.auth.deepseek import get_deepseek_api_key_from_env

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert get_deepseek_api_key_from_env() is None

    monkeypatch.setenv("DEEPSEEK_API_KEY", "  ds-key  ")
    assert get_deepseek_api_key_from_env() == "ds-key"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    assert get_deepseek_api_key_from_env() is None


def test_apply_deepseek_config_writes_provider_and_default():
    from pythinker_code.auth.deepseek import (
        DEEPSEEK_BASE_URL,
        DEEPSEEK_PROVIDER_KEY,
        _apply_deepseek_config,
    )

    config = Config(is_from_default_location=True)

    _apply_deepseek_config(config, SecretStr("ds-test"))

    assert set(config.providers) == {DEEPSEEK_PROVIDER_KEY}
    provider = config.providers[DEEPSEEK_PROVIDER_KEY]
    assert provider.type == "openai_legacy"
    assert provider.base_url == DEEPSEEK_BASE_URL
    assert provider.api_key.get_secret_value() == "ds-test"
    assert config.models["deepseek/v4-pro"].provider == DEEPSEEK_PROVIDER_KEY
    assert config.models["deepseek/v4-pro"].model == "deepseek-v4-pro"
    assert config.default_model == "deepseek/v4-pro"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_deepseek_auth.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'pythinker_code.auth.deepseek'`.

- [ ] **Step 3: Export the platform ID**

Modify `src/pythinker_code/auth/__init__.py`. Inspect the current file before editing (it already exports `PYTHINKER_CODE_PLATFORM_ID`, `OPENAI_API_PLATFORM_ID`, `OPENAI_CHATGPT_PLATFORM_ID`, `OPENCODE_GO_PLATFORM_ID`, `MINIMAX_PLATFORM_ID`). Add `DEEPSEEK_PLATFORM_ID` and include it in `__all__`:

```python
PYTHINKER_CODE_PLATFORM_ID = "pythinker-code"
OPENAI_API_PLATFORM_ID = "openai"
OPENAI_CHATGPT_PLATFORM_ID = "openai-chatgpt"
OPENCODE_GO_PLATFORM_ID = "opencode-go"
MINIMAX_PLATFORM_ID = "minimax"
DEEPSEEK_PLATFORM_ID = "deepseek"

__all__ = [
    "DEEPSEEK_PLATFORM_ID",
    "MINIMAX_PLATFORM_ID",
    "OPENAI_API_PLATFORM_ID",
    "OPENAI_CHATGPT_PLATFORM_ID",
    "OPENCODE_GO_PLATFORM_ID",
    "PYTHINKER_CODE_PLATFORM_ID",
]
```

If the existing file has additional content, preserve it.

- [ ] **Step 4: Implement constants and config helper**

Create `src/pythinker_code/auth/deepseek.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import SecretStr

from pythinker_code.auth import DEEPSEEK_PLATFORM_ID
from pythinker_code.config import Config, LLMModel, LLMProvider

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_PROVIDER_KEY = "managed:deepseek"
DEEPSEEK_DEFAULT_MODEL_ALIAS = "deepseek/v4-pro"


@dataclass(frozen=True, slots=True)
class DeepSeekModel:
    model_id: str
    alias_suffix: str
    display_name: str
    provider_key: str = DEEPSEEK_PROVIDER_KEY
    max_context_size: int = 128_000

    @property
    def alias(self) -> str:
        return f"{DEEPSEEK_PLATFORM_ID}/{self.alias_suffix}"


DEEPSEEK_MODELS: tuple[DeepSeekModel, ...] = (
    DeepSeekModel("deepseek-v4-pro", "v4-pro", "DeepSeek V4 Pro"),
    DeepSeekModel("deepseek-v4-flash", "v4-flash", "DeepSeek V4 Flash"),
)


def get_deepseek_api_key_from_env() -> str | None:
    value = os.getenv("DEEPSEEK_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


# Strict pyright reports this as unused until Task 2 adds an in-module caller
# (`login_deepseek_api_key`); the suppression is removed at that point.
def _apply_deepseek_config(  # pyright: ignore[reportUnusedFunction]
    config: Config,
    api_key: SecretStr,
    models: tuple[DeepSeekModel, ...] = DEEPSEEK_MODELS,
) -> None:
    config.providers[DEEPSEEK_PROVIDER_KEY] = LLMProvider(
        type="openai_legacy",
        base_url=DEEPSEEK_BASE_URL,
        api_key=api_key,
    )

    provider_keys = {DEEPSEEK_PROVIDER_KEY}
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
    if DEEPSEEK_DEFAULT_MODEL_ALIAS in config.models:
        config.default_model = DEEPSEEK_DEFAULT_MODEL_ALIAS
    else:
        config.default_model = fallback
    config.default_thinking = False
```

- [ ] **Step 5: Run tests + pyright**

Run: `uv run pytest tests/auth/test_deepseek_auth.py -v`

Expected: PASS for the three tests in this task.

Run: `uv run pyright src/pythinker_code/auth/deepseek.py tests/auth/test_deepseek_auth.py`

Expected: 0 errors / 0 warnings / 0 informations.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/auth/__init__.py src/pythinker_code/auth/deepseek.py tests/auth/test_deepseek_auth.py
git commit -m "feat(auth): add deepseek config helpers"
```

(No Co-Authored-By, no "Generated with Claude Code" — user's hard rule.)

## Task 2: Add Best-Effort Model Discovery And Login Events

**Files:**
- Modify: `src/pythinker_code/auth/deepseek.py`
- Test: `tests/auth/test_deepseek_auth.py`

- [ ] **Step 1: Add failing login tests**

Append to `tests/auth/test_deepseek_auth.py`:

```python
def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


@pytest.mark.asyncio
async def test_login_deepseek_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import login_deepseek_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "ds-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr("pythinker_code.auth.deepseek._discover_deepseek_models", fake_discover)

    events = [event async for event in login_deepseek_api_key(config, "ds-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "ds-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "deepseek/v4-pro"
    assert "deepseek/v4-flash" in config.models
    assert (tmp_path / "config.toml").exists()


@pytest.mark.asyncio
async def test_login_deepseek_falls_back_on_non_auth_response_error(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import login_deepseek_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.deepseek.com/v1/models"),
            (),
            status=503,
            message="Service Unavailable",
        )

    monkeypatch.setattr("pythinker_code.auth.deepseek._discover_deepseek_models", fake_discover)

    events = [event async for event in login_deepseek_api_key(config, "ds-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert config.default_model == "deepseek/v4-pro"


@pytest.mark.asyncio
async def test_login_deepseek_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import login_deepseek_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.deepseek.com/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr("pythinker_code.auth.deepseek._discover_deepseek_models", fake_discover)

    events = [event async for event in login_deepseek_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid DeepSeek API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_deepseek_uses_discovered_context_length(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import DeepSeekModel, login_deepseek_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            DeepSeekModel(
                model_id="deepseek-v4-pro",
                alias_suffix="v4-pro",
                display_name="DeepSeek V4 Pro",
                max_context_size=256_000,
            ),
        )

    monkeypatch.setattr("pythinker_code.auth.deepseek._discover_deepseek_models", fake_discover)

    events = [event async for event in login_deepseek_api_key(config, "ds-test")]

    assert events[-1].type == "success"
    assert config.models["deepseek/v4-pro"].max_context_size == 256_000


@pytest.mark.asyncio
async def test_login_deepseek_requires_key(tmp_path):
    from pythinker_code.auth.deepseek import login_deepseek_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_deepseek_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "DeepSeek API key is required."


@pytest.mark.parametrize(
    "payload, expected_aliases",
    [
        (None, set()),
        ({}, set()),
        ({"data": "not a list"}, set()),
        ({"data": [{"context_length": 1000}]}, set()),
        ({"data": [{"id": "unknown-model"}]}, set()),
        ({"data": [{"id": "deepseek-v4-pro"}]}, {"deepseek/v4-pro"}),
    ],
)
def test_parse_discovered_deepseek_models_handles_malformed_payloads(payload, expected_aliases):
    from pythinker_code.auth.deepseek import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert {m.alias for m in result} == expected_aliases


def test_parse_discovered_deepseek_models_overrides_context_length_only_for_positive_int():
    from pythinker_code.auth.deepseek import _parse_discovered_models

    payload = {
        "data": [
            {"id": "deepseek-v4-pro", "context_length": "bogus"},
            {"id": "deepseek-v4-flash", "context_length": -5},
        ]
    }
    result = _parse_discovered_models(payload)
    by_id = {m.model_id: m for m in result}
    assert by_id["deepseek-v4-pro"].max_context_size == 128_000
    assert by_id["deepseek-v4-flash"].max_context_size == 128_000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_deepseek_auth.py -v`

Expected: FAIL with `ImportError`/`AttributeError` for `login_deepseek_api_key` and `_discover_deepseek_models` and `_parse_discovered_models`.

- [ ] **Step 3: Implement discovery, parser, and login (and remove the pyright suppression)**

Update `src/pythinker_code/auth/deepseek.py` imports and append the new code. Replace the `# pyright: ignore[reportUnusedFunction]` directive (and its 2-line comment block) on `_apply_deepseek_config` because Task 2 adds an in-module caller.

Imports at top:

```python
from collections.abc import AsyncIterator
from typing import Any, cast

import aiohttp

from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import save_config
from pythinker_code.utils.aiohttp import new_client_session
```

Replace the `_apply_deepseek_config` definition: remove the comment block above it AND the `# pyright: ignore[reportUnusedFunction]` directive on the `def` line. The function body is unchanged.

Append below `_apply_deepseek_config`:

```python
def _model_by_id() -> dict[str, DeepSeekModel]:
    return {model.model_id: model for model in DEEPSEEK_MODELS}


def _parse_discovered_models(data: object) -> tuple[DeepSeekModel, ...]:
    if not isinstance(data, dict):
        return ()
    data = cast(dict[str, Any], data)
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        return ()

    known = _model_by_id()
    result: list[DeepSeekModel] = []
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
            DeepSeekModel(
                model_id=current.model_id,
                alias_suffix=current.alias_suffix,
                display_name=display_name,
                provider_key=current.provider_key,
                max_context_size=max_context_size,
            )
        )
    return tuple(result)


async def _discover_deepseek_models(api_key: str) -> tuple[DeepSeekModel, ...]:
    async with (
        new_client_session() as session,
        session.get(
            f"{DEEPSEEK_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            raise_for_status=True,
        ) as response,
    ):
        payload = await response.json(content_type=None)
    return _parse_discovered_models(payload)


async def login_deepseek_api_key(
    config: Config, api_key: str | None = None
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    resolved_key = (api_key or get_deepseek_api_key_from_env() or "").strip()
    if not resolved_key:
        yield OAuthEvent("error", "DeepSeek API key is required.")
        return

    models = DEEPSEEK_MODELS
    try:
        discovered = await _discover_deepseek_models(resolved_key)
        if discovered:
            models = discovered
    except aiohttp.ClientResponseError as exc:
        if exc.status in {401, 403}:
            yield OAuthEvent("error", "Invalid DeepSeek API key; the key was not saved.")
            return
        yield OAuthEvent(
            "info",
            "DeepSeek model listing is unavailable; using the built-in model list.",
        )
    except (aiohttp.ClientError, TimeoutError, ValueError):
        yield OAuthEvent(
            "info",
            "DeepSeek model listing is unavailable; using the built-in model list.",
        )

    _apply_deepseek_config(config, SecretStr(resolved_key), models=models)
    save_config(config)
    yield OAuthEvent("success", f"DeepSeek configured with model {config.default_model}.")
```

- [ ] **Step 4: Run tests and pyright**

Run: `uv run pytest tests/auth/test_deepseek_auth.py -v`

Expected: ALL pass (3 from Task 1 + 5 login tests + 7 parser cases = 15 collected by pytest, including parametrized cases).

Run: `uv run pyright src/pythinker_code/auth/deepseek.py tests/auth/test_deepseek_auth.py`

Expected: 0/0/0.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/deepseek.py tests/auth/test_deepseek_auth.py
git commit -m "feat(auth): add deepseek login flow"
```

## Task 3: Add DeepSeek Logout

**Files:**
- Modify: `src/pythinker_code/auth/deepseek.py`
- Test: `tests/auth/test_deepseek_auth.py`

- [ ] **Step 1: Add failing logout tests**

Append to `tests/auth/test_deepseek_auth.py`:

```python
@pytest.mark.asyncio
async def test_logout_deepseek_removes_only_deepseek(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import (
        DEEPSEEK_PROVIDER_KEY,
        _apply_deepseek_config,
        logout_deepseek,
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
    _apply_deepseek_config(config, SecretStr("ds-test"))

    events = [event async for event in logout_deepseek(config)]

    assert events[-1].type == "success"
    assert DEEPSEEK_PROVIDER_KEY not in config.providers
    assert "deepseek/v4-pro" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_deepseek_preserves_non_deepseek_default(monkeypatch, tmp_path):
    from pythinker_code.auth.deepseek import _apply_deepseek_config, logout_deepseek
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
    _apply_deepseek_config(config, SecretStr("ds-test"))
    config.default_model = "openai/gpt-5.2"

    events = [event async for event in logout_deepseek(config)]

    assert events[-1].type == "success"
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_deepseek_rejects_non_default_config_location():
    from pythinker_code.auth.deepseek import logout_deepseek

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_deepseek(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
    assert config.providers == {}
    assert config.models == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_deepseek_auth.py -v -k logout`

Expected: FAIL with `ImportError` for `logout_deepseek`.

- [ ] **Step 3: Implement logout**

Append to `src/pythinker_code/auth/deepseek.py`:

```python
async def logout_deepseek(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    provider_keys = {DEEPSEEK_PROVIDER_KEY}
    config.providers.pop(DEEPSEEK_PROVIDER_KEY, None)
    for key, model in list(config.models.items()):
        if model.provider in provider_keys:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of DeepSeek successfully.")
```

- [ ] **Step 4: Run auth tests + pyright**

Run: `uv run pytest tests/auth/test_deepseek_auth.py -v`

Expected: PASS (all prior + 3 new logout tests).

Run: `uv run pyright src/pythinker_code/auth/deepseek.py tests/auth/test_deepseek_auth.py`

Expected: 0/0/0.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/deepseek.py tests/auth/test_deepseek_auth.py
git commit -m "feat(auth): add deepseek logout"
```

## Task 4: Wire CLI Login And Logout Flags

**Files:**
- Modify: `src/pythinker_code/cli/__init__.py`
- Modify: `tests/cli/test_openai_login_cli.py`

- [ ] **Step 1: Inspect existing CLI patterns**

Read the current `login` and `logout` Typer commands in `src/pythinker_code/cli/__init__.py`. Note how `--minimax` and `--opencode-go` are wired (from prior features). The new `--deepseek` flag follows the same shape.

- [ ] **Step 2: Add failing CLI routing tests**

Append to `tests/cli/test_openai_login_cli.py`:

```python
def test_cli_login_deepseek_routes_to_deepseek(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.login_deepseek_api_key", login, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["login", "--deepseek"], input="ds-test\n")

    assert result.exit_code == 0
    assert login.call_args.args[1] == "ds-test"


def test_cli_login_rejects_deepseek_with_other_modes(monkeypatch):
    result = runner.invoke(cli, ["login", "--deepseek", "--api-key"])

    assert result.exit_code == 1
    assert "Choose only one" in result.output

    result_two = runner.invoke(cli, ["login", "--deepseek", "--minimax"])

    assert result_two.exit_code == 1
    assert "Choose only one" in result_two.output


def test_cli_logout_deepseek_routes_to_deepseek_logout(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.logout_deepseek", logout, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["logout", "--deepseek"])

    assert result.exit_code == 0
    assert logout.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -v -k deepseek`

Expected: FAIL because `--deepseek` does not exist.

- [ ] **Step 4: Import DeepSeek functions in CLI**

Add to `src/pythinker_code/cli/__init__.py`, alongside the existing `from pythinker_code.auth.minimax import ...`:

```python
from pythinker_code.auth.deepseek import login_deepseek_api_key, logout_deepseek
```

- [ ] **Step 5: Add `--deepseek` flag to `login` and route**

Add to the `login` command signature (placed after the `minimax` flag):

```python
    deepseek: bool = typer.Option(
        False, "--deepseek", help="Configure DeepSeek with an API key."
    ),
```

Update the docstring: `"""Login with OpenAI, OpenCode Go, MiniMax, or DeepSeek."""`.

Update the mode-conflict check to include the new flag:

```python
        selected_modes = sum(
            bool(value)
            for value in (browser, headless, api_key, opencode_go, minimax, deepseek)
        )
        if selected_modes > 1:
            typer.echo(
                "Choose only one of --browser, --headless, --api-key, --opencode-go, --minimax, or --deepseek.",
                err=True,
            )
            return False
```

Insert the DeepSeek branch BEFORE the existing `minimax` branch:

```python
        if deepseek:
            key = typer.prompt("DeepSeek API key", hide_input=True).strip()
            events = login_deepseek_api_key(config, key)
        elif minimax:
            ...  # existing MiniMax branch unchanged
```

- [ ] **Step 6: Add `--deepseek` flag to `logout` and route**

Add the flag (placed after the `minimax` flag):

```python
    deepseek: bool = typer.Option(False, "--deepseek", help="Logout from DeepSeek."),
```

Update the docstring: `"""Logout from OpenAI, OpenCode Go, MiniMax, or DeepSeek."""`.

Extend the mode-conflict and `events` selection. Replace the existing block:

```python
        if minimax and opencode_go:
            typer.echo(
                "Choose only one of --opencode-go or --minimax.",
                err=True,
            )
            return False

        config = load_config()
        if minimax:
            events = logout_minimax(config)
        elif opencode_go:
            events = logout_opencode_go(config)
        else:
            events = logout_openai(config)
```

with:

```python
        if sum(bool(v) for v in (opencode_go, minimax, deepseek)) > 1:
            typer.echo(
                "Choose only one of --opencode-go, --minimax, or --deepseek.",
                err=True,
            )
            return False

        config = load_config()
        if deepseek:
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
git commit -m "feat(cli): route deepseek auth commands"
```

## Task 5: Wire Shell Login And Logout Commands

**Files:**
- Modify: `src/pythinker_code/ui/shell/oauth.py`
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`

- [ ] **Step 1: Inspect existing shell patterns**

Read `src/pythinker_code/ui/shell/oauth.py`. Note that `_prompt_api_key(label)` already exists, `_LOGIN_PROVIDER_OPTIONS` is the chooser source, and the `MINIMAX_PLATFORM_ID` / `OPENCODE_GO_PLATFORM_ID` constants are imported from `pythinker_code.auth`. Reuse these — do not add a new prompt helper.

- [ ] **Step 2: Add failing shell route tests**

Append to `tests/ui_and_conv/test_openai_shell_login.py`:

```python
@pytest.mark.asyncio
async def test_shell_login_deepseek_routes_to_deepseek(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "login_deepseek_api_key", login, raising=False)
    monkeypatch.setattr(
        shell_oauth, "_prompt_api_key", lambda label: _async_value("ds-test")
    )

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.login)(_app(), "deepseek")

    assert login.call_args.args[1] == "ds-test"


@pytest.mark.asyncio
async def test_shell_logout_deepseek_routes_to_deepseek(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "logout_deepseek", logout, raising=False)

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.logout)(_app(), "deepseek")

    assert logout.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v -k deepseek`

Expected: FAIL because shell routes do not yet recognize `deepseek`.

- [ ] **Step 4: Import DeepSeek functions and platform ID**

Modify `src/pythinker_code/ui/shell/oauth.py`. Update the existing `from pythinker_code.auth import ...` line to include `DEEPSEEK_PLATFORM_ID`:

```python
from pythinker_code.auth import (
    DEEPSEEK_PLATFORM_ID,
    MINIMAX_PLATFORM_ID,
    OPENCODE_GO_PLATFORM_ID,
)
```

Add a new import block alongside the existing minimax/opencode-go ones:

```python
from pythinker_code.auth.deepseek import (
    login_deepseek_api_key,
    logout_deepseek,
)
```

- [ ] **Step 5: Append DeepSeek to the chooser**

Locate `_LOGIN_PROVIDER_OPTIONS` and append a new tuple entry:

```python
_LOGIN_PROVIDER_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("1", "browser", "OpenAI ChatGPT (browser)"),
    ("2", "headless", "OpenAI ChatGPT (device code)"),
    ("3", "api-key", "OpenAI API key"),
    ("4", "opencode-go", "OpenCode Go"),
    ("5", "minimax", "MiniMax"),
    ("6", "deepseek", "DeepSeek"),
)
```

Update the prompt prompt string in `_prompt_login_provider` to read `[1-6]` in both the prompt label and the default-fallback comment:

```python
        choice = await session.prompt_async(" Enter [1-6] (default 1): ")
```

- [ ] **Step 6: Add `/login deepseek` route**

Locate the `/login` mode dispatch chain. Insert a DeepSeek branch BEFORE the existing `minimax` branch (so the visible chain reads `deepseek → minimax → opencode-go → api-key → headless → default browser`):

```python
    elif mode == "deepseek":
        api_key = await _prompt_api_key("DeepSeek")
        if not api_key:
            console.print("[red]No DeepSeek API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_deepseek_api_key(soul.runtime.config, api_key))
        provider = DEEPSEEK_PLATFORM_ID
```

Update the unknown-mode usage error to include the new mode:

```python
        console.print(
            "[red]Usage: /login [browser|headless|api-key|opencode-go|minimax|deepseek][/red]"
        )
```

- [ ] **Step 7: Add `/logout deepseek` route**

Modify `logout` in `src/pythinker_code/ui/shell/oauth.py`:

```python
    mode = args.strip().lower()
    if mode == "deepseek":
        ok = await _render_oauth_events(logout_deepseek(config))
    elif mode == "minimax":
        ok = await _render_oauth_events(logout_minimax(config))
    elif mode in ("opencode-go", "opencode", "go"):
        ok = await _render_oauth_events(logout_opencode_go(config))
    elif mode == "":
        ok = await _render_oauth_events(logout_openai(config))
    else:
        console.print("[red]Usage: /logout [opencode-go|minimax|deepseek][/red]")
        return
```

- [ ] **Step 8: Update docstrings**

Update the `login` and `logout` docstrings to mention DeepSeek:

```python
"""Login with OpenAI, OpenCode Go, MiniMax, or DeepSeek."""
"""Logout from OpenAI, OpenCode Go, MiniMax, or DeepSeek."""
```

- [ ] **Step 9: Run shell tests + pyright**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v`

Expected: PASS (all existing + 2 new).

Run: `uv run pyright src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py`

Expected: 0/0/0.

- [ ] **Step 10: Commit**

```bash
git add src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py
git commit -m "feat(shell): route deepseek auth commands"
```

## Task 6: Final Quality Checks

**Files:**
- Verify all touched files; commit only if quality gates mutate files.

- [ ] **Step 1: Run formatting**

Run: `cd /home/ai/Projects/pythinker-code-main && make format`

Expected: exit 0. If files are modified, stage them for the optional final commit (Step 5).

- [ ] **Step 2: Run project checks**

Run: `cd /home/ai/Projects/pythinker-code-main && make check`

Expected: exit 0. Note any pre-existing non-blocking warnings in unrelated files (these are out of scope).

- [ ] **Step 3: Run focused DeepSeek + integration test suite**

Run:

```bash
uv run pytest tests/auth/test_deepseek_auth.py \
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

If `make format` or `make check` modified any files, stage and commit:

```bash
git add <files-listed-by-status>
git commit -m "chore: finalize deepseek auth checks"
```

If nothing changed, do NOT create an empty commit.

## Self-Review Notes

- **Spec coverage:** The plan covers dedicated CLI/shell login, env-key resolution, single-provider config (`openai_legacy` only — Anthropic-compat endpoint intentionally skipped), all four current alias mappings (V4-Pro and V4-Flash), best-effort discovery, auth-failure handling, secret redaction, logout, chooser update, and tests with mocked network calls. Provider construction (`openai_legacy` at custom base URL) is pre-verified by OpenCode Go's Task 6 — no new provider-construction test required.
- **Scope control:** The plan excludes legacy DeepSeek aliases (`deepseek-chat`, `deepseek-reasoner`), DeepSeek's Anthropic-compat endpoint, and any non-text DeepSeek models.
- **Type consistency:** Provider key is `managed:deepseek` everywhere. Model alias format is `deepseek/<suffix>`. API model IDs are lowercase (`deepseek-v4-pro`). `DEEPSEEK_PLATFORM_ID = "deepseek"`. `OAuthEvent` is constructed positionally throughout. API keys use `SecretStr` in config writes.
- **Implementation risk:** Low. DeepSeek's API is OpenAI-compatible and the Pythinker `openai_legacy` provider type is already wired.
