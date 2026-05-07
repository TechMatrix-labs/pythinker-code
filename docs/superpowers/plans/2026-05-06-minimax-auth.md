# MiniMax Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated MiniMax setup/logout path and configure the four current MiniMax M2.5/M2.7 text models in Pythinker Code, with Token Plan key-prefix awareness.

**Architecture:** Add a focused `pythinker_code.auth.minimax` module that owns MiniMax constants, model metadata, env-key resolution, best-effort model discovery, login events (including Token Plan info event), and logout events. Reuse the existing `anthropic` provider type at `https://api.minimax.io/anthropic` (single managed provider, no split). Wire the module into existing `pythinker login`, `/login`, `pythinker logout`, and `/logout` routing without changing any current behavior.

**Tech Stack:** Python 3.12+, Typer, pytest, pytest-asyncio, pydantic `SecretStr`, aiohttp, existing `OAuthEvent`, `Config`, `LLMProvider`, `LLMModel`, `save_config`, and the `_prompt_api_key` shell helper introduced for OpenCode Go.

---

## File Structure

- Create: `src/pythinker_code/auth/minimax.py`
  - Owns MiniMax constants, model metadata, env-key resolution, discovery, config application, login (with Token Plan detection), and logout.
- Modify: `src/pythinker_code/auth/__init__.py`
  - Exports `MINIMAX_PLATFORM_ID`.
- Modify: `src/pythinker_code/cli/__init__.py`
  - Adds `--minimax` login/logout flags and routes to the new auth functions.
- Modify: `src/pythinker_code/ui/shell/oauth.py`
  - Adds `/login minimax`, `/logout minimax` routes; reuses existing `_prompt_api_key("MiniMax")`.
- Create: `tests/auth/test_minimax_auth.py`
  - Covers model constants, env resolution, config writes, discovery fallback, auth failures, secret redaction, Token Plan detection, and logout.
- Modify: `tests/cli/test_openai_login_cli.py`
  - Adds CLI route tests for MiniMax login/logout and mode conflict handling.
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`
  - Adds shell route tests for `/login minimax` and `/logout minimax`.

## Task 1: Add MiniMax Constants And Config Helpers

**Files:**
- Create: `src/pythinker_code/auth/minimax.py`
- Modify: `src/pythinker_code/auth/__init__.py`
- Test: `tests/auth/test_minimax_auth.py`

- [ ] **Step 1: Write failing tests for metadata, env resolution, and config writes**

Create `tests/auth/test_minimax_auth.py`:

```python
from __future__ import annotations

from pydantic import SecretStr

from pythinker_code.config import Config


def test_minimax_model_catalog_contains_four_current_models():
    from pythinker_code.auth.minimax import MINIMAX_MODELS

    aliases = {model.alias for model in MINIMAX_MODELS}
    assert aliases == {
        "minimax/m2.7",
        "minimax/m2.7-highspeed",
        "minimax/m2.5",
        "minimax/m2.5-highspeed",
    }

    api_ids = {m.alias: m.model_id for m in MINIMAX_MODELS}
    assert api_ids == {
        "minimax/m2.7": "MiniMax-M2.7",
        "minimax/m2.7-highspeed": "MiniMax-M2.7-highspeed",
        "minimax/m2.5": "MiniMax-M2.5",
        "minimax/m2.5-highspeed": "MiniMax-M2.5-highspeed",
    }

    assert all(
        m.provider_key == "managed:minimax-anthropic" for m in MINIMAX_MODELS
    )


def test_minimax_env_key_uses_minimax_api_key(monkeypatch):
    from pythinker_code.auth.minimax import get_minimax_api_key_from_env

    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    assert get_minimax_api_key_from_env() is None

    monkeypatch.setenv("MINIMAX_API_KEY", "  mx-key  ")
    assert get_minimax_api_key_from_env() == "mx-key"

    monkeypatch.setenv("MINIMAX_API_KEY", "")
    assert get_minimax_api_key_from_env() is None


