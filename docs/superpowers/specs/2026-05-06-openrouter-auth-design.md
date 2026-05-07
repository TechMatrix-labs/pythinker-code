# OpenRouter Auth Design

## Goal

Add OpenRouter as a managed provider in Pythinker Code so users with an OpenRouter API key can configure the provider from the CLI and use a curated set of popular models routed through OpenRouter's unified API.

This change is limited to a small starter catalog of six popular models exposed via OpenRouter's OpenAI-compatible chat-completions API. Discovery from OpenRouter's `/api/v1/models` endpoint is used to override metadata for catalog entries but does NOT add new aliases (OpenRouter exposes 500+ models — flooding the user's config is undesirable).

## Context

OpenRouter is a meta-provider that aggregates 500+ models from OpenAI, Anthropic, Google, DeepSeek, MiniMax, Meta, Mistral, xAI, and others behind a single OpenAI-compatible endpoint and a single API key. It uses `Authorization: Bearer sk-or-...` and lives at `https://openrouter.ai/api/v1`.

Pythinker's existing `openai_legacy` provider type covers the wire format. Provider construction at a custom base URL was proven during the OpenCode Go work.

## User-facing behavior

CLI:

```sh
pythinker login --openrouter
pythinker logout --openrouter
```

Shell:

```text
/login openrouter
/logout openrouter
```

The command prompts for the OpenRouter API key (hidden input), validates it via best-effort model discovery, writes the managed provider and the curated model aliases, and reloads the shell after successful setup.

The setup must also support an environment-provided key. If a key is not provided interactively, use:

1. `OPENROUTER_API_KEY` (de facto convention used by every OpenRouter SDK and example).

The dedicated OpenRouter mode must not change any existing login or logout flow.

## Provider configuration

Provider family ID:

```text
openrouter
```

Configure ONE managed provider entry:

- `managed:openrouter` — type `openai_legacy`, base URL `https://openrouter.ai/api/v1`.

Model aliases follow the project convention but include the upstream vendor in the suffix:

```text
openrouter/<vendor>/<model-suffix>
```

The `LLMModel.model` field stores the EXACT OpenRouter model slug (`openai/gpt-5.2`, `anthropic/claude-sonnet-4.6`, etc.). The alias prefixes the slug with `openrouter/` (so the alias is `openrouter/openai/gpt-5.2`).

## Models

Configure exactly six curated starter models:

| Alias | OpenRouter slug | Provider type | Display name | Max context |
| --- | --- | --- | --- | --- |
| `openrouter/openai/gpt-5.2` | `openai/gpt-5.2` | `openai_legacy` | GPT-5.2 (OpenRouter) | 400_000 |
| `openrouter/anthropic/claude-sonnet-4.6` | `anthropic/claude-sonnet-4.6` | `openai_legacy` | Claude Sonnet 4.6 (OpenRouter) | 200_000 |
| `openrouter/anthropic/claude-opus-4.7` | `anthropic/claude-opus-4.7` | `openai_legacy` | Claude Opus 4.7 (OpenRouter) | 1_000_000 |
| `openrouter/deepseek/deepseek-v4-pro` | `deepseek/deepseek-v4-pro` | `openai_legacy` | DeepSeek V4 Pro (OpenRouter) | 128_000 |
| `openrouter/google/gemini-2.5-pro` | `google/gemini-2.5-pro` | `openai_legacy` | Gemini 2.5 Pro (OpenRouter) | 1_000_000 |
| `openrouter/openrouter/auto` | `openrouter/auto` | `openai_legacy` | OpenRouter Auto (router) | 1_000_000 |

Set the default model to `openrouter/openai/gpt-5.2` after successful setup. If that alias is not present in the curated catalog (e.g. user pruned it), fall back to the first configured OpenRouter model.

The static catalog values above are intentional defaults. Discovery may override `max_context_size` and `display_name` for matching slugs (see next section), but discovery does NOT add new aliases.

## Model discovery

OpenRouter exposes `https://openrouter.ai/api/v1/models` returning the full 500+ model catalog. The setup flow must:

1. Try to list models with `Authorization: Bearer <api key>`.
2. If the endpoint returns a usable list, find entries whose `id` matches one of the six curated slugs above. For matches, override `max_context_size` (from the response's `context_length` field) and `display_name` (from `name`). DROP every other discovered model.
3. If listing fails with `404`, non-JSON, timeout, or a non-auth server error, fall back to the static catalog and emit an `info` event before success.
4. If listing fails with `401` or `403`, do not save the key. Emit an `error` event with `"Invalid OpenRouter API key; the key was not saved."`.

The override-without-add behavior is the key difference from MiniMax/DeepSeek (which replace the catalog with discovered models). The reason: OpenRouter exposes hundreds of models and adding them all would flood `config.toml`.

Discovery is best-effort. Tests must mock all network calls.

## Validation

API-key validation must avoid generation requests.

Preferred validation order:

1. `GET https://openrouter.ai/api/v1/models` with `Authorization: Bearer <key>`.
2. If unavailable for non-auth reasons, accept the key and configure the static model list with an info-level event.
3. If the response is `401` or `403`, show a clear error and do not save the key.

Do not log or display the API key. JSON event output must redact secrets.

OpenRouter API keys start with the prefix `sk-or-`. We do NOT validate the prefix client-side because users can have legacy or custom-prefixed keys.

## Data flow

CLI setup:

1. User runs `pythinker login --openrouter`.
2. Pythinker reads `OPENROUTER_API_KEY` from the environment or prompts for one (hidden input).
3. Pythinker attempts model discovery and validates auth failures.
4. Pythinker writes the managed provider entry and the six curated model aliases.
5. Pythinker sets `default_model` to `openrouter/openai/gpt-5.2` or the first configured OpenRouter model.
6. Pythinker reports success with the default model.

Shell setup:

1. User runs `/login openrouter`.
2. Pythinker prompts for the API key when no environment key exists.
3. Pythinker renders setup events through the existing OAuth event renderer.
4. On success, Pythinker tracks a `login` event with provider `openrouter`, clears the console, and reloads the shell.

## Logout behavior

Existing OpenAI, OpenCode Go, MiniMax, DeepSeek, and Anthropic logout behavior must not remove OpenRouter providers. Add both user-facing logout options:

- `pythinker logout --openrouter`
- `/logout openrouter`

Logout removes the `managed:openrouter` provider entry and every model whose `provider` field equals that key. If `default_model` points to a removed OpenRouter model, set `default_model` to the first remaining configured model or clear it (`""`).

## Error handling

- If the user enters an empty API key and no environment key exists, print `OpenRouter API key is required.`
- If model discovery returns `401` or `403`, print `Invalid OpenRouter API key; the key was not saved.`
- If model discovery is unavailable for non-auth reasons (timeout, 404, 5xx, malformed JSON), configure the static model list and print an info-level event before the success event.

## Testing

Add tests for:

- Model catalog completeness (six curated aliases, exact OpenRouter slugs, all assigned to `managed:openrouter`).
- Env resolution for `OPENROUTER_API_KEY`.
- Config writes for the single OpenRouter managed provider.
- All six curated model aliases are created.
- Default model selection prefers `openrouter/openai/gpt-5.2`.
- `401` and `403` model discovery failures do not save the key.
- Non-auth model discovery failures fall back to the static official model list with an info event before success.
- Override-without-add: a discovery response containing both a known curated slug and an unknown extra slug results in only the curated slug being kept (with overridden context_length / display_name) — the extra slug is dropped.
- API keys are not included in event messages or JSON output.
- OpenRouter logout removes only OpenRouter providers/models.
- CLI parsing for `pythinker login --openrouter` and `pythinker logout --openrouter`.
- Shell routing for `/login openrouter` and `/logout openrouter`.

All tests must mock network calls.

Provider construction (`openai_legacy` at custom base URL) is pre-verified by OpenCode Go's Task 6.

## Provider chooser update

Append `OpenRouter` as the next sequential option in the `/login` shell chooser. After this change (assuming DeepSeek and Anthropic already landed) the chooser exposes 8 options:

```
1. OpenAI ChatGPT (browser)
2. OpenAI ChatGPT (device code)
3. OpenAI API key
4. OpenCode Go
5. MiniMax
6. DeepSeek
7. Anthropic
8. OpenRouter
```

## Non-goals

- Do not auto-add models discovered from `/v1/models` beyond the six curated aliases. Override-only.
- Do not configure OpenRouter-provider-specific routing parameters (`provider.order`, `provider.allow_fallbacks`, etc.) — out of scope; users who need these can edit `config.toml`.
- Do not add OpenRouter ranking/attribution headers (`HTTP-Referer`, `X-OpenRouter-Title`).
- Do not configure OpenRouter's `openrouter/auto` model as the default (users opt in via the catalog; default stays on a deterministic vendor model).
- Do not configure free-tier-only models in the curated catalog.
- Do not change any existing login or logout behavior.
- Do not require the OpenRouter SDK; the existing `openai_legacy` provider wrapper is sufficient.
