# Anthropic Direct Auth Design

## Goal

Add Anthropic (direct API) as a managed provider in Pythinker Code so users with an Anthropic Console API key can configure the provider from the CLI and use the current Claude frontier model lineup (Opus 4.7, Sonnet 4.6, Haiku 4.5).

This change is limited to the direct Anthropic API (`https://api.anthropic.com`). It does not configure any third-party gateway (Bedrock, Vertex, Foundry, Portkey, etc.) and does not add any non-Anthropic provider.

## Context

Pythinker already has managed setup for OpenAI, OpenCode Go, MiniMax, and (in the prior plan) DeepSeek. Anthropic follows the same pattern: a single API key authorizes the Messages API, and the existing Pythinker `anthropic` provider type covers the wire format. Provider construction with the `anthropic` type at a configured base URL was already proven during the OpenCode Go work.

The key difference from prior providers: Anthropic uses `x-api-key` + `anthropic-version` headers natively, not `Authorization: Bearer`. The `anthropic` provider wrapper handles this internally.

The new module is named `auth/anthropic_direct.py` (not `auth/anthropic.py`) to disambiguate from the `anthropic` wire-format string used by other managed providers' `LLMProvider.type` field.

## User-facing behavior

CLI:

```sh
pythinker login --anthropic
pythinker logout --anthropic
```

Shell:

```text
/login anthropic
/logout anthropic
```

The command prompts for the Anthropic API key (hidden input), validates it via best-effort model discovery, writes the managed provider and model aliases, and reloads the shell after successful setup.

The setup must also support an environment-provided key. If a key is not provided interactively, use:

1. `ANTHROPIC_API_KEY` (only documented Anthropic env var).

The dedicated Anthropic mode must not change any existing login or logout flow.

## Provider configuration

Provider family ID:

```text
anthropic
```

Configure ONE managed provider entry:

- `managed:anthropic` — type `anthropic`, base URL `https://api.anthropic.com`.

