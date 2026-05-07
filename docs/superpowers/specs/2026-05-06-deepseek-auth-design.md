# DeepSeek Auth Design

## Goal

Add DeepSeek as a managed provider in Pythinker Code so users with a DeepSeek API key can configure the provider from the CLI and use the current DeepSeek V4 model family (V4-Pro and V4-Flash).

This change is limited to DeepSeek's OpenAI-compatible chat-completions API for the V4 model family. It does not configure DeepSeek's Anthropic-compatible endpoint, does not include legacy `deepseek-chat` / `deepseek-reasoner` aliases (deprecated 2026-07-24), and does not configure any non-DeepSeek provider.

## Context

Pythinker already has managed setup for OpenAI, OpenCode Go, and MiniMax. DeepSeek follows the same pattern: a single API key authorizes a chat-completions endpoint, and the existing Pythinker `openai_legacy` provider type covers the wire format.

DeepSeek exposes both an OpenAI-compatible endpoint at `https://api.deepseek.com/v1` and an Anthropic-compatible endpoint at `https://api.deepseek.com/anthropic`. We configure only the OpenAI-compatible endpoint because:

- Every DeepSeek V4 model is exposed on the OpenAI-compatible path, including thinking mode (via `reasoning_effort`).
- A single managed provider keeps the model alias namespace single-routed and simpler.
- Users who want native Anthropic streaming with `thinking` blocks can edit `config.toml` directly.

## User-facing behavior

Add a dedicated DeepSeek setup mode without changing any existing login flow.

CLI:

```sh
pythinker login --deepseek
pythinker logout --deepseek
```

Shell:

```text
/login deepseek
/logout deepseek
```

The command prompts for the DeepSeek API key (hidden input), validates it via best-effort model discovery, writes the managed provider and model aliases, and reloads the shell after successful setup.

The setup must also support an environment-provided key. If a key is not provided interactively, use:

1. `DEEPSEEK_API_KEY` (only documented DeepSeek env var).

The dedicated DeepSeek mode must not change `pythinker login`, `pythinker login --browser`, `pythinker login --headless`, `pythinker login --api-key`, `pythinker login --opencode-go`, `pythinker login --minimax`, `/login`, or any existing `/login <mode>` route.

## Provider configuration

Provider family ID:

```text
deepseek
```

Configure ONE managed provider entry:

- `managed:deepseek` — type `openai_legacy`, base URL `https://api.deepseek.com/v1`.

Model aliases follow the project convention:

```text
deepseek/<short-suffix>
```

The `LLMModel.model` field stores the EXACT API model ID (e.g. `deepseek-v4-pro`); the alias uses a lowercase short form (`deepseek/v4-pro`).

## Models

Configure exactly two current text models:

| Alias | API model ID | Provider type | Display name | Max context |
| --- | --- | --- | --- | --- |
| `deepseek/v4-pro` | `deepseek-v4-pro` | `openai_legacy` | DeepSeek V4 Pro | 128_000 |
| `deepseek/v4-flash` | `deepseek-v4-flash` | `openai_legacy` | DeepSeek V4 Flash | 128_000 |

Legacy `deepseek-chat`, `deepseek-reasoner`, and any `-thinking`-suffixed variants are intentionally excluded (the `reasoning_effort` request parameter handles thinking on the canonical V4 model IDs).

Set the default model to `deepseek/v4-pro` after successful setup. If `v4-pro` is not present in the discovered list, fall back to the first configured DeepSeek model (preserving the static catalog order above).

If model discovery returns numeric `context_length` values for either of the two official models, prefer that discovered value over the static 128,000 default.

## Model discovery

DeepSeek exposes `https://api.deepseek.com/v1/models` (OpenAI-compatible listing). The setup flow must:

1. Try to list models from `https://api.deepseek.com/v1/models` with `Authorization: Bearer <api key>`.
2. If the endpoint returns a usable list, map known IDs (`deepseek-v4-pro`, `deepseek-v4-flash`) into the static catalog above, optionally overriding `max_context_size` and `display_name`.
3. If listing fails with `404`, non-JSON, timeout, or a non-auth server error, fall back to the static catalog and emit an `info` event before success.
4. If listing fails with `401` or `403`, do not save the key. Emit an `error` event with `"Invalid DeepSeek API key; the key was not saved."`.

