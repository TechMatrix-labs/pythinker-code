# MiniMax Auth Design

## Goal

Add MiniMax as a first-class managed provider in Pythinker Code so users with a MiniMax API key (Open Platform pay-as-you-go OR Token Plan subscription) can configure the provider from the CLI and use the current MiniMax M2.5 / M2.7 text models.

This change is limited to MiniMax text-model access. It does not add MiniMax speech, image, video, or music models. It does not add any non-MiniMax provider.

## Context

Pythinker currently has managed provider setup for OpenAI (API key + ChatGPT OAuth) and OpenCode Go (API key with two-provider split). This task adds an analogous managed setup for MiniMax.

MiniMax exposes both an OpenAI-compatible chat-completions API and an Anthropic-compatible messages API at distinct base URLs that share a single API key. MiniMax's official documentation recommends the Anthropic-compatible endpoint for full feature support (thinking blocks, tool use, etc.). Because the Anthropic-compatible endpoint is the recommended surface and supports every text model we plan to expose, this design configures **only the Anthropic-compatible managed provider** by default. Users who prefer the OpenAI-compatible surface can edit `config.toml` directly; that is a deliberate simplification, not a limitation.

MiniMax has two key types that share the same wire format (`Authorization: Bearer <key>`):

- **Open Platform / pay-as-you-go keys** — billed per token. Prefix typically `sk-`.
- **Token Plan / Coding Plan keys** — subscription, prompt quotas per 5-hour window for text models. Prefix `sk-cp-`.

The two key types are NOT interchangeable: the server enforces the binding. The client wire format is identical, so Pythinker treats both transparently and only emits an informational event when a Token Plan key is detected.

## User-facing behavior

Add a dedicated MiniMax setup mode without changing any existing login flow.

CLI:

```sh
pythinker login --minimax
pythinker logout --minimax
```

Shell:

```text
/login minimax
/logout minimax
```

The command prompts for the MiniMax API key (hidden input), validates it via best-effort model discovery, writes a managed provider and model aliases, and reloads the shell after successful setup.

The setup must also support an environment-provided key. If a key is not provided interactively, use:

1. `MINIMAX_API_KEY` (only documented MiniMax env var)

No other fallback variable names are supported (MiniMax docs do not document any).

The dedicated MiniMax mode must not change `pythinker login`, `pythinker login --browser`, `pythinker login --headless`, `pythinker login --api-key`, `pythinker login --opencode-go`, `/login`, `/login browser`, `/login headless`, `/login api-key`, or `/login opencode-go`.

## Provider configuration

Add a provider family ID for model aliases and telemetry:

```text
minimax
```

Configure ONE managed provider entry. The Anthropic-compatible endpoint is MiniMax's recommended surface and supports every model we expose:

- `managed:minimax-anthropic` — type `anthropic`, base URL `https://api.minimax.io/anthropic`.

Provider key naming preserves the Pythinker convention (`managed:<family>-<wire-format>`). Even though only one provider is configured, the suffix `-anthropic` keeps room for an optional `-openai` provider in the future without renaming the existing key.

Model aliases follow the project's existing form:

```text
minimax/<model-id-suffix>
```

The `LLMModel.model` field stores the EXACT API model ID (CamelCase, e.g. `MiniMax-M2.7`), while the alias uses a lowercase short form (`minimax/m2.7`).

The implementation must add small MiniMax-specific helpers for provider keys, model alias construction, and removal — do not stretch the OpenCode Go helpers, even though the patterns are similar.

## Models

Configure exactly four current text models (M2.5 and M2.7, standard and high-speed):

| Alias | API model ID | Provider type | Display name | Max context |
| --- | --- | --- | --- | --- |
| `minimax/m2.7` | `MiniMax-M2.7` | `anthropic` | MiniMax M2.7 | 192_000 |
| `minimax/m2.7-highspeed` | `MiniMax-M2.7-highspeed` | `anthropic` | MiniMax M2.7 High-Speed | 192_000 |
| `minimax/m2.5` | `MiniMax-M2.5` | `anthropic` | MiniMax M2.5 | 192_000 |
| `minimax/m2.5-highspeed` | `MiniMax-M2.5-highspeed` | `anthropic` | MiniMax M2.5 High-Speed | 192_000 |

Legacy `MiniMax-M2.1`, `MiniMax-M2`, and `M2-her` are intentionally excluded.

Set the default model to `minimax/m2.7` after successful setup. If `m2.7` is not present in the discovered list, fall back to the first configured MiniMax model (preserving the static catalog order above).

If model discovery returns numeric `context_length` values for any of the four official models, prefer that discovered value over the static 192,000 default.

## Token Plan awareness

After successful setup, inspect the resolved API key for a Token Plan prefix and emit a single informational event before the success event when applicable:

- If the resolved key starts with `sk-cp-` → emit `OAuthEvent("info", "MiniMax Token Plan key detected; requests are quota-metered (5-hour rolling window for text), not per-token billed.")`.
- Otherwise → no extra event (default pay-as-you-go assumption).

