# OpenCode Go Auth Design

## Goal

Add OpenCode Go as a first-class setup path in Pythinker Code so users with an OpenCode Go subscription can configure the provider from the CLI and use all current OpenCode Go plan models.

This change is limited to OpenCode Go model access. It does not add Tavily MCP setup, Context7 MCP setup, or generic OpenCode CLI integration.

## Context

Pythinker currently has managed provider setup for OpenAI API keys and OpenAI ChatGPT Codex OAuth. That setup writes provider and model entries into `config.toml`, uses managed provider keys, refreshes managed model lists at startup when possible, and exposes login through both `pythinker login` and `/login`.

OpenCode Go is documented as an API-key-based model provider. Users sign in to OpenCode Zen, subscribe to Go, copy an API key, and connect it in OpenCode. OpenCode Go model IDs use the `opencode-go/<model-id>` form in OpenCode config. The current API base path is `https://opencode.ai/zen/go/v1`.

The OpenCode Go model set is mixed:

- Most models use an OpenAI-compatible `chat/completions` API.
- MiniMax M2.5 and MiniMax M2.7 use an Anthropic-compatible `messages` API.

Because Pythinker already has provider implementations for OpenAI-compatible and Anthropic-compatible APIs, the smallest complete design is to configure two managed providers that share the same OpenCode Go API key.

## User-facing behavior

Add a dedicated OpenCode Go setup mode without changing the default OpenAI login behavior.

CLI examples:

```sh
pythinker login --opencode-go
```

Shell examples:

```text
/login opencode-go
```

The command prompts for the OpenCode Go API key, validates or accepts it, writes managed providers and model aliases, and reloads the shell after successful setup.

The setup must also support environment-provided keys. If a key is not provided interactively, use the first available value from:

1. `OPENCODE_GO_API_KEY`
2. `OPENCODE_API_KEY`
3. `OPENCODE_ZEN_API_KEY`

The dedicated OpenCode Go mode must not replace `pythinker login`, `pythinker login --browser`, `pythinker login --headless`, `pythinker login --api-key`, `/login`, `/login browser`, `/login headless`, or `/login api-key`.

## Provider configuration

Add a provider family ID for model aliases and telemetry:

```text
opencode-go
```

Configure two managed provider entries. These provider keys are intentionally distinct because the APIs are not wire-compatible:

- `managed:opencode-go-openai` for OpenAI-compatible models.
- `managed:opencode-go-anthropic` for Anthropic-compatible models.

Both providers use the same API key and the same base URL:

```text
https://opencode.ai/zen/go/v1
```

The OpenAI-compatible provider uses provider type `openai_legacy`, because OpenCode Go exposes `chat/completions` for these models. The Anthropic-compatible provider uses provider type `anthropic`, because MiniMax models use `messages`.

Model aliases must follow OpenCode's documented form and use the provider family ID, not the internal provider key:

```text
opencode-go/<model-id>
```

The `LLMModel.model` field must contain the raw model ID expected by the API, for example `kimi-k2.6`.

The implementation must not rely on `managed_provider_key("opencode-go")` for this provider family, because one alias family maps to two provider implementations. Add small OpenCode Go-specific helpers for provider keys, model alias construction, and removal instead of stretching the generic managed-platform helpers.

## Models

Configure the current official OpenCode Go model list:

| Alias | API model ID | Provider type | Display name |
| --- | --- | --- | --- |
| `opencode-go/glm-5` | `glm-5` | `openai_legacy` | GLM-5 |
| `opencode-go/glm-5.1` | `glm-5.1` | `openai_legacy` | GLM-5.1 |
| `opencode-go/kimi-k2.5` | `kimi-k2.5` | `openai_legacy` | Kimi K2.5 |
| `opencode-go/kimi-k2.6` | `kimi-k2.6` | `openai_legacy` | Kimi K2.6 |
| `opencode-go/deepseek-v4-pro` | `deepseek-v4-pro` | `openai_legacy` | DeepSeek V4 Pro |
| `opencode-go/deepseek-v4-flash` | `deepseek-v4-flash` | `openai_legacy` | DeepSeek V4 Flash |
| `opencode-go/mimo-v2-pro` | `mimo-v2-pro` | `openai_legacy` | MiMo-V2-Pro |
| `opencode-go/mimo-v2-omni` | `mimo-v2-omni` | `openai_legacy` | MiMo-V2-Omni |
| `opencode-go/mimo-v2.5-pro` | `mimo-v2.5-pro` | `openai_legacy` | MiMo-V2.5-Pro |
| `opencode-go/mimo-v2.5` | `mimo-v2.5` | `openai_legacy` | MiMo-V2.5 |
| `opencode-go/qwen3.5-plus` | `qwen3.5-plus` | `openai_legacy` | Qwen3.5 Plus |
| `opencode-go/qwen3.6-plus` | `qwen3.6-plus` | `openai_legacy` | Qwen3.6 Plus |
| `opencode-go/minimax-m2.5` | `minimax-m2.5` | `anthropic` | MiniMax M2.5 |
| `opencode-go/minimax-m2.7` | `minimax-m2.7` | `anthropic` | MiniMax M2.7 |