Discovery is best-effort. Tests must mock all network calls.

## Validation

API-key validation must avoid generation requests.

Preferred validation order:

1. `GET https://api.deepseek.com/v1/models` with `Authorization: Bearer <key>`.
2. If unavailable for non-auth reasons, accept the key and configure the static model list with an info-level event.
3. If the response is `401` or `403`, show a clear error and do not save the key.

Do not log or display the API key. JSON event output must redact secrets.

## Data flow

CLI setup:

1. User runs `pythinker login --deepseek`.
2. Pythinker reads `DEEPSEEK_API_KEY` from the environment or prompts for one (hidden input).
3. Pythinker attempts model discovery and validates auth failures.
4. Pythinker writes the managed provider entry and the two DeepSeek model aliases.
5. Pythinker sets `default_model` to `deepseek/v4-pro` or the first configured DeepSeek model.
6. Pythinker reports success with the default model.

Shell setup:

1. User runs `/login deepseek`.
2. Pythinker prompts for the API key when no environment key exists.
3. Pythinker renders setup events through the existing OAuth event renderer.
4. On success, Pythinker tracks a `login` event with provider `deepseek`, clears the console, and reloads the shell.

## Logout behavior

Existing OpenAI, OpenCode Go, and MiniMax logout behavior must not remove DeepSeek providers. Add both user-facing logout options:

- `pythinker logout --deepseek`
- `/logout deepseek`

Logout removes the `managed:deepseek` provider entry and every model whose `provider` field equals that key. If `default_model` points to a removed DeepSeek model, set `default_model` to the first remaining configured model or clear it (`""`).

## Error handling

- If the user enters an empty API key and no environment key exists, print `DeepSeek API key is required.`
- If model discovery returns `401` or `403`, print `Invalid DeepSeek API key; the key was not saved.`
- If model discovery is unavailable for non-auth reasons (timeout, 404, 5xx, malformed JSON), configure the static model list and print an info-level event before the success event.

## Testing

Add tests for:

- Model catalog completeness (two aliases, exact API IDs, all assigned to `managed:deepseek`).
- Env resolution for `DEEPSEEK_API_KEY`.
- Config writes for the single DeepSeek managed provider.
- All current model aliases are created.
- Default model selection prefers `deepseek/v4-pro`.
- `401` and `403` model discovery failures do not save the key.
- Non-auth model discovery failures fall back to the static official model list with an info event before success.
- API keys are not included in event messages or JSON output.
- DeepSeek logout removes only DeepSeek providers/models and leaves OpenAI, OpenCode Go, and MiniMax providers intact.
- CLI parsing for `pythinker login --deepseek` and `pythinker logout --deepseek`.
- Shell routing for `/login deepseek` and `/logout deepseek`.

All tests must mock network calls. No tests should call real DeepSeek endpoints.

Provider construction (`create_llm` for the `openai_legacy` provider type at a non-default base URL) was verified during the OpenCode Go work in `tests/core/test_openai_provider.py::test_create_llm_supports_opencode_go_openai_provider`. That coverage is sufficient; no additional provider-construction test is required for DeepSeek.

## Provider chooser update

Append `DeepSeek` as option 6 in the `/login` shell chooser. After this change the chooser exposes 6 options:

```
1. OpenAI ChatGPT (browser)
2. OpenAI ChatGPT (device code)
3. OpenAI API key
4. OpenCode Go
5. MiniMax
6. DeepSeek
```

## Non-goals

- Do not configure the DeepSeek Anthropic-compatible endpoint (`https://api.deepseek.com/anthropic`).
- Do not add legacy `deepseek-chat` or `deepseek-reasoner` aliases.
- Do not configure DeepSeek non-text models (none are documented at this time, but explicitly out of scope if added later).
- Do not change any existing login or logout behavior.
- Do not require an external CLI binary.
