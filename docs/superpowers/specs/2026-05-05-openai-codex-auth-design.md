# OpenAI Codex-Compatible Auth Design

## Goal

Replace user-facing Pythinker account authentication with OpenAI authentication so Pythinker uses OpenAI/Codex as the default account setup path.

Pythinker must support three OpenAI setup flows:

- ChatGPT browser login for Codex-capable ChatGPT accounts.
- ChatGPT headless login using Codex-compatible device-code authentication.
- OpenAI API key setup using the standard OpenAI API.

The old Pythinker OAuth flow must not remain visible through `pythinker login`, `/login`, or `/setup`.

## Context

Pythinker currently has two user-facing auth/setup paths:

- `pythinker login` and `/login` run Pythinker OAuth in `src/pythinker_code/auth/oauth.py` against `auth.pythinker.com`.
- `/setup` configures API-key platforms through `src/pythinker_code/ui/shell/setup.py` and the platform picker in `src/pythinker_code/auth/platforms.py`.

Those flows should be replaced at the user-facing layer. OpenAI/Codex login becomes the normal path, and OpenAI API key setup becomes the fallback path for users who do not use ChatGPT managed auth.

OpenAI API documentation uses API-key authentication for direct API calls. OpenAI Codex CLI also supports ChatGPT managed auth for Codex usage with ChatGPT plans through browser and device-code flows. Pythinker should follow Codex-compatible behavior rather than inventing a separate OpenAI OAuth protocol.

## User-Facing Behavior

`pythinker login` becomes the default OpenAI/Codex login entrypoint. With no flags, it starts browser-based ChatGPT/Codex login.

CLI examples:

```sh
pythinker login
pythinker login --browser
pythinker login --headless
pythinker login --api-key
```

Shell slash examples:

```text
/login
/login browser
/login headless
/login api-key
/setup
```

The commands mean:

- `pythinker login`, `pythinker login --browser`, `/login`, and `/login browser`: Start Codex-compatible ChatGPT browser login, open the auth URL, receive the localhost callback, store tokens, discover models, and configure OpenAI as default.
- `pythinker login --headless` and `/login headless`: Start Codex-compatible device-code login, print verification URL and user code, poll until authorized, store tokens, discover models, and configure OpenAI as default.
- `pythinker login --api-key`, `/login api-key`, and `/setup`: Prompt for an OpenAI API key, validate it with the OpenAI models endpoint, store it in Pythinker config, discover models, and configure OpenAI as default.

`/setup` should no longer open a generic platform picker. It should route to OpenAI API-key setup because OpenAI is the default provider.

## Removed User-Facing Behavior

The implementation must remove Pythinker account OAuth from normal user-facing login/setup:

- `pythinker login` must not call `login_pythinker_code`.
- `/login` must not offer or select the `pythinker-code` platform.
- `/setup` must not present the old platform picker.
- Login/help text must not tell users to authenticate with a Pythinker account.

Existing Pythinker OAuth internals may be deleted during implementation if no tests or runtime code need them. If deletion is too large for the first implementation pass, the code may remain temporarily unused, but no visible command should invoke it.

## Architecture

Add a focused OpenAI auth module, for example `src/pythinker_code/auth/openai.py`, to keep OpenAI/Codex-specific logic separate from the old Pythinker OAuth implementation.

The module should expose event-driven functions compatible with the current `OAuthEvent` rendering style:

- `login_openai_browser(config) -> AsyncIterator[OAuthEvent]`
- `login_openai_headless(config) -> AsyncIterator[OAuthEvent]`
- `login_openai_api_key(config, api_key: str | None = None) -> AsyncIterator[OAuthEvent]`
- `logout_openai(config) -> AsyncIterator[OAuthEvent]`

The CLI and shell UI should render these events with the existing JSON-line and terminal status behavior. This preserves the current operational shape while replacing the underlying account provider.

## OpenAI/Codex Auth Source Of Truth

The implementation plan must begin by checking the current OpenAI Codex source/docs for auth details. Current Codex app-server docs describe these login modes:

- `account/login/start` with `type: "apiKey"` for API-key login.
- `account/login/start` with `type: "chatgpt"` for browser ChatGPT managed login.
- `account/login/start` with `type: "chatgptDeviceCode"` for device-code login.

The implementation should use the current Codex-compatible endpoints, request payloads, token response shape, and refresh behavior found during that research step. Tests must mock those HTTP interactions and must not hit real OpenAI endpoints.

## Credential Storage

Use Pythinker’s existing credential storage directory under `get_share_dir()/credentials`.

Credential keys:

- `oauth/openai-chatgpt` for ChatGPT managed auth tokens.
- OpenAI API keys remain in `config.toml` as `LLMProvider.api_key`, matching existing API-key provider behavior.

The ChatGPT token file should preserve enough Codex-compatible fields to support refresh and account metadata. Access tokens, refresh tokens, and API keys must not be written into logs or displayed in terminal output.

