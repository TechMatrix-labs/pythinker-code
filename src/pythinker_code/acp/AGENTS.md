# ACP Integration Notes (pythinker-code)

## Protocol summary (ACP overview)
- ACP is JSON-RPC 2.0 with request/response methods plus one-way notifications.
- Typical flow: `initialize` -> optional `authenticate` -> `session/new` or `session/load`
  -> `session/prompt`
  with `session/update` notifications and optional `session/cancel`.
- Clients provide `session/request_permission` and optional terminal/filesystem methods.
- All ACP file paths must be absolute; line numbers are 1-based.

## Entry points and server modes
- **Deprecated single-session server**: `PythinkerCLI.run_acp()` uses `ACP` -> `ACPServerSingleSession`.
  - Code: `src/pythinker_code/app.py`, `src/pythinker_code/ui/acp/__init__.py`.
  - Used when running CLI with `--acp` UI mode; every ACP method now raises a deprecation error.
- **Multi-session server**: `acp_main()` runs `ACPServer` with `use_unstable_protocol=True`.
  - Code: `src/pythinker_code/acp/__init__.py`, `src/pythinker_code/acp/server.py`.
  - Exposed via the `pythinker acp` command in `src/pythinker_code/cli/__init__.py`.

## Capabilities advertised
- `prompt_capabilities`: `embedded_context=True`, `image=True`, `audio=False`.
- `mcp_capabilities`: `http=True`, `sse=False`.
- Multi-session: `load_session=True`, `session_capabilities.list` and `session_capabilities.resume` supported.
- `auth_methods` advertises terminal auth for `pythinker login`.

## Session lifecycle (implemented behavior)
- `session/new`
  - Multi-session: creates a persisted `Session`, builds `PythinkerCLI`, stores `ACPSession`.
  - Sends `AvailableCommandsUpdate` for slash commands on session creation.
  - MCP servers passed by ACP are converted via `acp_mcp_servers_to_mcp_config`.
- `session/load`
  - Multi-session only: loads by `Session.find`, then builds `PythinkerCLI` and `ACPSession`.
  - No history replay yet (TODO).
- `session/list`
  - Multi-session only: lists sessions via `Session.list`, no pagination.
- `session/resume`
  - Multi-session only: loads the session if needed and returns current mode/model state.
- `session/set_mode`
  - Multi-session only: accepts only `default`.
- `session/set_model`
  - Multi-session only: switches the session LLM and persists default model/thinking settings.
- `session/prompt`
  - Uses `ACPSession.prompt()` to stream updates and produce a `stop_reason`.
  - Stop reasons: `end_turn`, `max_turn_requests`, `cancelled`.
- `session/cancel`
  - Sets the per-turn cancel event to stop the prompt.

## Streaming updates and content mapping
- Text chunks -> `AgentMessageChunk`.
- Think chunks -> `AgentThoughtChunk`.
- Tool calls:
  - Start -> `ToolCallStart` with JSON args as text content.
  - Streaming args -> `ToolCallProgress` with updated title/args.
  - Results -> `ToolCallProgress` with `completed` or `failed`.
  - Tool call IDs are prefixed with turn ID to avoid collisions across turns.
- Plan updates:
  - `TodoDisplayBlock` is converted into `AgentPlanUpdate`.
- Available commands:
  - `AvailableCommandsUpdate` is sent right after session creation.

## Prompt/content conversion
- Incoming prompt blocks:
  - Supported: `TextContentBlock`, `ImageContentBlock` (converted to data URL).
  - Unsupported types are logged and ignored.
- Tool result display blocks:
  - `DiffDisplayBlock` -> `FileEditToolCallContent`.
  - `HideOutputDisplayBlock` suppresses tool output in ACP (used by terminal tool).

## Tool integration and permission flow
- ACP sessions use `ACPHost` to route filesystem reads/writes through ACP clients.
- If the client advertises `terminal` capability, the `Shell` tool is replaced by an
  ACP-backed `Terminal` tool.
  - Uses ACP `terminal/create`, waits for exit, streams `TerminalToolCallContent`,
    then releases the terminal handle.
- Approval requests in the core tool system are bridged to ACP
  `session/request_permission` with allow-once/allow-always/reject options.

## Current gaps / not implemented
- `fork_session` is not implemented.
- `ext_method` / `ext_notification` for custom ACP extensions are stubbed.
- Deprecated single-session `--acp` rejects all methods and exists only to report migration guidance.
- `session/load` still has no history replay.

## Filesystem (ACP client-backed)
- When the client advertises `fs.readTextFile` / `fs.writeTextFile`, `ACPHost` routes
  reads and writes through ACP `fs/*` methods.
- `ReadFile` uses `HostPath.read_lines`, which `ACPHost` implements via ACP reads.
- `ReadMediaFile` uses `HostPath.read_bytes` to load image/video payloads through ACP reads.
- `WriteFile` uses `HostPath.read_text/write_text/append_text` and still generates diffs
  and approvals in the tool layer.

## Zed-specific notes (as of current integration)
- Terminal auth advertises `pythinker login`; `authenticate` verifies that login completed.
- External agent clients should use `pythinker acp`, not deprecated `pythinker --acp`.
