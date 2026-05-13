# Telemetry & error reporting

Pythinker Code emits anonymous telemetry to help us spot crashes, regressions
and silent failures. This page documents exactly what's collected, where it's
sent, and how to opt out.

## Backends

| Stack | Endpoint | What it carries |
|---|---|---|
| **OpenTelemetry → SigNoz** (logs / metrics / traces) | `https://otel.pythinker.com` | Structured events emitted via `track(...)`, periodic metric snapshots, and (when sampled) trace spans. |
| **Sentry-compatible Bugsink** (errors) | `https://errors.pythinker.com/1` | Unhandled exceptions, asyncio task failures, and explicitly-reported handled exceptions. |
| **Hosted feedback endpoint** | `<platform>/feedback` | Free-form text submitted via the `/feedback` slash command. |

The OTel collector and Bugsink are pythinker-operated. The OTel ingest token
embedded in the binary is public by design (same pattern used by Datadog RUM
and PostHog public keys); rate limiting and PII scrubbing happen server-side
at the collector edge.

## What's collected

### OTel events

Emitted from `pythinker_code.telemetry.track(event_name, **properties)`. Every
event carries:

| Field | Source |
|---|---|
| `event_id` | UUIDv4 generated client-side. |
| `device_id` | Stable per-install hash (no user identity). |
| `session_id` | Per-process random ID. |
| `event` | The event name (e.g. `session_started`, `feedback_submitted`, `error`). |
| `properties.*` | Primitive enum-like attributes the call site passed. |
| `context.*` | Static attributes added by the sink (version, OS, Python, locale). |
| `timestamp` | Wall-clock time on the client. |

Property values **must** be primitives (bool/int/float/str/None). The call
sites are coded to never pass user input, file paths, or code snippets.

### Sentry events

Emitted from `pythinker_code.telemetry.sentry.capture_exception(exc)` (and
implicitly via `sys.excepthook` and the asyncio exception handler). Carries:

- Exception class, message, and stack trace.
- Release tag (`pythinker-code@<version>`).
- Lifecycle phase (`startup` / `runtime` / `shutdown`).
- A handful of static tags (`ui_mode`, `model`).

The `before_send` hook in `telemetry/sentry.py`:

- Strips file-path prefixes above `site-packages/` or `pythinker_code/`,
  collapsing them to `<env>/` so home directories don't leak.