def test_apply_minimax_config_writes_provider_and_default():
    from pythinker_code.auth.minimax import (
        MINIMAX_ANTHROPIC_BASE_URL,
        MINIMAX_ANTHROPIC_PROVIDER_KEY,
        _apply_minimax_config,
    )

    config = Config(is_from_default_location=True)

    _apply_minimax_config(config, SecretStr("mx-test"))

    assert set(config.providers) == {MINIMAX_ANTHROPIC_PROVIDER_KEY}
    provider = config.providers[MINIMAX_ANTHROPIC_PROVIDER_KEY]
    assert provider.type == "anthropic"
    assert provider.base_url == MINIMAX_ANTHROPIC_BASE_URL
    assert provider.api_key.get_secret_value() == "mx-test"
    assert config.models["minimax/m2.7"].provider == MINIMAX_ANTHROPIC_PROVIDER_KEY
    assert config.models["minimax/m2.7"].model == "MiniMax-M2.7"
    assert config.default_model == "minimax/m2.7"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_minimax_auth.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'pythinker_code.auth.minimax'`.

- [ ] **Step 3: Export the platform ID**

Modify `src/pythinker_code/auth/__init__.py`. Inspect the current file before editing — it already exports `PYTHINKER_CODE_PLATFORM_ID`, `OPENAI_API_PLATFORM_ID`, `OPENAI_CHATGPT_PLATFORM_ID`, `OPENCODE_GO_PLATFORM_ID`. Add `MINIMAX_PLATFORM_ID` alongside, and include it in `__all__`:

```python
PYTHINKER_CODE_PLATFORM_ID = "pythinker-code"
OPENAI_API_PLATFORM_ID = "openai"
OPENAI_CHATGPT_PLATFORM_ID = "openai-chatgpt"
OPENCODE_GO_PLATFORM_ID = "opencode-go"
MINIMAX_PLATFORM_ID = "minimax"

__all__ = [
    "MINIMAX_PLATFORM_ID",
    "OPENAI_API_PLATFORM_ID",
    "OPENAI_CHATGPT_PLATFORM_ID",
    "OPENCODE_GO_PLATFORM_ID",
    "PYTHINKER_CODE_PLATFORM_ID",
]
```

If the existing file has additional content beyond platform IDs and `__all__`, preserve it.

- [ ] **Step 4: Implement constants and config helper**

Create `src/pythinker_code/auth/minimax.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import SecretStr

from pythinker_code.auth import MINIMAX_PLATFORM_ID
from pythinker_code.config import Config, LLMModel, LLMProvider

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


# Strict pyright reports this as unused until later steps add the in-module
# caller (`login_minimax_api_key`); the suppression is removed in Step 4 of
# Task 2.
def _apply_minimax_config(  # pyright: ignore[reportUnusedFunction]
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

    fallback = next((m.alias for m in models), next(iter(config.models), ""))
    if MINIMAX_DEFAULT_MODEL_ALIAS in config.models:
        config.default_model = MINIMAX_DEFAULT_MODEL_ALIAS
    else:
        config.default_model = fallback
    config.default_thinking = False
```

NOTE: Verify `LLMModel` and `LLMProvider` field names match the actual `Config` definitions in `src/pythinker_code/config.py`. The OpenCode Go module already uses `provider`, `model`, `max_context_size`, `display_name` for `LLMModel` and `type`, `base_url`, `api_key` for `LLMProvider` — match those exactly. If a field name differs in your codebase, adapt while keeping the test assertions satisfiable.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_minimax_auth.py -v`

Expected: PASS for all three tests.

Run: `uv run pyright src/pythinker_code/auth/minimax.py tests/auth/test_minimax_auth.py`

Expected: 0 errors / 0 warnings / 0 informations.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/auth/__init__.py src/pythinker_code/auth/minimax.py tests/auth/test_minimax_auth.py
git commit -m "feat(auth): add minimax config helpers"
```

(No Co-Authored-By trailer. No "Generated with Claude Code" footer.)

## Task 2: Add Best-Effort Model Discovery, Login Events, And Token Plan Awareness

**Files:**
- Modify: `src/pythinker_code/auth/minimax.py`
- Test: `tests/auth/test_minimax_auth.py`

- [ ] **Step 1: Add failing tests for login success, auth failure, fallback, redaction, and Token Plan detection**

Append to `tests/auth/test_minimax_auth.py`:

```python
import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL


def _request_info(url: str) -> aiohttp.RequestInfo:
    return aiohttp.RequestInfo(
        url=URL(url),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL(url),
    )


@pytest.mark.asyncio
async def test_login_minimax_saves_static_models_when_discovery_fails(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        assert api_key == "mx-test"
        raise aiohttp.ClientConnectionError("models unavailable")

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "mx-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert "mx-test" not in "\n".join(event.json for event in events)
    assert config.default_model == "minimax/m2.7"
    assert "minimax/m2.5-highspeed" in config.models
    assert (tmp_path / "config.toml").exists()


@pytest.mark.asyncio
async def test_login_minimax_falls_back_on_non_auth_response_error(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.minimax.io/v1/models"),
            (),
            status=503,
            message="Service Unavailable",
        )

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "mx-test")]

    assert [event.type for event in events] == ["info", "success"]
    assert config.default_model == "minimax/m2.7"


