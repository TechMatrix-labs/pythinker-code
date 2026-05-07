# LM Studio & Ollama Local Provider Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class support for two local model runtimes — **LM Studio** (default `http://localhost:1234/v1`) and **Ollama** (default `http://localhost:11434/v1`) — as managed providers in Pythinker Code, with discovery, login/logout, model auto-refresh, and graceful behavior when the local server is unreachable.

**Architecture:** Both runtimes expose an OpenAI-compatible `/v1/chat/completions` API with full feature parity for what Pythinker Code consumes (chat, streaming, tools, JSON mode / structured outputs, vision, `reasoning_effort`). We therefore reuse the existing `openai_legacy` provider type with `base_url` pointed at the local server — **no new `ProviderType` is added**. We register two new `Platform` entries (`lm-studio`, `ollama`) and add per-runtime `auth` modules that mirror the DeepSeek pattern (`src/pythinker_code/auth/deepseek.py`) but treat the API key as optional, accept a custom `base_url` for non-default ports, and enrich model metadata with a runtime-native call (`/api/v0/models` for LM Studio, `/api/tags` + `/api/show` for Ollama) with a clean fallback to the OpenAI-compat `/v1/models` shape.

**Tech Stack:** Python 3.12+, Typer, pytest, pytest-asyncio, pydantic `SecretStr`, aiohttp, existing `OAuthEvent`, `Config`, `LLMProvider`, `LLMModel`, `save_config`, `Platform` registry in `auth/platforms.py`, the shared `_prompt_api_key` shell helper, and the `_LOGIN_PROVIDER_OPTIONS` chooser tuple in `ui/shell/oauth.py`.

**Source-of-truth references** (verified via Tavily + Context7, 2026-05-07):
- LM Studio OpenAI compat: https://lmstudio.ai/docs/developer/openai-compat (endpoints `/v1/models`, `/v1/chat/completions`, `/v1/responses`, `/v1/completions`, `/v1/embeddings`)
- LM Studio v0 native: https://lmstudio.ai/docs/developer/rest/endpoints (`GET /api/v0/models` → `loaded_context_length`, `max_context_length`, `arch`, `quantization`, `state`)
- Ollama OpenAI compat: https://docs.ollama.com/api/openai-compatibility (full feature set: streaming, JSON mode, vision, tools, `reasoning_effort`, `tool_choice`)
- Ollama native: https://docs.ollama.com/api/introduction (`GET /api/tags` for model list with size/family/parameter_size; `POST /api/show` for per-model `model_info.<arch>.context_length`)

---

## Why we are NOT adding a new provider type

The `openai_legacy` adapter (`pythinker_core.contrib.chat_provider.openai_legacy.OpenAILegacy`) already supports every feature these runtimes expose over `/v1/chat/completions`:

| Feature             | LM Studio `/v1` | Ollama `/v1` | Carried by `openai_legacy` |
|---------------------|-----------------|--------------|----------------------------|
| Streaming           | ✅              | ✅           | ✅                         |
| Tools / tool_choice | ✅              | ✅           | ✅                         |
| JSON mode / structured outputs (`response_format`) | ✅ | ✅ | ✅ |
| Vision (base64 image content parts) | ✅ | ✅ | ✅ |
| `reasoning_effort`  | ✅ (gpt-oss)    | ✅           | ✅ via `reasoning_key`     |
| `temperature`, `top_p`, `max_tokens`, `seed`, `stop` | ✅ | ✅ | ✅ |

The runtimes' *native* APIs (`/api/v1/chat`, `/api/chat`) only add stateful chat / model load streaming / MCP — features not used by the agent core. Adding a third provider type to `pythinker_code.llm.ProviderType` would buy nothing and double the test surface. Reuse `openai_legacy` and keep the LM Studio / Ollama specifics in their auth modules.

---

## File Structure

- **Modify** `src/pythinker_code/auth/__init__.py`
  - Add `LM_STUDIO_PLATFORM_ID = "lm-studio"` and `OLLAMA_PLATFORM_ID = "ollama"` constants and re-export them.
- **Modify** `src/pythinker_code/auth/platforms.py`
  - Append `Platform` entries for both runtimes so `refresh_managed_models` walks them just like DeepSeek/OpenRouter.
  - Make the `_list_models` Authorization header tolerate empty / placeholder API keys (the local servers accept any string but reject malformed `Authorization` lines on some builds — send the header only when a real key is present).
- **Create** `src/pythinker_code/auth/lm_studio.py`
  - Constants, env resolution (`LM_STUDIO_BASE_URL`, `LM_STUDIO_API_KEY`), reachability probe, `_apply_lm_studio_config`, native enrichment via `GET /api/v0/models`, `login_lm_studio`, `logout_lm_studio`.
- **Create** `src/pythinker_code/auth/ollama.py`
  - Constants, env resolution (`OLLAMA_BASE_URL`, `OLLAMA_API_KEY`), reachability probe, `_apply_ollama_config`, native enrichment via `GET /api/tags` and per-model `POST /api/show`, `login_ollama`, `logout_ollama`.
- **Modify** `src/pythinker_code/cli/__init__.py`
  - Add `--lm-studio` and `--ollama` flags to the `login` and `logout` Typer commands. Both accept an optional `--base-url` and `--api-key`. Mirror the existing `--deepseek` routing exactly.
- **Modify** `src/pythinker_code/ui/shell/oauth.py`
  - Add `/login lm-studio` and `/login ollama` shell modes; append `LM Studio` and `Ollama` to `_LOGIN_PROVIDER_OPTIONS`; add corresponding `/logout` modes; update the usage error strings.
- **Create** `tests/auth/test_lm_studio_auth.py` and `tests/auth/test_ollama_auth.py`
  - Mirror `tests/auth/test_deepseek_auth.py` structure: env resolution, config write, discovery happy path, discovery server-down path (fallback), 401-tolerated path, logout, secret redaction, malformed-payload parser tests.
- **Modify** `tests/auth/test_platforms.py`
  - Assert the two new platforms are registered with the correct base URLs and that `refresh_managed_models` skips them gracefully when the server is unreachable (no exception bubbles).
- **Modify** `tests/cli/test_openai_login_cli.py` (or its sibling for login flags — match whatever the deepseek tests modify)
  - CLI route tests for `pythinker login --lm-studio` / `--ollama` and the corresponding logout flags, including mutual-exclusion errors.
- **Modify** `tests/ui_and_conv/test_openai_shell_login.py` (or sibling)
  - Shell tests for `/login lm-studio`, `/login ollama`, `/logout lm-studio`, `/logout ollama`, including the chooser line.

---

## Behavior Specification

### Reachability and base URL

- **Default base URLs:** `http://localhost:1234/v1` (LM Studio), `http://localhost:11434/v1` (Ollama).
- **Override:** `LM_STUDIO_BASE_URL`, `OLLAMA_BASE_URL` env vars (read at login time and via `augment_provider_with_env_vars` at runtime — see below).
- **`--base-url` flag:** lets a user point at a remote LAN host (e.g. another machine on `http://192.168.1.10:1234/v1`).
- The login flow probes `GET {base_url}/models` once with a 5s timeout. On `ConnectionRefused` / `TimeoutError`, the login emits an `OAuthEvent("error", "<runtime> server is not reachable at <url>; start it and retry.")` and **does not write the provider** (avoids leaving a half-configured provider that breaks `Config.validate_model`).

### API key handling

- Local servers do not require auth by default. The `--api-key` flag and `LM_STUDIO_API_KEY` / `OLLAMA_API_KEY` env vars are honored when set; otherwise use the placeholder `"local"`.
- `LLMProvider.api_key` is required (`SecretStr`), so we always store *something* — but the discovery client and `openai_legacy` chat client only attach the `Authorization: Bearer <key>` header when the resolved key is not `"local"`. Add a single helper `_authorization_header(api_key: str) -> dict[str, str]` in each auth module to gate this; `_list_models` in `platforms.py` is updated to take an *optional* `headers` builder so the same gate applies to model refresh. (See Task 2.)