- Removes `server_name` (which is usually the user's hostname).
- Disables `send_default_pii` and request-frame variable capture.

### Reported handled errors

`pythinker_code.telemetry.errors.report_handled_error(exc, *, site, tool=None, **attrs)`
is the canonical helper for any `except Exception:` block that catches an
exception, renders a graceful failure to the user (`ToolError`, red TUI line,
warning), and currently has no monitoring visibility.

It:

1. Emits an OTel `error` event with `{site, exc_class, tool, **attrs}`.
2. Calls `sentry.capture_exception(exc)`.

Both calls are wrapped in `contextlib.suppress(Exception)` so monitoring can
never break the host program.

Common `site` values (extend with care — these are dashboard query keys):

| Site | Where |
|---|---|
| `tool.read` | `tools/file/read.py` |
| `tool.read_media` | `tools/file/read_media.py` |
| `tool.write` | `tools/file/write.py` |
| `tool.replace` | `tools/file/replace.py` |
| `tool.glob` | `tools/file/glob.py` |
| `tool.grep` | `tools/file/grep_local.py` |
| `tool.shell.exec` | `tools/shell/__init__.py` (foreground command) |
| `tool.shell.background_start` | `tools/shell/__init__.py` (background spawn) |
| `tool.agent.foreground` | `tools/agent/__init__.py` |
| `tool.ask_user` | `tools/ask_user/__init__.py` |
| `tool.plan.enter` | `tools/plan/enter.py` |
| `tool.plan.exit` | `tools/plan/__init__.py` |
| `auth.keyring.read` | `auth/oauth.py` (`_load_from_keyring`) |
| `auth.oauth.device_authorize` | `auth/oauth.py` (device-code request) |
| `auth.oauth.device_poll` | `auth/oauth.py` (device-code poll loop) |
| `auth.models.fetch` | `auth/oauth.py` (`list_models` post-login) |
| `auth.oauth.refresh` | `auth/oauth.py` (foreground token refresh) |
| `auth.oauth.refresh.background` | `auth/oauth.py` (background refresh loop) |
| `auth.platforms.refresh.pre_sync` | `auth/platforms.py` (pre-sync refresh) |
| `auth.platforms.refresh.after_401` | `auth/platforms.py` (refresh-on-401) |
| `auth.platforms.sync` | `auth/platforms.py` (model sync fallback) |
| `auth.openai.discover_chatgpt_models` | `auth/openai.py` |
| `auth.openai.browser_login` | `auth/openai.py` |
| `auth.openai.device_start` | `auth/openai.py` |
| `auth.openai.device_poll` | `auth/openai.py` |
| `soul.btw.execute` | `soul/btw.py` (side question) |
| `soul.btw.run_wire` | `soul/btw.py` (wire-based side question) |
| `soul.toolset.register_external` | `soul/toolset.py` (external tool registration) |
| `soul.toolset.mcp.connect` | `soul/toolset.py` (MCP server connect) |
| `soul.toolset.mcp.call` | `soul/toolset.py` (MCP tool call) |
| `soul.toolset.mcp.call.timeout` | `soul/toolset.py` (MCP tool call — timeout-classified) |
| `soul.toolset.external_tool` | `soul/toolset.py` (`WireExternalTool`) |
| `soul.injection.get` | `soul/pythinkersoul.py` (injection provider get) |
| `soul.injection.on_context_compacted` | `soul/pythinkersoul.py` |
| `soul.injection.on_auto_changed` | `soul/pythinkersoul.py` |
| `soul.context.compact` | `soul/pythinkersoul.py` (compaction inside step) |
| `soul.step.error` | `soul/pythinkersoul.py` (any step exception) |
| `soul.chat.recover` | `soul/pythinkersoul.py` (provider recovery) |
| `acp.session.prompt` | `acp/session.py` |
| `acp.session.approval` | `acp/session.py` |
| `acp.host.terminal` | `acp/host.py` |
| `hooks.runner` | `hooks/runner.py` |
| `hooks.engine.run` | `hooks/engine.py` (top-level fail-open wrap) |
| `hooks.engine.triggered_cb` | `hooks/engine.py` (HookTriggered callback) |
| `hooks.engine.resolved_cb` | `hooks/engine.py` (HookResolved callback) |
| `hooks.engine.wire` | `hooks/engine.py` (wire hook dispatch) |
| `subagents.run.soul` | `subagents/runner.py` (soul-run wrapper) |
| `subagents.run.background` | `subagents/runner.py` (background failure) |

When you add a new catch site, prefer reusing an existing prefix and add a
specific suffix. Do not put free-form messages in `site` — it must remain a
small, stable enumeration for dashboard slicing.

### `/feedback` slash command

Distinct from automatic telemetry. The user types feedback explicitly; it is
POSTed to the configured feedback endpoint along with `session_id`, version,
OS, and current model. No code or file context is attached.

Endpoint resolution order:

1. `PYTHINKER_FEEDBACK_URL` environment variable.
2. `feedback.endpoint_url` in `config.toml`.
3. The built-in Pythinker platform endpoint.

When using a configured endpoint, set `PYTHINKER_FEEDBACK_API_KEY` or
`feedback.api_key` to send an `Authorization: Bearer ...` header. `feedback.custom_headers`
can add static headers. The built-in Pythinker provider remains supported but
OAuth is no longer required for self-hosted/dev feedback routing.

### `/report-error` slash command

A user-invoked complement to automatic Sentry/OTel capture, designed for the
case where the user *knows* something is wrong but the code path didn't
raise — or where they want to attach a comment to a recently-seen failure.

The runtime keeps a **process-local ring buffer** of the last 10 errors that
were forwarded through `report_handled_error` (`pythinker_code/telemetry/errors.py`).
Each entry stores: `timestamp`, `site`, `exc_class`, a 200-char-truncated
`message`, and the optional `tool` name. The buffer is in-memory only — it
does not persist across processes and does not back the OTel/Sentry pipeline
(those already received the full event when it occurred).

When the user runs `/report-error`:

1. The TUI prints the buffer's contents (site + class + tool).
2. The user types a free-form description and hits enter.
3. The runtime POSTs to `<platform>/feedback` with `type=error`, the comment,
   the same context as `/feedback` (version, OS, model, session_id), and a
   `recent_errors[]` array constructed from the ring buffer.
4. On success, the buffer is cleared.

If submission is unavailable or fails, the slash falls back to opening the
GitHub issue tracker in a browser.

## Opting out

Set either of the following before launching `pythinker`:

- `PYTHINKER_DISABLE_TELEMETRY=1` — kills both Sentry and OTel emission for
  the process. The `/feedback` slash command is **not** affected (it only
  fires on explicit user invocation).
- `PYTHINKER_FEEDBACK_URL` — overrides where explicit `/feedback` and
  `/report-error` submissions are sent.
- `PYTHINKER_FEEDBACK_API_KEY` — optional bearer token for that feedback endpoint.
- `config.telemetry = false` in your config file (TOML) — same effect.

Override individual endpoints when running your own collectors:

| Variable | Default |
|---|---|
| `PYTHINKER_SENTRY_DSN` | `https://...@errors.pythinker.com/1` |
| `PYTHINKER_OTEL_ENDPOINT` | `https://otel.pythinker.com` |
| `PYTHINKER_OTEL_TOKEN` | (embedded) |
| `PYTHINKER_OTEL_TRACE_SAMPLE_RATE` | `1.0` (always-on) |

`PYTHINKER_OTEL_TRACE_SAMPLE_RATE` accepts a float in `[0.0, 1.0]`. Values are
clamped; malformed input falls back to the default. Sampling is `ParentBased`
on top of `TraceIdRatioBased`, so a parent's sample decision (e.g. an
upstream ACP/wire request that already chose to sample) is honored —
otherwise the rate decides at the root.

## Spans

Currently emitted (when traces are sampled):

| Span | Where | Key attributes |
|---|---|---|
| `pythinker.turn` | `soul/pythinkersoul.py` | `session.id`, `agent.role`, `model`, `plan_mode`, `turn.stop_reason`, `turn.step_count` |
| `pythinker.llm` | `soul/pythinkersoul.py` | `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.id`, `llm.tool_calls` |
| `pythinker.tool_call` | `soul/toolset.py` | `tool.name`, `tool.success`, `tool.error_type` |
| `pythinker.mcp.call` | `soul/toolset.py` | `mcp.server`, `mcp.tool`, `mcp.timeout_ms`, `mcp.is_error` |

## What's *not* collected

- Prompts, completions, or any LLM input/output.
- File contents, paths above `site-packages/` (Sentry path-scrubbing), or
  command arguments.
- Local environment variable values.
- The user's hostname or username.
- Anything from the `/feedback` slash command unless the user explicitly
  typed it.