@pytest.mark.asyncio
async def test_login_minimax_rejects_401(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        raise aiohttp.ClientResponseError(
            _request_info("https://api.minimax.io/v1/models"),
            (),
            status=401,
            message="Unauthorized",
        )

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "bad-key")]

    assert events[-1].type == "error"
    assert "Invalid MiniMax API key" in events[-1].message
    assert config.providers == {}
    assert config.models == {}


@pytest.mark.asyncio
async def test_login_minimax_uses_discovered_context_length(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import MiniMaxModel, login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return (
            MiniMaxModel(
                model_id="MiniMax-M2.7",
                alias_suffix="m2.7",
                display_name="MiniMax M2.7",
                max_context_size=512_000,
            ),
        )

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "mx-test")]

    assert events[-1].type == "success"
    assert config.models["minimax/m2.7"].max_context_size == 512_000


@pytest.mark.asyncio
async def test_login_minimax_requires_key(tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    config = Config(is_from_default_location=True)

    events = [event async for event in login_minimax_api_key(config, "")]

    assert events[-1].type == "error"
    assert events[-1].message == "MiniMax API key is required."


@pytest.mark.asyncio
async def test_login_minimax_emits_token_plan_event_for_sk_cp_prefix(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return ()

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "sk-cp-token-plan-abc")]

    types = [event.type for event in events]
    assert types[0] == "info"
    assert "Token Plan" in events[0].message
    assert types[-1] == "success"
    # Secret never appears in any event message or JSON.
    assert "sk-cp-token-plan-abc" not in "\n".join(event.json for event in events)