### Discovery and model enrichment

- **Path A (always works):** `GET {base_url}/models` → OpenAI-compat list of `{id}`. Sufficient for the runtime to be usable.
- **Path B (richer):** call the native endpoint to fill `max_context_size`, `display_name`, and any obvious capabilities:
  - LM Studio: `GET {base_url_root}/api/v0/models` returns each model's `id`, `arch`, `state`, `max_context_length`, `loaded_context_length`, `quantization`, `type` (`llm` vs `embeddings`). Filter to `type == "llm"`. Use `max_context_length` for `LLMModel.max_context_size`. Build `display_name` from `arch` + `quantization` (e.g. `"qwen2 (Q4_K_M)"`).
  - Ollama: `GET {base_url_root}/api/tags` returns each model's `name`, `size`, `details.family`, `details.parameter_size`, `details.quantization_level`. Then `POST {base_url_root}/api/show` (body `{"name": <model>}`) yields `model_info["<arch>.context_length"]` and the architecture key. Use `parameter_size` + `quantization_level` for `display_name`.
- **Fallback:** if Path B fails (404, network), use a per-runtime default `max_context_size` (32768) and an empty `display_name`. Discovery still succeeds.

`base_url_root` is `base_url` with the trailing `/v1` stripped (so `http://localhost:1234/v1` → `http://localhost:1234`). Compute it once at the top of each enrichment helper.

### Model alias scheme

Aliases follow the existing `<platform_id>/<model_id>` convention used by `managed_model_key`:
- `lm-studio/qwen2.5-coder-32b-instruct`
- `ollama/llama3.1:8b`

The provider key is `managed:lm-studio` / `managed:ollama` so the existing `MANAGED_PROVIDER_PREFIX` machinery in `platforms.py` and the `/usage` rate-limit cache key downstream both work unchanged.

### Default-model selection on login