Use conservative context sizes from official or third-party metadata when available. If metadata is unavailable, use the documented public values surfaced by current model-router docs:

- `mimo-v2.5` and `mimo-v2.5-pro`: 1,000,000 tokens.
- `qwen3.5-plus` and `qwen3.6-plus`: 262,000 tokens.
- `minimax-m2.5` and `minimax-m2.7`: 205,000 tokens.
- Other OpenCode Go models: 262,000 tokens. If model discovery returns a numeric context length for an official model, prefer that discovered value.

Set the default model to `opencode-go/kimi-k2.6` after successful setup. If that model is not present because the discovered list changes, use the first configured OpenAI-compatible model.

## Model discovery

OpenCode docs list `https://opencode.ai/zen/go/v1/models` as the model metadata endpoint, but current third-party reports indicate the endpoint may return `404` for some valid Go API keys. The implementation must treat model discovery as best effort.

The setup flow must:

1. Try to list models from `https://opencode.ai/zen/go/v1/models` with `Authorization: Bearer <api key>`.
2. If the endpoint returns a usable list, map returned IDs into the provider split above.
3. If listing fails with `404`, non-JSON HTML, timeout, or a non-auth server error, fall back to the static official model list.
4. If listing fails with `401` or `403`, do not save the key.

This keeps the CLI usable even when the model metadata endpoint is unavailable while still rejecting clearly invalid credentials.

## Validation

API key validation must avoid generation requests.

Preferred validation order:

1. `GET /models` against the Go base URL.
2. If that is unavailable for non-auth reasons, accept the key and configure the static model list with a success message that model listing was unavailable.
3. If the response is `401` or `403`, show a clear error and do not save the key.

Do not log or display the API key. JSON event output must redact secrets.

## Data flow

CLI setup:

1. User runs `pythinker login --opencode-go`.
2. Pythinker reads an environment key or prompts for one.
3. Pythinker attempts model discovery and validates auth failures.
4. Pythinker writes both managed providers and all known OpenCode Go model aliases.
5. Pythinker sets `default_model` to `opencode-go/kimi-k2.6` or a safe fallback.
6. Pythinker reports success with the default model.

Shell setup:

1. User runs `/login opencode-go`.
2. Pythinker prompts for the API key when no environment key exists.
3. Pythinker renders setup events through the existing OAuth event renderer.
4. On success, Pythinker tracks a `login` event with provider `opencode-go`, clears the console, and reloads the shell.

## Logout behavior

Existing OpenAI logout behavior must not remove OpenCode Go providers unless the user is explicitly logging out of OpenCode Go.

Add both user-facing logout options:

- `pythinker logout --opencode-go`
- `/logout opencode-go`

Logout must remove both managed OpenCode Go providers and all models whose provider is one of those provider keys. If `default_model` points to a removed model, set it to the first remaining configured model or clear it.

## Error handling

- If the user enters an empty API key and no environment key exists, print `OpenCode Go API key is required.`
- If model discovery returns `401` or `403`, print `Invalid OpenCode Go API key; the key was not saved.`
- If model discovery is unavailable for non-auth reasons, configure the static official model list and print a warning-level event before the success event.
- If a user selects a MiniMax model and the Anthropic-compatible request fails due to provider incompatibility, surface the provider error and leave the configured model intact.
- If OpenCode changes model IDs, startup refresh must preserve existing config until a successful replacement list is available. Startup refresh may be implemented as an OpenCode Go-specific path; it does not need to reuse `refresh_managed_models` if that would blur the two-provider split.

## Testing

Add tests for:

- CLI parsing for `pythinker login --opencode-go`.
- Shell routing for `/login opencode-go`.
- Environment key precedence: `OPENCODE_GO_API_KEY`, then `OPENCODE_API_KEY`, then `OPENCODE_ZEN_API_KEY`.
- Config writes for both OpenCode Go managed providers.
- All current official model aliases are created.
- MiniMax models are assigned to the Anthropic-compatible provider.
- Other OpenCode Go models are assigned to the OpenAI-compatible provider.
- Default model selection prefers `opencode-go/kimi-k2.6`.
- `401` and `403` model discovery failures do not save the key.
- Non-auth model discovery failures fall back to the static official model list.
- API keys are not included in event messages or JSON output.
- OpenCode Go logout removes only OpenCode Go providers/models and leaves OpenAI providers intact.

All tests must mock network calls. No tests should call real OpenCode endpoints.

## Non-goals

- Do not add Tavily MCP setup.
- Do not add Context7 MCP setup.
- Do not change the default `pythinker login` behavior.
- Do not require the external `opencode` binary.
- Do not integrate with OpenCode's local credential file.
- Do not add a custom provider abstraction unless existing provider types cannot support the documented endpoints.
