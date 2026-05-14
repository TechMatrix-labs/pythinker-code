---
Author: Mohamed Elkholy
Updated: 2026-05-13
Status: Draft
---

# PLIP-9: Pythinker SDK Professionalization

## Motivation

Pythinker SDK is currently a thin re-export package over `pythinker-core` with a short README and smoke tests. That is useful for early adopters, but it does not yet feel like a complete SDK: users must assemble provider setup, conversation loops, tool-result messages, and MCP tool wiring themselves.

This PLIP proposes a surgical enhancement path that keeps `pythinker-core` as the low-level primitive layer while making `pythinker-sdk` the ergonomic developer-facing package.

## Evidence and validation

### Repository evidence

- `sdks/pythinker-sdk/src/pythinker_sdk/__init__.py` re-exports `Pythinker`, `Message`, `generate`, `step`, tool classes, and errors from `pythinker-core`.
- `sdks/pythinker-sdk/README.md` includes basic generation, streaming, video upload, and a one-step tool-calling example.
- SDK tests are limited to public-import smoke coverage and one mocked chat-completion generation test.
- CLI MCP integration already exists in `src/pythinker_code/soul/toolset.py`, but it is tied to CLI runtime approval, telemetry, hooks, and `fastmcp` client lifecycle. The SDK should not import CLI runtime modules.
- `packages/pythinker-core/src/pythinker_core/tooling/mcp.py` already converts MCP content blocks into Pythinker message content parts. The SDK should reuse this low-level converter where possible.

### Context7 MCP Python SDK validation

Validated against `/modelcontextprotocol/python-sdk/v1.12.4` documentation:

- Current client lifecycle is `ClientSession(read, write)` followed by `await session.initialize()`.
- Stdio transport uses `StdioServerParameters` plus `stdio_client(...)`.
- Streamable HTTP transport uses `streamablehttp_client(url)` and returns read/write streams plus a session-id accessor.
- Tool discovery uses `await session.list_tools()` and reads `tools_result.tools`.
- Tool invocation uses `await session.call_tool(name, arguments={...})`.
- Tool results may include text content, structured JSON content, embedded resources, images, and error state; the SDK adapter must not assume text-only results.

### Tavily search validation

Validated with current Tavily web/MCP search results:

- Tavily MCP server exposes search, extract, crawl, map, and research tools.
- `tavily_search` supports `query`, `search_depth`, `topic`, `max_results`, `include_answer`, `include_raw_content`, domain filters, images, dates/time ranges, and related options.
- Search depth values include `basic`, `advanced`, `fast`, and `ultra-fast`; `advanced` can cost more but returns richer chunks.
- Tavily has a remote MCP server and API-key/OAuth configuration patterns. SDK examples should demonstrate environment-variable based configuration without embedding secrets.

## Goals

1. Make the SDK pleasant for common agent workflows without hiding the core primitives.
2. Add MCP client-tool integration to the SDK without depending on `pythinker_code` CLI internals.
3. Provide a production-quality Tavily MCP example that demonstrates current MCP patterns.
4. Improve docs, examples, and tests enough that the SDK can be adopted independently.
5. Preserve public compatibility for existing `from pythinker_sdk import ...` imports.

## Non-goals

- No hosted endpoints, telemetry, or new external services.
- No CLI runtime approval, hook, or wire integration inside the SDK.
- No broad refactor of `pythinker-core` provider internals.
- No dependency upgrade unless required by the SDK feature and explicitly reviewed.
- No secrets in examples, tests, docs, or fixtures.

## Proposed user-facing API

### 1. Ergonomic client

Add `pythinker_sdk.client`:

```python
from pythinker_sdk import PythinkerClient

client = PythinkerClient.from_env(model="pythinker-ai")
result = await client.generate("Who are you?", system_prompt="You are helpful.")
```

Minimum shape:

- `PythinkerClient(...)` wraps `Pythinker` plus default `system_prompt`, tools/toolset, and history helpers.
- `PythinkerClient.from_env(...)` reads `PYTHINKER_API_KEY` and `PYTHINKER_BASE_URL` while allowing explicit overrides.
- `generate(...)` accepts either a string or explicit `Sequence[Message]`.
- `step(...)` delegates to `pythinker_core.step` with configured toolset.
- `run_until_done(...)` loops through tool calls and appends tool-result messages until the assistant returns no tool calls or `max_steps` is reached.

Compatibility: continue exporting all current core classes from `pythinker_sdk.__init__`.

### 2. Conversation helper

Add a small `Conversation` class:

- Owns `history: list[Message]`.
- `add_user(content)` and `add_tool_result(result)` helpers.
- `last_text()` convenience method.
- No persistence or database layer.

This prevents every README example from reimplementing `tool_result_to_message`.

### 3. MCP tool adapter

Add `pythinker_sdk.mcp` using the official MCP Python SDK APIs validated above:

- `MCPServerConfig` dataclass for stdio and streamable HTTP transports.
- `MCPTool` implementing `pythinker_core.tooling.CallableTool`.
- `MCPToolset` implementing or composing `Toolset`/`SimpleToolset`.
- Async context manager lifecycle:

```python
from pythinker_sdk.mcp import MCPServerConfig, MCPToolset

async with MCPToolset.connect([
    MCPServerConfig.streamable_http("tavily", url=tavily_mcp_url),
]) as tools:
    client = PythinkerClient.from_env(toolset=tools)
    result = await client.run_until_done("Search the latest MCP SDK guidance.")
```