After discovery, set `Config.default_model` to the alias of the model that has the largest `max_context_size` (ties broken by alphabetical order on `id`), unless `Config.default_model` already references a different platform — in which case leave it alone (don't steal default from a configured cloud provider on a `pythinker login --ollama` invocation).

### Logout

Mirror `logout_deepseek`: pop `managed:<platform>` from `config.providers`, drop every `LLMModel` whose `provider == managed:<platform>`, and if the now-deleted alias was `default_model`, fall back to `next(iter(config.models), "")`. Save and emit one success event.

### Env var overrides at runtime

Extend `pythinker_code.llm.augment_provider_with_env_vars` so `LM_STUDIO_BASE_URL` / `LM_STUDIO_API_KEY` and `OLLAMA_BASE_URL` / `OLLAMA_API_KEY` override `provider.base_url` / `provider.api_key` for the matching managed provider keys. The match is by the provider entry's *key in the dict* (`model.provider == "managed:lm-studio"` / `"managed:ollama"`), not by `provider.type` (which is `openai_legacy` for several providers). Pass the provider key into `augment_provider_with_env_vars` — that requires updating the single call site at `src/pythinker_code/cli/plugin.py:257` to pass `model.provider` as a third argument. (Existing branches are keyed on `provider.type` and stay untouched.)

---

## Task 1: Register Platforms And Constants

**Files:**
- Modify: `src/pythinker_code/auth/__init__.py`
- Modify: `src/pythinker_code/auth/platforms.py`
- Test: `tests/auth/test_platforms.py`

- [ ] **Step 1: Add failing tests for the new platform registry entries**

Append to `tests/auth/test_platforms.py`:

```python
def test_lm_studio_platform_registered():
    from pythinker_code.auth import LM_STUDIO_PLATFORM_ID
    from pythinker_code.auth.platforms import get_platform_by_id

    platform = get_platform_by_id(LM_STUDIO_PLATFORM_ID)
    assert platform is not None
    assert platform.name == "LM Studio"
    assert platform.base_url == "http://localhost:1234/v1"
    assert platform.allowed_prefixes is None


def test_ollama_platform_registered():
    from pythinker_code.auth import OLLAMA_PLATFORM_ID
    from pythinker_code.auth.platforms import get_platform_by_id

    platform = get_platform_by_id(OLLAMA_PLATFORM_ID)
    assert platform is not None
    assert platform.name == "Ollama"
    assert platform.base_url == "http://localhost:11434/v1"
    assert platform.allowed_prefixes is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_platforms.py -v`
Expected: FAIL with `AttributeError` / `AssertionError` for the two new tests.

- [ ] **Step 3: Add platform IDs**

Edit `src/pythinker_code/auth/__init__.py` to add the two constants and export them:

```python
from __future__ import annotations

PYTHINKER_CODE_PLATFORM_ID = "pythinker-code"
OPENAI_API_PLATFORM_ID = "openai"
OPENAI_CHATGPT_PLATFORM_ID = "openai-chatgpt"
OPENCODE_GO_PLATFORM_ID = "opencode-go"
MINIMAX_PLATFORM_ID = "minimax"
DEEPSEEK_PLATFORM_ID = "deepseek"
ANTHROPIC_PLATFORM_ID = "anthropic"
OPENROUTER_PLATFORM_ID = "openrouter"
LM_STUDIO_PLATFORM_ID = "lm-studio"
OLLAMA_PLATFORM_ID = "ollama"

__all__ = [
    "ANTHROPIC_PLATFORM_ID",
    "DEEPSEEK_PLATFORM_ID",
    "LM_STUDIO_PLATFORM_ID",
    "MINIMAX_PLATFORM_ID",
    "OLLAMA_PLATFORM_ID",
    "OPENAI_API_PLATFORM_ID",
    "OPENAI_CHATGPT_PLATFORM_ID",
    "OPENCODE_GO_PLATFORM_ID",
    "OPENROUTER_PLATFORM_ID",
    "PYTHINKER_CODE_PLATFORM_ID",
]
```

- [ ] **Step 4: Append `Platform` entries**

In `src/pythinker_code/auth/platforms.py`, import the new IDs:

```python
from pythinker_code.auth import (
    LM_STUDIO_PLATFORM_ID,
    OLLAMA_PLATFORM_ID,
    OPENAI_API_PLATFORM_ID,
    OPENAI_CHATGPT_PLATFORM_ID,
    PYTHINKER_CODE_PLATFORM_ID,
)
```

Add two helpers near `_pythinker_code_base_url`:

```python
def _lm_studio_base_url() -> str:
    return os.getenv("LM_STUDIO_BASE_URL") or "http://localhost:1234/v1"


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
```

Append to the `PLATFORMS` list (after the existing `pythinker-ai` entry):

```python
    Platform(
        id=LM_STUDIO_PLATFORM_ID,
        name="LM Studio",
        base_url=_lm_studio_base_url(),
    ),
    Platform(
        id=OLLAMA_PLATFORM_ID,
        name="Ollama",
        base_url=_ollama_base_url(),
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_platforms.py -v`
Expected: PASS for both new tests; existing tests remain green.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/auth/__init__.py src/pythinker_code/auth/platforms.py tests/auth/test_platforms.py
git commit -m "feat(auth): register lm-studio and ollama platforms"
```

---

## Task 2: Make Platform Discovery Tolerate Optional API Keys

**Files:**
- Modify: `src/pythinker_code/auth/platforms.py`
- Test: `tests/auth/test_platforms.py`

The existing `_list_models` always sends `Authorization: Bearer <key>`. Some local Ollama builds reject the header when the key is not the expected value, and we want to send the header only when the user has actually configured a key.

- [ ] **Step 1: Write the failing test**

Append to `tests/auth/test_platforms.py`:

```python
@pytest.mark.asyncio
async def test_list_models_omits_authorization_when_key_is_local(monkeypatch):
    import aiohttp
    from pythinker_code.auth.platforms import list_models, get_platform_by_id

    captured: dict[str, dict[str, str]] = {}

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return None
        async def json(self):
            return self._payload

    class _Sess:
        def get(self, url, *, headers, raise_for_status):
            captured["headers"] = dict(headers)
            return _Resp({"data": [{"id": "qwen2.5-coder", "context_length": 0}]})
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(
        "pythinker_code.auth.platforms.new_client_session",
        lambda: _Sess(),
    )

    platform = get_platform_by_id("lm-studio")
    assert platform is not None
    await list_models(platform, "local")
    assert "Authorization" not in captured["headers"]

    await list_models(platform, "real-key")
    assert captured["headers"]["Authorization"] == "Bearer real-key"
```

(The test relies on `pytest-asyncio`; the existing `tests/auth/test_platforms.py` already uses it for other cases — match the prevailing style.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/auth/test_platforms.py::test_list_models_omits_authorization_when_key_is_local -v`
Expected: FAIL — current code always sends Authorization.

- [ ] **Step 3: Update `_list_models` to gate the header**

In `src/pythinker_code/auth/platforms.py`, replace the body of `_list_models`:

```python
LOCAL_API_KEY_PLACEHOLDER = "local"


def _bearer_headers(api_key: str) -> dict[str, str]:
    if not api_key or api_key == LOCAL_API_KEY_PLACEHOLDER:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


async def _list_models(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    api_key: str,
) -> list[ModelInfo]:
    models_url = f"{base_url.rstrip('/')}/models"
    try:
        async with session.get(
            models_url,
            headers=_bearer_headers(api_key),
            raise_for_status=True,
        ) as response:
            resp_json = await response.json()
    except aiohttp.ClientError:
        raise

    data = resp_json.get("data")
    if not isinstance(data, list):
        raise ValueError(f"Unexpected models response for {base_url}")

    result: list[ModelInfo] = []
    for item in cast(list[dict[str, Any]], data):
        model_id = item.get("id")
        if not model_id:
            continue
        raw_display_name = item.get("display_name")
        display_name = str(raw_display_name) if raw_display_name else None
        result.append(
            ModelInfo(
                id=str(model_id),
                context_length=int(item.get("context_length") or 0),
                supports_reasoning=bool(item.get("supports_reasoning")),
                supports_image_in=bool(item.get("supports_image_in")),
                supports_video_in=bool(item.get("supports_video_in")),
                display_name=display_name,
            )
        )
    return result
```

Export `LOCAL_API_KEY_PLACEHOLDER` so the auth modules import the same constant.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_platforms.py -v`
Expected: PASS for the new test; all existing platform tests still green.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/platforms.py tests/auth/test_platforms.py
git commit -m "feat(auth): omit Authorization header when api key is local placeholder"
```

---

## Task 3: LM Studio Auth Module

**Files:**
- Create: `src/pythinker_code/auth/lm_studio.py`
- Test: `tests/auth/test_lm_studio_auth.py`

- [ ] **Step 1: Write failing tests**

Create `tests/auth/test_lm_studio_auth.py`:

```python
from __future__ import annotations

import aiohttp
import pytest
from pydantic import SecretStr

from pythinker_code.config import Config


def test_lm_studio_constants():
    from pythinker_code.auth.lm_studio import (
        LM_STUDIO_BASE_URL,
        LM_STUDIO_PROVIDER_KEY,
    )

    assert LM_STUDIO_BASE_URL == "http://localhost:1234/v1"
    assert LM_STUDIO_PROVIDER_KEY == "managed:lm-studio"


def test_lm_studio_env_resolution(monkeypatch):
    from pythinker_code.auth.lm_studio import (
        get_lm_studio_api_key_from_env,
        get_lm_studio_base_url_from_env,
    )

    monkeypatch.delenv("LM_STUDIO_API_KEY", raising=False)
    monkeypatch.delenv("LM_STUDIO_BASE_URL", raising=False)
    assert get_lm_studio_api_key_from_env() is None
    assert get_lm_studio_base_url_from_env() is None

    monkeypatch.setenv("LM_STUDIO_API_KEY", "  k  ")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://10.0.0.5:1234/v1")
    assert get_lm_studio_api_key_from_env() == "k"
    assert get_lm_studio_base_url_from_env() == "http://10.0.0.5:1234/v1"


def test_apply_lm_studio_config_writes_provider_and_models():
    from pythinker_code.auth.lm_studio import (
        LM_STUDIO_BASE_URL,
        LM_STUDIO_PROVIDER_KEY,
        LMStudioModel,
        _apply_lm_studio_config,
    )

    config = Config(is_from_default_location=True)
    models = (
        LMStudioModel(
            model_id="qwen2.5-coder-32b",
            display_name="Qwen2.5 Coder 32B (Q4_K_M)",
            max_context_size=32768,
        ),
        LMStudioModel(
            model_id="llama-3.1-8b",
            display_name="Llama 3.1 8B",
            max_context_size=131072,
        ),
    )

    _apply_lm_studio_config(
        config,
        SecretStr("local"),
        base_url=LM_STUDIO_BASE_URL,
        models=models,
    )

    assert config.providers[LM_STUDIO_PROVIDER_KEY].type == "openai_legacy"
    assert config.providers[LM_STUDIO_PROVIDER_KEY].base_url == LM_STUDIO_BASE_URL
    assert "lm-studio/llama-3.1-8b" in config.models
    # Default picks largest context window
    assert config.default_model == "lm-studio/llama-3.1-8b"


@pytest.mark.asyncio
async def test_login_emits_error_when_server_unreachable(monkeypatch):
    from pythinker_code.auth.lm_studio import login_lm_studio

    async def _raise(*args, **kwargs):
        raise aiohttp.ClientConnectorError(connection_key=None, os_error=OSError("no"))

    monkeypatch.setattr("pythinker_code.auth.lm_studio._discover_lm_studio_models", _raise)

    config = Config(is_from_default_location=True)
    events = [event async for event in login_lm_studio(config)]
    assert any(e.kind == "error" and "not reachable" in e.message for e in events)
    # No provider written when server is down
    assert "managed:lm-studio" not in config.providers


@pytest.mark.asyncio
async def test_logout_lm_studio_clears_provider_and_models():
    from pythinker_code.auth.lm_studio import (
        LM_STUDIO_PROVIDER_KEY,
        LMStudioModel,
        _apply_lm_studio_config,
        logout_lm_studio,
    )

    config = Config(is_from_default_location=True)
    _apply_lm_studio_config(
        config,
        SecretStr("local"),
        base_url="http://localhost:1234/v1",
        models=(LMStudioModel(model_id="m", display_name="M", max_context_size=4096),),
    )
    assert LM_STUDIO_PROVIDER_KEY in config.providers

    events = [event async for event in logout_lm_studio(config)]
    assert any(e.kind == "success" for e in events)
    assert LM_STUDIO_PROVIDER_KEY not in config.providers
    assert all(m.provider != LM_STUDIO_PROVIDER_KEY for m in config.models.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_lm_studio_auth.py -v`
Expected: FAIL — module does not exist yet.

- [ ] **Step 3: Implement `src/pythinker_code/auth/lm_studio.py`**

```python
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import LM_STUDIO_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.auth.platforms import LOCAL_API_KEY_PLACEHOLDER
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
LM_STUDIO_PROVIDER_KEY = "managed:lm-studio"
LM_STUDIO_DEFAULT_CONTEXT_SIZE = 32768


@dataclass(frozen=True, slots=True)
class LMStudioModel:
    model_id: str
    display_name: str
    max_context_size: int = LM_STUDIO_DEFAULT_CONTEXT_SIZE
    provider_key: str = LM_STUDIO_PROVIDER_KEY

    @property
    def alias(self) -> str:
        return f"{LM_STUDIO_PLATFORM_ID}/{self.model_id}"


def get_lm_studio_api_key_from_env() -> str | None:
    value = os.getenv("LM_STUDIO_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def get_lm_studio_base_url_from_env() -> str | None:
    value = os.getenv("LM_STUDIO_BASE_URL")
    if value and value.strip():
        return value.strip()
    return None


def _bearer_headers(api_key: str) -> dict[str, str]:
    if not api_key or api_key == LOCAL_API_KEY_PLACEHOLDER:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _root_url(base_url: str) -> str:
    """Strip trailing /v1 (or /v1/) so we can hit /api/v0/* on the same host."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed[: -len("/v1")]
    return trimmed


async def _discover_lm_studio_models(
    base_url: str,
    api_key: str,
) -> tuple[LMStudioModel, ...]:
    """Prefer the native v0 endpoint (richer metadata); fall back to /v1/models."""
    headers = _bearer_headers(api_key)
    root = _root_url(base_url)
    timeout = aiohttp.ClientTimeout(total=5)

    async with new_client_session() as session:
        # Path B: native enrichment.
        try:
            async with session.get(
                f"{root}/api/v0/models",
                headers=headers,
                timeout=timeout,
                raise_for_status=True,
            ) as response:
                payload = await response.json(content_type=None)
            return _parse_native_lm_studio_models(payload)
        except (aiohttp.ClientResponseError, aiohttp.ClientError, TimeoutError):
            pass

        # Path A: OpenAI-compat fallback.
        async with session.get(
            f"{base_url.rstrip('/')}/models",
            headers=headers,
            timeout=timeout,
            raise_for_status=True,
        ) as response:
            payload = await response.json(content_type=None)
        return _parse_openai_compat_models(payload)


def _parse_native_lm_studio_models(payload: object) -> tuple[LMStudioModel, ...]:
    if not isinstance(payload, dict):
        return ()
    payload = cast(dict[str, Any], payload)
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return ()

    result: list[LMStudioModel] = []
    for item in cast(list[dict[str, Any]], raw_items):
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        if item.get("type") not in (None, "llm", "vlm"):
            # Skip embedding models; they are not chat-capable.
            continue
        max_ctx = item.get("max_context_length")
        if not isinstance(max_ctx, int) or max_ctx <= 0:
            max_ctx = LM_STUDIO_DEFAULT_CONTEXT_SIZE
        arch = item.get("arch") if isinstance(item.get("arch"), str) else None
        quant = item.get("quantization") if isinstance(item.get("quantization"), str) else None
        display = " ".join(part for part in (arch, f"({quant})" if quant else None) if part) or model_id
        result.append(
            LMStudioModel(
                model_id=model_id,
                display_name=display,
                max_context_size=max_ctx,
            )
        )
    return tuple(result)


def _parse_openai_compat_models(payload: object) -> tuple[LMStudioModel, ...]:
    if not isinstance(payload, dict):
        return ()
    payload = cast(dict[str, Any], payload)
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return ()
    result: list[LMStudioModel] = []
    for item in cast(list[dict[str, Any]], raw_items):
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        result.append(
            LMStudioModel(
                model_id=model_id,
                display_name=model_id,
                max_context_size=LM_STUDIO_DEFAULT_CONTEXT_SIZE,
            )
        )
    return tuple(result)


def _apply_lm_studio_config(
    config: Config,
    api_key: SecretStr,
    *,
    base_url: str,
    models: tuple[LMStudioModel, ...],
) -> None:
    config.providers[LM_STUDIO_PROVIDER_KEY] = LLMProvider(
        type="openai_legacy",
        base_url=base_url,
        api_key=api_key,
    )

    # Replace any prior LM Studio aliases.
    for key, model in list(config.models.items()):
        if model.provider == LM_STUDIO_PROVIDER_KEY:
            del config.models[key]

    for model in models:
        config.models[model.alias] = LLMModel(
            provider=model.provider_key,
            model=model.model_id,
            max_context_size=model.max_context_size,
            display_name=model.display_name,
        )

    if not models:
        return

    # Pick the model with the largest context, ties broken by alias sort.
    best = max(models, key=lambda m: (m.max_context_size, m.alias))
    if not config.default_model or config.default_model not in config.models:
        config.default_model = best.alias


async def login_lm_studio(
    config: Config,
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    resolved_url = (
        (base_url or get_lm_studio_base_url_from_env() or LM_STUDIO_BASE_URL).strip()
    )
    resolved_key = (api_key or get_lm_studio_api_key_from_env() or LOCAL_API_KEY_PLACEHOLDER).strip()

    try:
        models = await _discover_lm_studio_models(resolved_url, resolved_key)
    except aiohttp.ClientResponseError as exc:
        if exc.status in (401, 403):
            yield OAuthEvent("error", "LM Studio rejected the API key; the key was not saved.")
            return
        yield OAuthEvent(
            "error",
            f"LM Studio model listing failed ({exc.status}); the provider was not saved.",
        )
        return
    except (aiohttp.ClientError, TimeoutError, ConnectionError) as exc:
        yield OAuthEvent(
            "error",
            f"LM Studio server is not reachable at {resolved_url}; start it and retry. ({exc})",
        )
        return

    if not models:
        yield OAuthEvent(
            "error",
            "LM Studio reported zero loaded chat models; load a model in the LM Studio UI and retry.",
        )
        return

    _apply_lm_studio_config(
        config,
        SecretStr(resolved_key),
        base_url=resolved_url,
        models=models,
    )
    save_config(config)
    yield OAuthEvent(
        "success",
        f"LM Studio configured at {resolved_url} with {len(models)} model(s); "
        f"default = {config.default_model}.",
    )


async def logout_lm_studio(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    config.providers.pop(LM_STUDIO_PROVIDER_KEY, None)
    for key, model in list(config.models.items()):
        if model.provider == LM_STUDIO_PROVIDER_KEY:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of LM Studio successfully.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_lm_studio_auth.py -v`
Expected: PASS for all five tests.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/lm_studio.py tests/auth/test_lm_studio_auth.py
git commit -m "feat(auth): add LM Studio managed provider with native model enrichment"
```

---

## Task 4: Ollama Auth Module

**Files:**
- Create: `src/pythinker_code/auth/ollama.py`
- Test: `tests/auth/test_ollama_auth.py`

The Ollama module mirrors LM Studio but uses `/api/tags` (list) + `/api/show` (per-model context window). Because `/api/show` is per-model, we issue concurrent calls with `asyncio.gather` and tolerate per-model failures (any failure → fall back to `OLLAMA_DEFAULT_CONTEXT_SIZE`).

- [ ] **Step 1: Write failing tests**

Create `tests/auth/test_ollama_auth.py`:

```python
from __future__ import annotations

import aiohttp
import pytest
from pydantic import SecretStr

from pythinker_code.config import Config


def test_ollama_constants():
    from pythinker_code.auth.ollama import OLLAMA_BASE_URL, OLLAMA_PROVIDER_KEY

    assert OLLAMA_BASE_URL == "http://localhost:11434/v1"
    assert OLLAMA_PROVIDER_KEY == "managed:ollama"


def test_ollama_env_resolution(monkeypatch):
    from pythinker_code.auth.ollama import (
        get_ollama_api_key_from_env,
        get_ollama_base_url_from_env,
    )

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert get_ollama_api_key_from_env() is None
    assert get_ollama_base_url_from_env() is None

    monkeypatch.setenv("OLLAMA_API_KEY", " k ")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.5:11434/v1")
    assert get_ollama_api_key_from_env() == "k"
    assert get_ollama_base_url_from_env() == "http://192.168.0.5:11434/v1"


def test_parse_tags_response_extracts_models():
    from pythinker_code.auth.ollama import _parse_tags_payload

    payload = {
        "models": [
            {
                "name": "llama3.1:8b",
                "size": 4_000_000_000,
                "details": {
                    "family": "llama",
                    "parameter_size": "8B",
                    "quantization_level": "Q4_K_M",
                },
            },
            {"name": "mxbai-embed-large", "details": {"family": "bert"}},
        ]
    }
    parsed = _parse_tags_payload(payload)
    # Embedding family is filtered out
    assert {m.model_id for m in parsed} == {"llama3.1:8b"}
    only = parsed[0]
    assert only.display_name == "llama3.1:8b — 8B Q4_K_M"


def test_apply_ollama_config_writes_provider_and_models():
    from pythinker_code.auth.ollama import (
        OLLAMA_BASE_URL,
        OLLAMA_PROVIDER_KEY,
        OllamaModel,
        _apply_ollama_config,
    )

    config = Config(is_from_default_location=True)
    models = (
        OllamaModel(
            model_id="llama3.1:8b",
            display_name="llama3.1:8b — 8B Q4_K_M",
            max_context_size=131072,
        ),
        OllamaModel(
            model_id="qwen2.5-coder:7b",
            display_name="qwen2.5-coder:7b — 7B Q4_K_M",
            max_context_size=32768,
        ),
    )

    _apply_ollama_config(
        config,
        SecretStr("local"),
        base_url=OLLAMA_BASE_URL,
        models=models,
    )

    assert config.providers[OLLAMA_PROVIDER_KEY].type == "openai_legacy"
    assert config.providers[OLLAMA_PROVIDER_KEY].base_url == OLLAMA_BASE_URL
    assert config.default_model == "ollama/llama3.1:8b"


@pytest.mark.asyncio
async def test_login_emits_error_when_server_unreachable(monkeypatch):
    from pythinker_code.auth.ollama import login_ollama

    async def _raise(*args, **kwargs):
        raise aiohttp.ClientConnectorError(connection_key=None, os_error=OSError("no"))

    monkeypatch.setattr("pythinker_code.auth.ollama._discover_ollama_models", _raise)

    config = Config(is_from_default_location=True)
    events = [event async for event in login_ollama(config)]
    assert any(e.kind == "error" and "not reachable" in e.message for e in events)
    assert "managed:ollama" not in config.providers


@pytest.mark.asyncio
async def test_logout_ollama_clears_provider_and_models():
    from pythinker_code.auth.ollama import (
        OLLAMA_PROVIDER_KEY,
        OllamaModel,
        _apply_ollama_config,
        logout_ollama,
    )

    config = Config(is_from_default_location=True)
    _apply_ollama_config(
        config,
        SecretStr("local"),
        base_url="http://localhost:11434/v1",
        models=(OllamaModel(model_id="m", display_name="m", max_context_size=4096),),
    )
    assert OLLAMA_PROVIDER_KEY in config.providers

    events = [event async for event in logout_ollama(config)]
    assert any(e.kind == "success" for e in events)
    assert OLLAMA_PROVIDER_KEY not in config.providers
    assert all(m.provider != OLLAMA_PROVIDER_KEY for m in config.models.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth/test_ollama_auth.py -v`
Expected: FAIL — module does not exist yet.

- [ ] **Step 3: Implement `src/pythinker_code/auth/ollama.py`**

```python
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from pydantic import SecretStr

from pythinker_code.auth import OLLAMA_PLATFORM_ID
from pythinker_code.auth.oauth import OAuthEvent
from pythinker_code.auth.platforms import LOCAL_API_KEY_PLACEHOLDER
from pythinker_code.config import Config, LLMModel, LLMProvider, save_config
from pythinker_code.utils.aiohttp import new_client_session

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_PROVIDER_KEY = "managed:ollama"
OLLAMA_DEFAULT_CONTEXT_SIZE = 32768

# Families we should exclude from chat-model discovery.
_EMBEDDING_FAMILIES = frozenset({"bert", "nomic-bert", "mxbai-embed", "all-minilm"})


@dataclass(frozen=True, slots=True)
class OllamaModel:
    model_id: str
    display_name: str
    max_context_size: int = OLLAMA_DEFAULT_CONTEXT_SIZE
    provider_key: str = OLLAMA_PROVIDER_KEY

    @property
    def alias(self) -> str:
        return f"{OLLAMA_PLATFORM_ID}/{self.model_id}"


def get_ollama_api_key_from_env() -> str | None:
    value = os.getenv("OLLAMA_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def get_ollama_base_url_from_env() -> str | None:
    value = os.getenv("OLLAMA_BASE_URL")
    if value and value.strip():
        return value.strip()
    return None


def _bearer_headers(api_key: str) -> dict[str, str]:
    if not api_key or api_key == LOCAL_API_KEY_PLACEHOLDER:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _root_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed[: -len("/v1")]
    return trimmed


def _parse_tags_payload(payload: object) -> tuple[OllamaModel, ...]:
    if not isinstance(payload, dict):
        return ()
    payload = cast(dict[str, Any], payload)
    raw = payload.get("models")
    if not isinstance(raw, list):
        return ()

    result: list[OllamaModel] = []
    for item in cast(list[dict[str, Any]], raw):
        name = item.get("name")
        if not isinstance(name, str):
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        details = cast(dict[str, Any], details)
        family = details.get("family") if isinstance(details.get("family"), str) else ""
        if family.lower() in _EMBEDDING_FAMILIES:
            continue
        param_size = details.get("parameter_size") if isinstance(details.get("parameter_size"), str) else ""
        quant = details.get("quantization_level") if isinstance(details.get("quantization_level"), str) else ""
        descriptor = " ".join(p for p in (param_size, quant) if p)
        display = f"{name} — {descriptor}" if descriptor else name
        result.append(
            OllamaModel(
                model_id=name,
                display_name=display,
                max_context_size=OLLAMA_DEFAULT_CONTEXT_SIZE,
            )
        )
    return tuple(result)


async def _enrich_with_show(
    session: aiohttp.ClientSession,
    *,
    root: str,
    headers: dict[str, str],
    model: OllamaModel,
    timeout: aiohttp.ClientTimeout,
) -> OllamaModel:
    """Fetch /api/show and patch max_context_size from model_info if available."""
    try:
        async with session.post(
            f"{root}/api/show",
            json={"name": model.model_id},
            headers=headers,
            timeout=timeout,
            raise_for_status=True,
        ) as response:
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError):
        return model

    if not isinstance(payload, dict):
        return model
    info = payload.get("model_info")
    if not isinstance(info, dict):
        return model
    info = cast(dict[str, Any], info)
    for key, value in info.items():
        if key.endswith(".context_length") and isinstance(value, int) and value > 0:
            return OllamaModel(
                model_id=model.model_id,
                display_name=model.display_name,
                max_context_size=value,
            )
    return model


async def _discover_ollama_models(
    base_url: str,
    api_key: str,
) -> tuple[OllamaModel, ...]:
    headers = _bearer_headers(api_key)
    root = _root_url(base_url)
    timeout = aiohttp.ClientTimeout(total=5)

    async with new_client_session() as session:
        async with session.get(
            f"{root}/api/tags",
            headers=headers,
            timeout=timeout,
            raise_for_status=True,
        ) as response:
            payload = await response.json(content_type=None)

        base_models = _parse_tags_payload(payload)
        if not base_models:
            return ()

        enriched = await asyncio.gather(
            *(
                _enrich_with_show(
                    session, root=root, headers=headers, model=m, timeout=timeout
                )
                for m in base_models
            ),
            return_exceptions=False,
        )
        return tuple(enriched)


def _apply_ollama_config(
    config: Config,
    api_key: SecretStr,
    *,
    base_url: str,
    models: tuple[OllamaModel, ...],
) -> None:
    config.providers[OLLAMA_PROVIDER_KEY] = LLMProvider(
        type="openai_legacy",
        base_url=base_url,
        api_key=api_key,
    )

    for key, model in list(config.models.items()):
        if model.provider == OLLAMA_PROVIDER_KEY:
            del config.models[key]

    for model in models:
        config.models[model.alias] = LLMModel(
            provider=model.provider_key,
            model=model.model_id,
            max_context_size=model.max_context_size,
            display_name=model.display_name,
        )

    if not models:
        return

    best = max(models, key=lambda m: (m.max_context_size, m.alias))
    if not config.default_model or config.default_model not in config.models:
        config.default_model = best.alias


async def login_ollama(
    config: Config,
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Login requires the default config file; restart without --config/--config-file.",
        )
        return

    resolved_url = (base_url or get_ollama_base_url_from_env() or OLLAMA_BASE_URL).strip()
    resolved_key = (api_key or get_ollama_api_key_from_env() or LOCAL_API_KEY_PLACEHOLDER).strip()

    try:
        models = await _discover_ollama_models(resolved_url, resolved_key)
    except aiohttp.ClientResponseError as exc:
        if exc.status in (401, 403):
            yield OAuthEvent("error", "Ollama rejected the API key; the key was not saved.")
            return
        yield OAuthEvent(
            "error",
            f"Ollama model listing failed ({exc.status}); the provider was not saved.",
        )
        return
    except (aiohttp.ClientError, TimeoutError, ConnectionError) as exc:
        yield OAuthEvent(
            "error",
            f"Ollama server is not reachable at {resolved_url}; start it and retry. ({exc})",
        )
        return

    if not models:
        yield OAuthEvent(
            "error",
            "Ollama has no chat models pulled; run `ollama pull <model>` and retry.",
        )
        return

    _apply_ollama_config(
        config,
        SecretStr(resolved_key),
        base_url=resolved_url,
        models=models,
    )
    save_config(config)
    yield OAuthEvent(
        "success",
        f"Ollama configured at {resolved_url} with {len(models)} model(s); "
        f"default = {config.default_model}.",
    )


async def logout_ollama(config: Config) -> AsyncIterator[OAuthEvent]:
    if not config.is_from_default_location:
        yield OAuthEvent(
            "error",
            "Logout requires the default config file; restart without --config/--config-file.",
        )
        return

    config.providers.pop(OLLAMA_PROVIDER_KEY, None)
    for key, model in list(config.models.items()):
        if model.provider == OLLAMA_PROVIDER_KEY:
            del config.models[key]

    if config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
    save_config(config)
    yield OAuthEvent("success", "Logged out of Ollama successfully.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/auth/test_ollama_auth.py -v`
Expected: PASS for all six tests.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/auth/ollama.py tests/auth/test_ollama_auth.py
git commit -m "feat(auth): add Ollama managed provider with /api/tags + /api/show enrichment"
```

---

## Task 5: CLI Login/Logout Flags

**Files:**
- Modify: `src/pythinker_code/cli/__init__.py`
- Test: `tests/cli/test_openai_login_cli.py` (or its sibling — match the file the deepseek CLI tests live in; grep for `--deepseek` in tests/cli to confirm)

- [ ] **Step 1: Locate the existing CLI test file**

```bash
grep -rln "deepseek" tests/cli/ | head -1
```

Expected output: a single file path. All edits in this task target that file.

- [ ] **Step 2: Write failing tests**

In the file from Step 1, append (replace `<that_file>`):

```python
def test_login_lm_studio_invokes_login_lm_studio(monkeypatch, runner):
    captured: dict[str, object] = {}

    async def _fake(config, api_key=None, base_url=None):
        captured["config"] = config
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        if False:
            yield  # pragma: no cover

    monkeypatch.setattr(
        "pythinker_code.cli.login_lm_studio",
        _fake,
    )
    result = runner.invoke(app, ["login", "--lm-studio", "--api-key", "k"])
    assert result.exit_code == 0
    assert captured["api_key"] == "k"


def test_login_ollama_invokes_login_ollama(monkeypatch, runner):
    captured: dict[str, object] = {}

    async def _fake(config, api_key=None, base_url=None):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        if False:
            yield  # pragma: no cover

    monkeypatch.setattr(
        "pythinker_code.cli.login_ollama",
        _fake,
    )
    result = runner.invoke(
        app,
        ["login", "--ollama", "--base-url", "http://10.0.0.5:11434/v1"],
    )
    assert result.exit_code == 0
    assert captured["base_url"] == "http://10.0.0.5:11434/v1"


def test_login_lm_studio_and_ollama_mutually_exclusive(runner):
    result = runner.invoke(app, ["login", "--lm-studio", "--ollama"])
    assert result.exit_code != 0
    assert "Choose only one" in result.stdout or "only one" in result.stdout
```

(Match the existing fixture style — the file already has `runner` and `app` fixtures.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/cli/<that_file> -v`
Expected: FAIL — flags do not exist.

- [ ] **Step 4: Wire CLI flags**

In `src/pythinker_code/cli/__init__.py`, near the existing `login_deepseek_api_key` lazy importer, add:

```python
def login_lm_studio(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.lm_studio import login_lm_studio as impl

    return impl(*args, **kwargs)


def logout_lm_studio(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.lm_studio import logout_lm_studio as impl

    return impl(*args, **kwargs)


def login_ollama(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.ollama import login_ollama as impl

    return impl(*args, **kwargs)


def logout_ollama(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.ollama import logout_ollama as impl

    return impl(*args, **kwargs)
```

In the `login` Typer command (search for `--deepseek` to find it), add after the existing `deepseek` flag declaration:

```python
    lm_studio: bool = typer.Option(
        False, "--lm-studio", help="Configure LM Studio as a local provider."
    ),
    ollama: bool = typer.Option(
        False, "--ollama", help="Configure Ollama as a local provider."
    ),
    base_url: str = typer.Option(
        "",
        "--base-url",
        help="Override the default base URL for --lm-studio or --ollama.",
    ),
```

(`--api-key` already exists on this command.)

In the body of `login`, extend the mutual-exclusion check:

```python
        if (
            sum(
                bool(v)
                for v in (
                    deepseek,
                    opencode_go,
                    minimax,
                    openrouter,
                    anthropic,
                    lm_studio,
                    ollama,
                )
            )
            > 1
        ):
            typer.echo(
                "Choose only one of --opencode-go, --minimax, --deepseek, --anthropic, "
                "--openrouter, --lm-studio, or --ollama.",
                err=True,
            )
            raise typer.Exit(code=1)
```

Add the routing branches alongside the `elif deepseek:` branch:

```python
        elif lm_studio:
            events = login_lm_studio(
                config,
                api_key=api_key or None,
                base_url=base_url or None,
            )
        elif ollama:
            events = login_ollama(
                config,
                api_key=api_key or None,
                base_url=base_url or None,
            )
```

In the `logout` command, mirror the same flag-set update and add:

```python
        elif lm_studio:
            events = logout_lm_studio(config)
        elif ollama:
            events = logout_ollama(config)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/cli/ -v`
Expected: PASS for the new tests; previous tests remain green.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/cli/__init__.py tests/cli/<that_file>
git commit -m "feat(cli): add --lm-studio and --ollama login/logout flags"
```

---

## Task 6: Shell `/login` & `/logout` Modes

**Files:**
- Modify: `src/pythinker_code/ui/shell/oauth.py`
- Test: `tests/ui_and_conv/test_openai_shell_login.py` (or whatever file currently houses `/login deepseek` tests; grep `_LOGIN_PROVIDER_OPTIONS` in tests if uncertain)

- [ ] **Step 1: Write failing tests**

In the shell login test file, append:

```python
@pytest.mark.asyncio
async def test_slash_login_lm_studio_invokes_login_lm_studio(monkeypatch, soul):
    captured: dict[str, object] = {}

    async def _fake(config, api_key=None, base_url=None):
        captured["config"] = config
        if False:
            yield  # pragma: no cover

    monkeypatch.setattr(
        "pythinker_code.ui.shell.oauth.login_lm_studio",
        _fake,
    )
    await dispatch(soul, "/login lm-studio")
    assert "config" in captured


@pytest.mark.asyncio
async def test_slash_login_ollama_invokes_login_ollama(monkeypatch, soul):
    captured: dict[str, object] = {}

    async def _fake(config, api_key=None, base_url=None):
        captured["config"] = config
        if False:
            yield  # pragma: no cover

    monkeypatch.setattr(
        "pythinker_code.ui.shell.oauth.login_ollama",
        _fake,
    )
    await dispatch(soul, "/login ollama")
    assert "config" in captured


def test_login_chooser_includes_lm_studio_and_ollama():
    from pythinker_code.ui.shell.oauth import _LOGIN_PROVIDER_OPTIONS

    labels = [label for _, _, label in _LOGIN_PROVIDER_OPTIONS]
    assert "LM Studio" in labels
    assert "Ollama" in labels
```

(Match the prevailing async dispatch helper / `soul` fixture used by sibling tests.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui_and_conv/<file> -v`
Expected: FAIL.

- [ ] **Step 3: Wire shell modes**

In `src/pythinker_code/ui/shell/oauth.py`:

1. Add imports next to the `deepseek` ones:

```python
from pythinker_code.auth.lm_studio import (
    login_lm_studio,
    logout_lm_studio,
)
from pythinker_code.auth.ollama import (
    login_ollama,
    logout_ollama,
)
```

2. Append two entries to `_LOGIN_PROVIDER_OPTIONS` (after the existing `("6", "deepseek", "DeepSeek")` row — pick the next free numeric identifiers):

```python
    ("9", "lm-studio", "LM Studio"),
    ("10", "ollama", "Ollama"),
```

3. In the login dispatcher, add branches alongside `elif mode == "deepseek":`:

```python
    elif mode == "lm-studio":
        ok = await _render_oauth_events(
            login_lm_studio(soul.runtime.config, api_key=None, base_url=None)
        )
    elif mode == "ollama":
        ok = await _render_oauth_events(
            login_ollama(soul.runtime.config, api_key=None, base_url=None)
        )
```

4. In the logout dispatcher add:

```python
    elif mode == "lm-studio":
        ok = await _render_oauth_events(logout_lm_studio(config))
    elif mode == "ollama":
        ok = await _render_oauth_events(logout_ollama(config))
```

5. Update the two usage error strings to include the new modes:

```python
    "[red]Usage: /login [browser|headless|api-key|opencode-go|minimax|deepseek|anthropic|openrouter|lm-studio|ollama][/red]"
```

```python
    "[red]Usage: /logout [opencode-go|minimax|deepseek|anthropic|openrouter|lm-studio|ollama][/red]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui_and_conv/ -v -k "login or logout"`
Expected: PASS for the three new tests.

- [ ] **Step 5: Commit**

```bash
git add src/pythinker_code/ui/shell/oauth.py tests/ui_and_conv/<file>
git commit -m "feat(shell): add /login and /logout for lm-studio and ollama"
```

---

## Task 7: Honor `*_BASE_URL` and `*_API_KEY` Env Vars at Runtime

**Files:**
- Modify: `src/pythinker_code/llm.py`
- Modify: `src/pythinker_code/cli/plugin.py`
- Test: `tests/core/test_llm_env_overrides.py` (create if absent — confirm with `ls tests/core/`)

`augment_provider_with_env_vars` currently switches on `provider.type`, but `openai_legacy` is shared by DeepSeek, OpenRouter, LM Studio, and Ollama. We need a per-provider-key path so `LM_STUDIO_BASE_URL` / `OLLAMA_BASE_URL` can override at runtime without affecting unrelated `openai_legacy` providers.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from pydantic import SecretStr

from pythinker_code.config import LLMModel, LLMProvider
from pythinker_code.llm import augment_provider_with_env_vars


def test_augment_lm_studio_provider_honors_env(monkeypatch):
    provider = LLMProvider(
        type="openai_legacy",
        base_url="http://localhost:1234/v1",
        api_key=SecretStr("local"),
    )
    model = LLMModel(provider="managed:lm-studio", model="qwen", max_context_size=4096)

    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://10.0.0.5:1234/v1")
    monkeypatch.setenv("LM_STUDIO_API_KEY", "secret")

    applied = augment_provider_with_env_vars(provider, model, provider_key="managed:lm-studio")
    assert provider.base_url == "http://10.0.0.5:1234/v1"
    assert provider.api_key.get_secret_value() == "secret"
    assert applied["LM_STUDIO_BASE_URL"] == "http://10.0.0.5:1234/v1"
    assert applied["LM_STUDIO_API_KEY"] == "******"


def test_augment_ollama_provider_honors_env(monkeypatch):
    provider = LLMProvider(
        type="openai_legacy",
        base_url="http://localhost:11434/v1",
        api_key=SecretStr("local"),
    )
    model = LLMModel(provider="managed:ollama", model="llama3.1:8b", max_context_size=4096)

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.5:11434/v1")
    applied = augment_provider_with_env_vars(provider, model, provider_key="managed:ollama")
    assert provider.base_url == "http://192.168.0.5:11434/v1"
    assert "OLLAMA_BASE_URL" in applied


def test_augment_other_openai_legacy_provider_is_unaffected(monkeypatch):
    provider = LLMProvider(
        type="openai_legacy",
        base_url="https://api.deepseek.com/v1",
        api_key=SecretStr("key"),
    )
    model = LLMModel(provider="managed:deepseek", model="deepseek-v4-pro", max_context_size=4096)

    monkeypatch.setenv("LM_STUDIO_BASE_URL", "should-not-leak")
    monkeypatch.setenv("OLLAMA_BASE_URL", "should-not-leak")

    augment_provider_with_env_vars(provider, model, provider_key="managed:deepseek")
    assert provider.base_url == "https://api.deepseek.com/v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_llm_env_overrides.py -v`
Expected: FAIL — `provider_key` argument unsupported.

- [ ] **Step 3: Update `augment_provider_with_env_vars`**

In `src/pythinker_code/llm.py`, change the signature to accept `provider_key` and add the two managed branches. The function becomes:

```python
def augment_provider_with_env_vars(
    provider: LLMProvider,
    model: LLMModel,
    provider_key: str | None = None,
) -> dict[str, str]:
    """Override provider/model settings from environment variables.

    Returns:
        Mapping of environment variables that were applied.
    """
    applied: dict[str, str] = {}

    if provider_key == "managed:lm-studio":
        if base_url := os.getenv("LM_STUDIO_BASE_URL"):
            provider.base_url = base_url
            applied["LM_STUDIO_BASE_URL"] = base_url
        if api_key := os.getenv("LM_STUDIO_API_KEY"):
            provider.api_key = SecretStr(api_key)
            applied["LM_STUDIO_API_KEY"] = "******"
        return applied

    if provider_key == "managed:ollama":
        if base_url := os.getenv("OLLAMA_BASE_URL"):
            provider.base_url = base_url
            applied["OLLAMA_BASE_URL"] = base_url
        if api_key := os.getenv("OLLAMA_API_KEY"):
            provider.api_key = SecretStr(api_key)
            applied["OLLAMA_API_KEY"] = "******"
        return applied

    match provider.type:
        case "pythinker":
            # ... existing block unchanged ...
        case "openai_legacy" | "openai_responses" | "openai_codex":
            # ... existing block unchanged ...
        case _:
            pass

    return applied
```

(Keep the existing `pythinker` and `openai_*` branches verbatim — only the prelude that handles the two managed local providers is added, and the parameter list grows by one optional argument.)

- [ ] **Step 4: Pass `provider_key` from the call site**

In `src/pythinker_code/cli/plugin.py:257`, change:

```python
augment_provider_with_env_vars(config.providers[model.provider], model)
```

to:

```python
augment_provider_with_env_vars(
    config.providers[model.provider], model, provider_key=model.provider
)
```

(Audit other call sites with `grep -rn "augment_provider_with_env_vars" src tests` — pass `provider_key=model.provider` everywhere or default `None`. Any test that does not pass `provider_key` exercises the legacy `provider.type` branches and should still pass.)

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/core/test_llm_env_overrides.py tests/cli tests/auth -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/llm.py src/pythinker_code/cli/plugin.py tests/core/test_llm_env_overrides.py
git commit -m "feat(llm): honor LM_STUDIO_/OLLAMA_ env overrides per provider key"
```

---

## Task 8: Refresh-Models Smoke Test For Local Platforms

**Files:**
- Modify: `tests/auth/test_platforms.py`

`refresh_managed_models` is invoked at startup. When the local server is offline it must not crash, must not delete the user's saved models, and must just log+continue.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_refresh_managed_models_tolerates_unreachable_local_server(monkeypatch):
    import aiohttp
    from pydantic import SecretStr

    from pythinker_code.auth.platforms import refresh_managed_models
    from pythinker_code.config import Config, LLMModel, LLMProvider

    config = Config(is_from_default_location=True)
    config.providers["managed:ollama"] = LLMProvider(
        type="openai_legacy",
        base_url="http://localhost:11434/v1",
        api_key=SecretStr("local"),
    )
    config.models["ollama/llama3.1:8b"] = LLMModel(
        provider="managed:ollama",
        model="llama3.1:8b",
        max_context_size=131072,
    )
    config.default_model = "ollama/llama3.1:8b"

    async def _boom(*args, **kwargs):
        raise aiohttp.ClientConnectorError(connection_key=None, os_error=OSError("no"))

    monkeypatch.setattr("pythinker_code.auth.platforms.list_models", _boom)
    # Should not raise; should not delete the saved model.
    changed = await refresh_managed_models(config)
    assert "ollama/llama3.1:8b" in config.models
    assert config.default_model == "ollama/llama3.1:8b"
    # No fallback list applies to local platforms, so no change is recorded.
    assert changed is False
```

- [ ] **Step 2: Run test to verify it passes (or surface a real bug)**

Run: `uv run pytest tests/auth/test_platforms.py::test_refresh_managed_models_tolerates_unreachable_local_server -v`

The existing `_fallback_or_log` returns `None` for non-OpenAI platforms, which means the loop hits `continue` after the error — so the test should already pass on top of Task 1. If it fails, the bug is real and should be fixed in `platforms.py` by ensuring the `except aiohttp.ClientError` branch (where `_openai_fallback_models` returns `None`) does not propagate the exception. Inspect the actual failure and patch `refresh_managed_models` to swallow the `aiohttp.ClientConnectorError` for non-OAuth providers when no fallback exists.

- [ ] **Step 3: Commit**

```bash
git add tests/auth/test_platforms.py
git commit -m "test(auth): refresh_managed_models tolerates unreachable local servers"
```

---

## Task 9: End-To-End Smoke Test (Manual)

This task is not automated; document it in a checklist that a maintainer runs once after the feature lands.

- [ ] **Step 1: Add a manual verification block to the plan's review section**

Append to the bottom of this document:

```markdown
### Manual verification (post-merge)

1. **LM Studio:** start LM Studio locally, load a chat model in the GUI, run:
   ```bash
   pythinker login --lm-studio
   pythinker --print "say hello in five words"
   ```
   Confirm a response is produced and `~/.local/share/pythinker/config.toml` contains `managed:lm-studio` with `base_url = "http://localhost:1234/v1"`.

2. **Ollama:** start `ollama serve`, then `ollama pull llama3.1:8b`, then run:
   ```bash
   pythinker login --ollama
   pythinker --print "explain quicksort in one paragraph"
   ```
   Confirm the response and that `default_model` is `ollama/llama3.1:8b`.

3. **Reach-LAN sanity:** with the server running on a different host, run:
   ```bash
   pythinker login --ollama --base-url http://<lan-ip>:11434/v1
   ```

4. **Server-down sanity:** stop the server, run `pythinker login --lm-studio`, confirm an error event with "not reachable" is shown and the previous config is unchanged on disk.

5. **Logout:** `pythinker logout --ollama` — confirm the provider and all `ollama/*` aliases disappear from the config.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-05-07-local-providers-lmstudio-ollama.md
git commit -m "docs: add manual verification steps for local providers"
```

---

## Out-Of-Scope (logged, not implemented in this plan)

These are intentionally excluded so this lands as one focused, reviewable change:

- **Native `lmstudio` / `ollama` provider types** in `pythinker_code.llm.ProviderType`. Useful only if we want stateful chats (LM Studio `/api/v1/chat`) or model load streaming. Re-evaluate when those features are user-requested.
- **Embedding model support.** Both runtimes expose `/v1/embeddings`, but Pythinker Code currently has no embedding consumer. Add when a downstream feature needs it.
- **MCP via LM Studio (`/api/v1/chat`).** LM Studio can broker MCP servers; Pythinker already has its own MCP client at `src/pythinker_code/mcp/`. Bridging the two is a separate plan.
- **Anthropic-compatible LM Studio endpoint (`/v1/messages`).** The `anthropic` provider type already supports a custom `base_url`. Adding LM Studio there is a one-line `Platform` registration; defer until a user asks.
- **Auto-pull on missing model.** If a user types `pythinker --model ollama/foo` and `foo` is not pulled, we currently 404. A nicer flow would issue `POST /api/pull` and stream progress. Out of scope.
- **`/usage` rate-limit adapter.** Local servers have no rate limits; the existing `_build_recording_http_client` will record empty headers, which is fine.
- **Web UI provider toggles** under `web/` and `vis/`. The CLI surface is the contract; UI surfacing comes later.

---

## Manual Verification (post-merge)

The automated tests cover correctness of the wiring. Run these one-shot smoke tests against a real local server before announcing the feature.

1. **LM Studio:** start LM Studio, load at least one chat model in the GUI ("Developer → Status: Running"), then run:
   ```bash
   pythinker login --lm-studio
   pythinker --print "say hello in five words"
   ```
   Expected: a one-line response. Confirm `~/.local/share/pythinker/config.toml` contains a `managed:lm-studio` provider with `base_url = "http://localhost:1234/v1"` and a default `lm-studio/<model_id>` alias.

2. **Ollama:** `ollama serve` in one terminal, `ollama pull llama3.1:8b` in another, then:
   ```bash
   pythinker login --ollama
   pythinker --print "explain quicksort in one paragraph"
   ```
   Confirm response and that `default_model` is `ollama/llama3.1:8b`.

3. **Reach-LAN sanity:** point at a different host:
   ```bash
   pythinker login --ollama --base-url http://<lan-ip>:11434/v1
   ```
   Confirm the saved provider's `base_url` reflects the override.

4. **Server-down sanity:** stop the local server, then:
   ```bash
   pythinker login --lm-studio
   ```
   Expected: an error message containing "not reachable" and `config.toml` unchanged.

5. **Logout:**
   ```bash
   pythinker logout --ollama
   ```
   Confirm the provider entry and all `ollama/*` model aliases disappear from the config.

6. **Shell modes:** inside the interactive shell, run `/login lm-studio`, `/login ollama`, `/logout lm-studio`, `/logout ollama` and confirm they behave the same as the CLI commands (no API key prompt; immediate config write on success).

7. **Env-var override:** `LM_STUDIO_BASE_URL=http://other:1234/v1 pythinker --print "hi"` should send the request to the override host (verify with the LM Studio server log).

If any step fails, file an issue referencing `docs/superpowers/plans/2026-05-07-local-providers-lmstudio-ollama.md` and the failing step number.