Detection is purely client-side and informational. The server enforces the actual key-type binding; Pythinker never blocks or rewrites traffic based on the prefix.

The detection MUST run on the resolved key value (after env-var resolution and trimming) and MUST NOT include the key in the event message or JSON output.

## Model discovery

MiniMax exposes `https://api.minimax.io/v1/models` (OpenAI-compatible listing). The setup flow must:

1. Try to list models from `https://api.minimax.io/v1/models` with `Authorization: Bearer <api key>`.
2. If the endpoint returns a usable list, map known IDs (`MiniMax-M2.7`, `MiniMax-M2.7-highspeed`, `MiniMax-M2.5`, `MiniMax-M2.5-highspeed`) into the static catalog above, optionally overriding `max_context_size` from `context_length` and `display_name` from `display_name`.
3. If listing fails with `404`, non-JSON HTML, timeout, or a non-auth server error, fall back to the static official model list and emit an `info` event before success.
4. If listing fails with `401` or `403`, do not save the key. Emit an `error` event with `"Invalid MiniMax API key; the key was not saved."`.

Discovery is best-effort. Tests must mock all network calls.

Note: discovery uses the OpenAI-compatible `/v1/models` endpoint even though chat traffic uses the Anthropic-compatible endpoint, because the MiniMax `/v1/models` listing is the documented model-discovery API and returns the same model IDs.

## Validation

API key validation must avoid generation requests.

Preferred validation order:

1. `GET https://api.minimax.io/v1/models` with `Authorization: Bearer <key>`.
2. If unavailable for non-auth reasons, accept the key and configure the static model list with an info-level event.
3. If the response is `401` or `403`, show a clear error and do not save the key.

Do not log or display the API key. JSON event output must redact secrets.

## Data flow

CLI setup:

1. User runs `pythinker login --minimax`.
2. Pythinker reads `MINIMAX_API_KEY` from the environment or prompts for one (hidden input).
3. Pythinker attempts model discovery and validates auth failures.
4. Pythinker writes the managed provider entry and the four MiniMax model aliases.
5. Pythinker emits a Token Plan info event if the key has the `sk-cp-` prefix.
6. Pythinker sets `default_model` to `minimax/m2.7` or the first configured MiniMax model.
7. Pythinker reports success with the default model.

Shell setup:

1. User runs `/login minimax`.
2. Pythinker prompts for the API key when no environment key exists.
3. Pythinker renders setup events through the existing OAuth event renderer.
4. On success, Pythinker tracks a `login` event with provider `minimax`, clears the console, and reloads the shell.

## Logout behavior

Existing OpenAI and OpenCode Go logout behavior must not remove MiniMax providers. Add both user-facing logout options:

- `pythinker logout --minimax`
- `/logout minimax`

Logout removes the `managed:minimax-anthropic` provider entry and every model whose `provider` field equals that key. If `default_model` points to a removed MiniMax model, set `default_model` to the first remaining configured model or clear it (`""`).

## Error handling

- If the user enters an empty API key and no environment key exists, print `MiniMax API key is required.`
- If model discovery returns `401` or `403`, print `Invalid MiniMax API key; the key was not saved.`
- If model discovery is unavailable for non-auth reasons (timeout, 404, 5xx, malformed JSON), configure the static model list and print an info-level event before the success event.
- The Token Plan info event is emitted regardless of discovery outcome (it is a property of the key itself, not the discovery response).

## Testing

Add tests for:

- Model catalog completeness (four aliases, exact API IDs, all assigned to the anthropic provider key).
- Env precedence: `MINIMAX_API_KEY`.
- Config writes for the single MiniMax managed provider.
- All four current model aliases are created.
- Default model selection prefers `minimax/m2.7`.
- `401` and `403` model discovery failures do not save the key.
- Non-auth model discovery failures fall back to the static official model list with an info event before success.
- API keys are not included in event messages or JSON output.
- Token Plan detection: `sk-cp-` prefix triggers exactly one info event before the success event; non-`sk-cp-` keys do not.
- MiniMax logout removes only MiniMax providers/models and leaves OpenAI and OpenCode Go providers intact.
- CLI parsing for `pythinker login --minimax` and `pythinker logout --minimax`.
- Shell routing for `/login minimax` and `/logout minimax`.

All tests must mock network calls. No tests should call real MiniMax endpoints.

Provider construction (`create_llm` for the `anthropic` provider type at a non-default base URL) was verified during the OpenCode Go work in `tests/core/test_openai_provider.py::test_create_llm_supports_opencode_go_anthropic_provider`. That coverage is sufficient; no additional provider-construction test is required for MiniMax.

## Non-goals

- Do not add the OpenAI-compatible MiniMax provider (`https://api.minimax.io/v1`) by default.
- Do not add MiniMax legacy models (M2.1, M2, M2-her).
- Do not add MiniMax non-text models (speech, image, video, music).
- Do not add Token Plan quota tracking — Pythinker does not poll usage endpoints.
- Do not change any existing login or logout behavior.
- Do not require any external MiniMax CLI binary.
- Do not integrate with MiniMax's web platform cookie session (out of scope; the docs say it is not API-key authenticated).