(Note: Anthropic's official SDK appends `/v1/messages` internally; the base URL must NOT include `/v1`. Verify the pythinker_core `anthropic` provider wrapper follows the same convention before writing tests.)

Model aliases follow the project convention:

```text
anthropic/<short-suffix>
```

The `LLMModel.model` field stores the EXACT API model ID (e.g. `claude-opus-4-7`); the alias uses a lowercase short form (`anthropic/claude-opus-4-7` — verbatim, since the API model ID is already in the alias-friendly format).

## Models

Configure exactly three current frontier text models:

| Alias | API model ID | Provider type | Display name | Max context |
| --- | --- | --- | --- | --- |
| `anthropic/claude-opus-4-7` | `claude-opus-4-7` | `anthropic` | Claude Opus 4.7 | 1_000_000 |
| `anthropic/claude-sonnet-4-6` | `claude-sonnet-4-6` | `anthropic` | Claude Sonnet 4.6 | 200_000 |
| `anthropic/claude-haiku-4-5` | `claude-haiku-4-5-20251001` | `anthropic` | Claude Haiku 4.5 | 200_000 |

Notes:

- Opus 4.7 has a 1M-token context window per Anthropic's transparency hub (released 2026-04-16).
- Sonnet 4.6 and Haiku 4.5 use the standard 200K context window.
- The Haiku 4.5 model ID intentionally includes the `-20251001` date suffix because Anthropic ships dated Haiku snapshots; Opus and Sonnet have stable aliases without dates.
- Older models (Opus 4.6, Opus 4.1, Sonnet 4.5, Sonnet 4, Haiku 4) are excluded — frontier-only catalog.

Set the default model to `anthropic/claude-opus-4-7` after successful setup. If `claude-opus-4-7` is not present in the discovered list, fall back to the first configured Anthropic model (preserving the static catalog order above).

If model discovery returns numeric `context_length` values for any of the three official models, prefer that discovered value over the static defaults.

## Model discovery

Anthropic exposes `https://api.anthropic.com/v1/models` (per platform.claude.com docs). The setup flow must:

1. Try to list models from `https://api.anthropic.com/v1/models` with `x-api-key: <api key>` and `anthropic-version: 2023-06-01` headers.
2. If the endpoint returns a usable list, map known IDs (the three current frontier IDs above) into the static catalog, optionally overriding `max_context_size` and `display_name`.
3. If listing fails with `404`, non-JSON, timeout, or a non-auth server error, fall back to the static catalog and emit an `info` event before success.
4. If listing fails with `401` or `403`, do not save the key. Emit an `error` event with `"Invalid Anthropic API key; the key was not saved."`.

Discovery is best-effort. Tests must mock all network calls.

Note: the response format follows OpenAI's `{"object": "list", "data": [...]}` shape; the parser shares the same structure as DeepSeek's and MiniMax's parsers.

## Validation

API-key validation must avoid generation requests.

Preferred validation order:

1. `GET https://api.anthropic.com/v1/models` with `x-api-key` and `anthropic-version` headers.
2. If unavailable for non-auth reasons, accept the key and configure the static model list with an info-level event.
3. If the response is `401` or `403`, show a clear error and do not save the key.

Do not log or display the API key. JSON event output must redact secrets.

## Data flow

CLI setup:

1. User runs `pythinker login --anthropic`.
2. Pythinker reads `ANTHROPIC_API_KEY` from the environment or prompts for one (hidden input).
3. Pythinker attempts model discovery and validates auth failures.
4. Pythinker writes the managed provider entry and the three Anthropic model aliases.
5. Pythinker sets `default_model` to `anthropic/claude-opus-4-7` or the first configured Anthropic model.
6. Pythinker reports success with the default model.

Shell setup:

1. User runs `/login anthropic`.
2. Pythinker prompts for the API key when no environment key exists.
3. Pythinker renders setup events through the existing OAuth event renderer.
4. On success, Pythinker tracks a `login` event with provider `anthropic`, clears the console, and reloads the shell.

## Logout behavior

Existing OpenAI, OpenCode Go, MiniMax, and DeepSeek logout behavior must not remove Anthropic providers. Add both user-facing logout options:

- `pythinker logout --anthropic`
- `/logout anthropic`

Logout removes the `managed:anthropic` provider entry and every model whose `provider` field equals that key. If `default_model` points to a removed Anthropic model, set `default_model` to the first remaining configured model or clear it (`""`).

## Error handling

- If the user enters an empty API key and no environment key exists, print `Anthropic API key is required.`
- If model discovery returns `401` or `403`, print `Invalid Anthropic API key; the key was not saved.`
- If model discovery is unavailable for non-auth reasons (timeout, 404, 5xx, malformed JSON), configure the static model list and print an info-level event before the success event.

## Testing

Add tests for:

- Model catalog completeness (three aliases, exact API IDs, all assigned to `managed:anthropic`).
- Env resolution for `ANTHROPIC_API_KEY`.
- Config writes for the single Anthropic managed provider.
- All current model aliases are created.
- Default model selection prefers `anthropic/claude-opus-4-7`.
- `401` and `403` model discovery failures do not save the key.
- Non-auth model discovery failures fall back to the static official model list with an info event before success.
- Discovery sends both `x-api-key` and `anthropic-version` headers (verified via aiohttp request mocking).
- API keys are not included in event messages or JSON output.
- Anthropic logout removes only Anthropic providers/models.
- CLI parsing for `pythinker login --anthropic` and `pythinker logout --anthropic`.
- Shell routing for `/login anthropic` and `/logout anthropic`.

All tests must mock network calls.

Provider construction (`create_llm` for the `anthropic` provider type at a custom base URL) was verified during the OpenCode Go work. That coverage is sufficient.

## Provider chooser update

Append `Anthropic` as the next sequential option in the `/login` shell chooser. After this change (assuming DeepSeek already landed) the chooser exposes 7 options:

```
1. OpenAI ChatGPT (browser)
2. OpenAI ChatGPT (device code)
3. OpenAI API key
4. OpenCode Go
5. MiniMax
6. DeepSeek
7. Anthropic
```

## Non-goals

- Do not configure third-party Anthropic gateways (Bedrock, Vertex, Foundry, Portkey, LaoZhang, etc.).
- Do not add Anthropic OAuth login (the Anthropic Console requires API keys for programmatic access).
- Do not add Anthropic non-text models or beta endpoints (Files, Skills, Agents, Sessions are out of scope).
- Do not add legacy Claude models (3.x, Sonnet 4.5, Opus 4.6, Opus 4.1).
- Do not change any existing login or logout behavior.
- Do not require the `anthropic` SDK; the project's existing `anthropic` provider wrapper is sufficient.