@pytest.mark.asyncio
async def test_login_minimax_does_not_emit_token_plan_event_for_pay_as_you_go(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import login_minimax_api_key

    monkeypatch.setenv("PYTHINKER_SHARE_DIR", str(tmp_path))
    config = Config(is_from_default_location=True)

    async def fake_discover(api_key):
        return ()

    monkeypatch.setattr("pythinker_code.auth.minimax._discover_minimax_models", fake_discover)

    events = [event async for event in login_minimax_api_key(config, "sk-paygo-key")]

    types = [event.type for event in events]
    assert types == ["success"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_minimax_auth.py -v`

Expected: FAIL with `ImportError` / `AttributeError` for `login_minimax_api_key` and `_discover_minimax_models`.

- [ ] **Step 3: Implement discovery, parser, and login**

Append (and update imports for) `src/pythinker_code/auth/minimax.py`:

```python
from collections.abc import AsyncIterator
from typing import Any, cast

import aiohttp

from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.config import save_config
from pythinker_code.utils.aiohttp import new_client_session


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
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item = cast(dict[str, Any], item)
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
```

NOTE: Verify `OAuthEvent`'s constructor accepts positional args `OAuthEvent("info", "...")` and exposes `.type`, `.message`, and `.json` (string). The OpenCode Go module already uses this shape; mirror it.

- [ ] **Step 4: REMOVE the now-stale pyright suppression**

`login_minimax_api_key` now calls `_apply_minimax_config(config, SecretStr(resolved_key), models=models)` in-module, so pyright no longer reports the helper as unused. Remove BOTH:

- The `# pyright: ignore[reportUnusedFunction]` directive on the `def _apply_minimax_config(...)` line.
- The two-line explanatory comment block immediately above it.

Verify: `uv run pyright src/pythinker_code/auth/minimax.py` → 0/0/0.

- [ ] **Step 5: Add unit tests for `_parse_discovered_models`**

Append to `tests/auth/test_minimax_auth.py`:

```python
@pytest.mark.parametrize(
    "payload, expected_aliases",
    [
        (None, set()),
        ({}, set()),
        ({"data": "not a list"}, set()),
        ({"data": [{"context_length": 1000}]}, set()),  # missing id
        ({"data": [{"id": "unknown-model"}]}, set()),  # unknown id dropped
        ({"data": [{"id": "MiniMax-M2.7"}]}, {"minimax/m2.7"}),
    ],
)
def test_parse_discovered_minimax_models_handles_malformed_payloads(payload, expected_aliases):
    from pythinker_code.auth.minimax import _parse_discovered_models

    result = _parse_discovered_models(payload)
    assert {m.alias for m in result} == expected_aliases


def test_parse_discovered_minimax_models_overrides_context_length_only_for_positive_int():
    from pythinker_code.auth.minimax import _parse_discovered_models

    payload = {
        "data": [
            {"id": "MiniMax-M2.7", "context_length": "bogus"},
            {"id": "MiniMax-M2.5", "context_length": -5},
            {"id": "MiniMax-M2.5-highspeed", "context_length": 384_000},
        ]
    }
    result = _parse_discovered_models(payload)
    by_id = {m.model_id: m for m in result}
    assert by_id["MiniMax-M2.7"].max_context_size == 192_000
    assert by_id["MiniMax-M2.5"].max_context_size == 192_000
    assert by_id["MiniMax-M2.5-highspeed"].max_context_size == 384_000
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_minimax_auth.py -v`

Expected: PASS (3 from Task 1 + 7 new login/Token Plan tests + 7 parser cases = 17 collected). All pass.

Run: `uv run pyright src/pythinker_code/auth/minimax.py tests/auth/test_minimax_auth.py`

Expected: 0/0/0.

- [ ] **Step 7: Commit**

```bash
git add src/pythinker_code/auth/minimax.py tests/auth/test_minimax_auth.py
git commit -m "feat(auth): add minimax login flow with token plan awareness"
```

## Task 3: Add MiniMax Logout

**Files:**
- Modify: `src/pythinker_code/auth/minimax.py`
- Test: `tests/auth/test_minimax_auth.py`

- [ ] **Step 1: Add failing logout tests**

Append to `tests/auth/test_minimax_auth.py`:

```python
@pytest.mark.asyncio
async def test_logout_minimax_removes_only_minimax(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import (
        MINIMAX_ANTHROPIC_PROVIDER_KEY,
        _apply_minimax_config,
        logout_minimax,
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
    _apply_minimax_config(config, SecretStr("mx-test"))

    events = [event async for event in logout_minimax(config)]

    assert events[-1].type == "success"
    assert MINIMAX_ANTHROPIC_PROVIDER_KEY not in config.providers
    assert "minimax/m2.7" not in config.models
    assert "managed:openai" in config.providers
    assert "openai/gpt-5.2" in config.models
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_minimax_preserves_non_minimax_default(monkeypatch, tmp_path):
    from pythinker_code.auth.minimax import _apply_minimax_config, logout_minimax
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
    _apply_minimax_config(config, SecretStr("mx-test"))
    config.default_model = "openai/gpt-5.2"

    events = [event async for event in logout_minimax(config)]

    assert events[-1].type == "success"
    assert config.default_model == "openai/gpt-5.2"


@pytest.mark.asyncio
async def test_logout_minimax_rejects_non_default_config_location():
    from pythinker_code.auth.minimax import logout_minimax

    config = Config(is_from_default_location=False)

    events = [event async for event in logout_minimax(config)]

    assert events[-1].type == "error"
    assert "default config file" in events[-1].message
    assert config.providers == {}
    assert config.models == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_minimax_auth.py -v -k logout`

Expected: FAIL with `ImportError` for `logout_minimax`.

- [ ] **Step 3: Implement logout**

Append to `src/pythinker_code/auth/minimax.py`:

```python
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
```

- [ ] **Step 4: Run auth tests**

Run: `uv run pytest tests/auth/test_minimax_auth.py -v`

Expected: PASS (all prior + 3 new logout tests).

Run: `uv run pyright src/pythinker_code/auth/minimax.py tests/auth/test_minimax_auth.py`

Expected: 0/0/0.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/minimax.py tests/auth/test_minimax_auth.py
git commit -m "feat(auth): add minimax logout"
```

## Task 4: Wire CLI Login And Logout Flags

**Files:**
- Modify: `src/pythinker_code/cli/__init__.py`
- Modify: `tests/cli/test_openai_login_cli.py`

- [ ] **Step 1: Inspect existing CLI patterns**

Read the current `login` and `logout` Typer commands in `src/pythinker_code/cli/__init__.py`. Note how `--opencode-go` is wired (added in the previous feature). The new `--minimax` flag follows the same shape.

- [ ] **Step 2: Add failing CLI routing tests**

Append to `tests/cli/test_openai_login_cli.py`:

```python
def test_cli_login_minimax_routes_to_minimax(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.login_minimax_api_key", login, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["login", "--minimax"], input="mx-test\n")

    assert result.exit_code == 0
    assert login.call_args.args[1] == "mx-test"


def test_cli_login_rejects_minimax_with_other_modes(monkeypatch):
    result = runner.invoke(cli, ["login", "--minimax", "--api-key"])

    assert result.exit_code == 1
    assert "Choose only one" in result.output

    result_two = runner.invoke(cli, ["login", "--minimax", "--opencode-go"])

    assert result_two.exit_code == 1
    assert "Choose only one" in result_two.output


def test_cli_logout_minimax_routes_to_minimax_logout(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr("pythinker_code.cli.logout_minimax", logout, raising=False)
    monkeypatch.setattr(
        "pythinker_code.cli.load_config",
        lambda: Config(is_from_default_location=True),
        raising=False,
    )

    result = runner.invoke(cli, ["logout", "--minimax"])

    assert result.exit_code == 0
    assert logout.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -v -k minimax`

Expected: FAIL because `--minimax` does not exist on the CLI commands.

- [ ] **Step 4: Import MiniMax functions in CLI**

Add to `src/pythinker_code/cli/__init__.py`, alongside the existing `from pythinker_code.auth.opencode_go import ...` line:

```python
from pythinker_code.auth.minimax import login_minimax_api_key, logout_minimax
```

- [ ] **Step 5: Add `--minimax` flag to `login` and route**

Add the flag to the `login` command signature (placed after the `opencode_go` flag added in the prior feature):

```python
    minimax: bool = typer.Option(
        False, "--minimax", help="Configure MiniMax with an API key."
    ),
```

Update the docstring to mention MiniMax: `"""Login with OpenAI, OpenCode Go, or MiniMax."""`.

Update the mode-conflict check to include the new flag. The current implementation counts four booleans; expand to five:

```python
        selected_modes = sum(
            bool(value)
            for value in (browser, headless, api_key, opencode_go, minimax)
        )
        if selected_modes > 1:
            typer.echo(
                "Choose only one of --browser, --headless, --api-key, --opencode-go, or --minimax.",
                err=True,
            )
            return False  # match existing return/exit pattern
```

Insert the MiniMax branch BEFORE the existing `opencode_go` branch (so the chain reads `minimax → opencode_go → api_key → headless → default browser`):

```python
        if minimax:
            key = typer.prompt("MiniMax API key", hide_input=True).strip()
            events = login_minimax_api_key(config, key)
        elif opencode_go:
            ...  # existing OpenCode Go branch unchanged
```

- [ ] **Step 6: Add `--minimax` flag to `logout` and route**

Add the flag to the `logout` command:

```python
    minimax: bool = typer.Option(
        False, "--minimax", help="Logout from MiniMax."
    ),
```

Update the docstring: `"""Logout from OpenAI, OpenCode Go, or MiniMax."""`.

Inside `_run`, change the `events` selection. The current code is:

```python
        events = logout_opencode_go(config) if opencode_go else logout_openai(config)
```

Replace with an explicit chain that gives MiniMax precedence over the existing flags:

```python
        if minimax:
            events = logout_minimax(config)
        elif opencode_go:
            events = logout_opencode_go(config)
        else:
            events = logout_openai(config)
```

Both JSON and console output branches consume the single `events` value (no double iteration).

Mode-conflict for logout: if both `--minimax` and `--opencode-go` are passed, exit 1 with a clear message. The existing logout handler does not have a mode-conflict check; add this check before computing `events`:

```python
        if minimax and opencode_go:
            typer.echo(
                "Choose only one of --opencode-go or --minimax.",
                err=True,
            )
            return False  # match existing exit-on-mode-conflict pattern
```

If the surrounding logout handler does not currently use `return False` (e.g., it uses `raise typer.Exit(code=1)` instead), match the existing exit style. Run the new test `test_cli_logout_minimax_routes_to_minimax_logout` to confirm the routing still works after the edit.

- [ ] **Step 7: Run CLI tests**

Run: `uv run pytest tests/cli/test_openai_login_cli.py -v`

Expected: PASS (all existing + 3 new). Pyright: `uv run pyright src/pythinker_code/cli/__init__.py tests/cli/test_openai_login_cli.py` → 0/0/0.

- [ ] **Step 8: Commit**

```bash
git add src/pythinker_code/cli/__init__.py tests/cli/test_openai_login_cli.py
git commit -m "feat(cli): route minimax auth commands"
```

## Task 5: Wire Shell Login And Logout Commands

**Files:**
- Modify: `src/pythinker_code/ui/shell/oauth.py`
- Modify: `tests/ui_and_conv/test_openai_shell_login.py`

- [ ] **Step 1: Inspect existing shell patterns**

Read `src/pythinker_code/ui/shell/oauth.py`. Note that the shared `_prompt_api_key(label)` helper already exists (extracted during the OpenCode Go feature) and the `MINIMAX_PLATFORM_ID` constant is exported from `pythinker_code.auth`. Reuse both — do not add a new prompt helper.

- [ ] **Step 2: Add failing shell route tests**

Append to `tests/ui_and_conv/test_openai_shell_login.py`:

```python
@pytest.mark.asyncio
async def test_shell_login_minimax_routes_to_minimax(monkeypatch):
    login = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "login_minimax_api_key", login, raising=False)
    monkeypatch.setattr(
        shell_oauth,
        "_prompt_api_key",
        lambda label: _async_value("mx-test"),
    )

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.login)(_app(), "minimax")

    assert login.call_args.args[1] == "mx-test"


@pytest.mark.asyncio
async def test_shell_logout_minimax_routes_to_minimax(monkeypatch):
    logout = Mock(side_effect=_success_event)
    monkeypatch.setattr(shell_oauth, "logout_minimax", logout, raising=False)

    with pytest.raises(Reload):
        await cast(Any, shell_oauth.logout)(_app(), "minimax")

    assert logout.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v -k minimax`

Expected: FAIL because shell routes do not yet recognize `minimax`.

- [ ] **Step 4: Import MiniMax functions and platform ID**

Add to `src/pythinker_code/ui/shell/oauth.py`, near the existing `from pythinker_code.auth.opencode_go import ...` line:

```python
from pythinker_code.auth import MINIMAX_PLATFORM_ID
from pythinker_code.auth.minimax import login_minimax_api_key, logout_minimax
```

If the module already imports `OPENCODE_GO_PLATFORM_ID` from `pythinker_code.auth`, fold `MINIMAX_PLATFORM_ID` into the same import line.

- [ ] **Step 5: Add `/login minimax` route**

Locate the `/login` mode dispatch chain. Insert a MiniMax branch BEFORE the existing OpenCode Go branch, mirroring the OpenCode Go shape:

```python
    elif mode == "minimax":
        api_key = await _prompt_api_key("MiniMax")
        if not api_key:
            console.print("[red]No MiniMax API key entered.[/red]")
            return
        ok = await _render_oauth_events(login_minimax_api_key(soul.runtime.config, api_key))
        provider = MINIMAX_PLATFORM_ID
```

Update the unknown-mode usage error to include the new mode:

```python
        console.print(
            "[red]Usage: /login [browser|headless|api-key|opencode-go|minimax][/red]"
        )
```

- [ ] **Step 6: Add `/logout minimax` route**

In the `/logout` handler, extend the dispatch on `args.strip().lower()`:

```python
    mode = args.strip().lower()
    if mode == "minimax":
        ok = await _render_oauth_events(logout_minimax(config))
    elif mode in ("opencode-go", "opencode", "go"):
        ok = await _render_oauth_events(logout_opencode_go(config))
    elif mode == "":
        ok = await _render_oauth_events(logout_openai(config))
    else:
        console.print("[red]Usage: /logout [opencode-go|minimax][/red]")
        return
```

- [ ] **Step 7: Update docstrings**

Update the `login` and `logout` docstrings to mention MiniMax:

```python
"""Login with OpenAI, OpenCode Go, or MiniMax."""
"""Logout from OpenAI, OpenCode Go, or MiniMax."""
```

(Match the wording the CLI commands use.)

- [ ] **Step 8: Run shell tests**

Run: `uv run pytest tests/ui_and_conv/test_openai_shell_login.py -v`

Expected: PASS (all existing + 2 new).

Run: `uv run pyright src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py` → 0/0/0.

- [ ] **Step 9: Commit**

```bash
git add src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/test_openai_shell_login.py
git commit -m "feat(shell): route minimax auth commands"
```

## Task 6: Final Quality Checks

**Files:**
- Verify all touched files; commit only if quality gates mutate files.

- [ ] **Step 1: Run formatting**

Run: `cd /home/ai/Projects/pythinker-code-main && make format`

Expected: exit 0. If files are modified, stage them for the optional final commit (Step 5).

- [ ] **Step 2: Run project checks**

Run: `cd /home/ai/Projects/pythinker-code-main && make check`

Expected: exit 0. Note any pre-existing non-blocking warnings in unrelated files (these are out of scope and were also present after the OpenCode Go feature).

- [ ] **Step 3: Run focused MiniMax test suite**

Run:

```bash
uv run pytest tests/auth/test_minimax_auth.py \
  tests/cli/test_openai_login_cli.py \
  tests/ui_and_conv/test_openai_shell_login.py -v
```

Expected: ALL pass.

- [ ] **Step 4: Inspect end-to-end diff**

Run: `git diff --stat <pre-feature-SHA>..HEAD` (use the commit immediately before Task 1's commit).

Expected: diff contains only the eight files listed under "File Structure" plus this plan + spec doc. No drive-by changes.

Run: `git log --format='%H %s%n%b%n---' <pre-feature-SHA>..HEAD`

Expected: every commit body is empty (subject only). NO Co-Authored-By trailer. NO "Generated with Claude Code" footer.

- [ ] **Step 5: Final commit (only if Step 1 or Step 2 mutated files)**

If `make format` or `make check` modified any files, stage and commit:

```bash
git add <files-listed-by-status>
git commit -m "chore: finalize minimax auth checks"
```

If nothing changed, do NOT create an empty commit. Per the OpenCode Go precedent: "Only create this commit if quality checks changed files that were not already committed."

## Self-Review Notes

- **Spec coverage:** The plan covers dedicated CLI/shell login, env-key resolution, single-provider config (Anthropic-compatible only per "clean UI" choice), all four current models (M2.5/M2.7 standard + highspeed), best-effort discovery, auth-failure handling, secret redaction, Token Plan key-prefix detection with informational event, logout, and tests with mocked network calls. Provider construction (`anthropic` type at custom base URL) is pre-verified by the OpenCode Go work — no additional provider-construction test required.
- **Scope control:** The plan excludes legacy MiniMax models (M2.1, M2, M2-her), non-text MiniMax models (speech, image, video, music), the OpenAI-compatible MiniMax provider, Token Plan quota tracking, and any external CLI integration.
- **Type consistency:** Provider key is `managed:minimax-anthropic` everywhere. Model alias format is `minimax/<suffix>`. API model IDs are CamelCase (`MiniMax-M2.7`). `MINIMAX_PLATFORM_ID = "minimax"`. `MINIMAX_TOKEN_PLAN_KEY_PREFIX = "sk-cp-"`. `OAuthEvent` is constructed positionally throughout. API keys use `SecretStr` in config writes.
- **Implementation risk:** MiniMax compatibility with the `anthropic` provider type is already proven by `tests/core/test_openai_provider.py::test_create_llm_supports_opencode_go_anthropic_provider` (the test verifies `anthropic` provider type at an arbitrary base URL — `https://api.minimax.io/anthropic` is exercised by the same code path). If a real MiniMax call ever fails at runtime due to a wire-format incompatibility specific to MiniMax's `/anthropic` endpoint, that is a server-side issue surfaced by the user, not a Pythinker bug.