Adapter requirements:

- Call `session.initialize()` exactly once per server connection.
- Discover tools with `session.list_tools()`.
- Convert MCP input schemas to `CallableTool` parameters without rewriting schemas.
- Invoke tools with `session.call_tool(name, arguments=kwargs)`.
- Convert text, image, audio, video, embedded-resource, and structured-content results into `ToolOk` or `ToolError`.
- Bound output size with an SDK-level maximum and add a truncation note when exceeded.
- Handle server/tool name collisions by defaulting to stable names such as `server__tool`, while preserving original MCP tool metadata.
- Close sessions/transports via the async context manager.

### 4. Tavily MCP example

Add `sdks/pythinker-sdk/examples/tavily_mcp_agent.py`:

- Reads the remote MCP URL or API key from environment variables.
- Uses the SDK MCP adapter rather than CLI internals.
- Demonstrates `tavily_search` with bounded defaults: `search_depth="advanced"`, `max_results<=5`, `include_answer=True`, `include_raw_content=False`.
- Clearly documents that `advanced` search may cost more and can be changed to `basic`, `fast`, or `ultra-fast`.
- Never prints secrets.

### 5. Documentation polish

Update `sdks/pythinker-sdk/README.md`:

- Add “Quickstart” with `PythinkerClient.from_env`.
- Keep low-level `generate`/`step` examples for advanced users.
- Add “MCP tools” section with stdio and streamable HTTP examples.
- Add “Tavily MCP” section using environment variables.
- Add “Error handling and timeouts” section covering provider and MCP errors.
- Add API stability notes.

## Implementation phases

### Phase 0 — API sketch and tests first

Acceptance criteria:

- Add tests for import compatibility.
- Add tests for `Conversation` tool-result message conversion.
- Add tests for `PythinkerClient.from_env` explicit override precedence.
- Add tests for `run_until_done` using a fake chat provider and fake toolset.

Verification:

```bash
make check-pythinker-sdk && make test-pythinker-sdk
```

### Phase 1 — Client and conversation helpers

Acceptance criteria:

- `PythinkerClient`, `Conversation`, and helper functions are implemented in new SDK modules.
- `pythinker_sdk.__all__` exports the new stable API.
- Existing README examples still work.

Verification:

```bash
make check-pythinker-sdk && make test-pythinker-sdk
```

### Phase 2 — MCP adapter

Acceptance criteria:

- SDK supports stdio and streamable HTTP MCP connections using official MCP Python SDK APIs.
- Tool schemas from MCP are exposed directly to the model.
- Tool results convert through `pythinker_core.tooling.mcp.convert_mcp_content` where possible and gracefully fall back for structured/unsupported content.
- Output truncation is deterministic and tested.
- Connection cleanup is tested.

Verification:

```bash
make check-pythinker-sdk && make test-pythinker-sdk
```

### Phase 3 — Tavily MCP example and docs

Acceptance criteria:

- Tavily example is added under `sdks/pythinker-sdk/examples/`.
- README documents stdio MCP, streamable HTTP MCP, and Tavily search defaults.
- Examples use environment variables and redact secrets.

Verification:

```bash
make check-pythinker-sdk && make test-pythinker-sdk
```

### Phase 4 — Packaging and release readiness

Acceptance criteria:

- `pyproject.toml` includes any new SDK runtime dependencies only if not already available transitively through `pythinker-core`.
- `CHANGELOG.md` has an Unreleased entry for SDK enhancements.
- Build succeeds.

Verification:

```bash
make build
```

## Test matrix

- Unit: `Conversation`, client env config, tool-result message conversion.
- Async unit: `run_until_done`, MCP connect/discover/call/cleanup with mocked sessions.
- Contract: MCP result conversion for text, structured content, image/audio/video resources, errors, and truncation.
- Import compatibility: current public imports plus new API.
- Docs smoke: README examples compile under type checker where feasible.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| SDK duplicates CLI MCP logic | Keep SDK adapter independent, small, and based on official MCP SDK; share only safe core conversion helpers. |
| MCP result formats drift | Tests cover structured content and unsupported content fallback. |
| Tool name collisions | Namespace MCP tools by server by default and document override behavior. |
| Long MCP outputs flood context | Enforce explicit output budget and truncation note. |
| Secret leakage in examples | Use env vars only; never log full URLs if they may contain API keys. |
| Breaking current users | Preserve current exports and add compatibility tests. |

## Open decisions

1. Should the SDK depend directly on `mcp` even though `pythinker-core` already does, or rely on the transitive dependency? Recommendation: add direct SDK dependency for any SDK module that imports `mcp`.
2. Should Tavily remote MCP support OAuth in the first SDK example, or start with API-key URL/env configuration? Recommendation: start with env URL/API-key and add OAuth later if requested.
3. Should MCP tools be named `tool` or `server__tool` when there is no collision? Recommendation: always use `server__tool` for predictability, with metadata documenting the original name.

## Success criteria

The enhancement is complete when a user can install `pythinker-sdk`, create a `PythinkerClient` from environment variables, attach MCP tools including Tavily, run a bounded agent loop, and understand the API from README examples without importing any `pythinker_code` CLI internals.