## Provider Configuration

After successful OpenAI auth, Pythinker should configure OpenAI as the default provider and model.

For API-key login:

- Provider key: `managed:openai`.
- Provider type: `openai_responses`.
- Base URL: `https://api.openai.com/v1`.
- API key: user-provided key.
- Model source: list `https://api.openai.com/v1/models` with `Authorization: Bearer <api key>`.

For ChatGPT managed auth:

- Provider key: `managed:openai-chatgpt`.
- Provider type: a new or extended OpenAI/Codex-compatible provider if ChatGPT managed tokens cannot be used with the existing `openai_responses` provider.
- Store `oauth=OAuthRef(storage="file", key="oauth/openai-chatgpt")` on the provider.
- Store no raw ChatGPT access token in `config.toml`.
- Configure the default model to a Codex/GPT model exposed by the authenticated account.

The implementation must verify whether the existing `OpenAIResponses` provider can use ChatGPT managed tokens directly. If it cannot, add a distinct provider type rather than overloading `openai_responses` incorrectly.

## Model Selection

Model discovery determines which models are configured. Pythinker should write one `LLMModel` entry per discovered model, then set `default_model` using this preference order:

1. First Codex/GPT coding model exposed by the account.
2. First GPT-5-class model.
3. First available GPT model.
4. First model returned by the discovery endpoint.

For API-key login, if the models endpoint returns no usable models, the API key must not be saved as the default provider. For ChatGPT managed login, keep valid tokens but do not overwrite `default_model` if model discovery fails.

## Data Flow

Browser login:

1. User runs `pythinker login`, `pythinker login --browser`, `/login`, or `/login browser`.
2. Pythinker starts the Codex-compatible browser auth request.
3. Pythinker opens the returned auth URL in the default browser.
4. The local callback receives the auth result.
5. Pythinker exchanges auth data for tokens.
6. Pythinker stores tokens, refresh metadata, and account metadata.
7. Pythinker discovers available models and writes default provider/model config.

Headless login:

1. User runs `pythinker login --headless` or `/login headless`.
2. Pythinker starts the Codex-compatible device-code auth request.
3. Pythinker prints the verification URL and user code.
4. Pythinker polls until success, timeout, or denial.
5. Pythinker stores tokens and configures provider/model on success.

API-key setup:

1. User runs `pythinker login --api-key`, `/login api-key`, or `/setup`.
2. Pythinker prompts for a key if none was provided.
3. Pythinker validates the key by listing models.
4. Pythinker saves the managed OpenAI provider and discovered models.
5. Pythinker sets the selected OpenAI model as the default.

## Logout Behavior

`pythinker logout` and `/logout` should log out of the active OpenAI-managed provider:

- For ChatGPT managed auth, delete `oauth/openai-chatgpt` credentials and remove the managed ChatGPT provider/models from config.
- For OpenAI API-key auth, remove the managed OpenAI provider/models from config.
- If the default model pointed at the removed provider, clear it or switch to another configured model.

Logout should not call the old Pythinker OAuth logout path.

## Error Handling

- If browser opening fails, print the URL and continue waiting for the local callback.
- If device-code auth expires, show a clear message and allow the user to retry by rerunning login.
- If device-code auth is disabled for the ChatGPT workspace, print the provider error and recommend browser login or API-key setup.
- If model discovery fails after ChatGPT auth, keep tokens but do not overwrite the current default model.
- If API-key validation returns 401, do not save the key.
- If a ChatGPT token refresh fails with unauthorized, clear the active token cache and tell the user to run `pythinker login` again.
- If ChatGPT managed auth is unavailable in the current environment, `pythinker login --api-key` and `/setup` must remain usable.

## Testing

Add tests for:

- CLI parsing for default browser login, `--browser`, `--headless`, and `--api-key`.
- `/login`, `/login browser`, `/login headless`, `/login api-key`, and `/setup` routing.
- `pythinker login` no longer calls `login_pythinker_code`.
- `/login` and `/setup` no longer open the old platform picker.
- Event rendering for browser, headless, and API-key flows.
- API-key validation success and failure.
- Config writes for managed OpenAI provider/model.
- Token save/load/delete for `oauth/openai-chatgpt`.
- Refresh failure behavior.
- Logout removes OpenAI managed auth and does not call Pythinker OAuth logout.

Use mocked HTTP responses for auth, token refresh, and model discovery. Do not hit real OpenAI endpoints in tests.

## Non-Goals

- Do not scrape ChatGPT web sessions or browser cookies.
- Do not keep Pythinker account OAuth visible in user-facing login/setup.
- Do not store OpenAI API keys outside existing config mechanisms.
- Do not guarantee all ChatGPT subscription tiers expose the same models; model discovery determines what is configured.
- Do not require the external `codex` binary at runtime.
