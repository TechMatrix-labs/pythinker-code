# Pythinker CLI

## Quick commands (use uv)

- `make prepare` (sync deps for all workspace packages and install git hooks)
- `make format`
- `make check`
- `make test`
- `make ai-test`
- `make build` / `make build-bin`
- `make web-back` / `make web-front`, `make vis-back` / `make vis-front` for web/vis development

If running tools directly, use `uv run ...`.

## Project overview

Pythinker CLI is a Python CLI agent for software engineering workflows. It supports an interactive
shell UI, ACP server mode for IDE integrations, and MCP tool loading.

## Tech stack

- Python 3.12+ (tooling configured for 3.14)
- CLI framework: Typer
- Async runtime: asyncio
- LLM framework: pythinker-core
- MCP integration: fastmcp
- Logging: loguru
- Package management/build: uv + uv_build; PyInstaller for binaries
- Tests: pytest + pytest-asyncio; lint/format: ruff; types: pyright + ty

## Architecture overview

- **CLI entry**: `src/pythinker_code/cli/__init__.py` (Typer) parses flags (UI mode, agent spec, config, MCP)
  and routes into `PythinkerCLI` in `src/pythinker_code/app.py`.
- **App/runtime setup**: `PythinkerCLI.create` loads config (`src/pythinker_code/config.py`), chooses a
  model/provider (`src/pythinker_code/llm.py`), builds a `Runtime` (`src/pythinker_code/soul/agent.py`),
  loads an agent spec, restores `Context`, then constructs `PythinkerSoul`.
- **Agent specs**: YAML under `src/pythinker_code/agents/` loaded by `src/pythinker_code/agentspec.py`.
  Specs can `extend` base agents, select tools by import path, and register builtin subagent
  types via the `subagents` field. Subagent instances are persisted separately under the session
  directory and can be resumed by `agent_id`. System prompts live alongside specs; builtin args
  include `PYTHINKER_NOW`, `PYTHINKER_WORK_DIR`, `PYTHINKER_WORK_DIR_LS`, `PYTHINKER_AGENTS_MD`, `PYTHINKER_SKILLS`, `PYTHINKER_ADDITIONAL_DIRS_INFO`, `PYTHINKER_OS`, `PYTHINKER_SHELL`
  (this file is injected via `PYTHINKER_AGENTS_MD`).
- **Tooling**: `src/pythinker_code/soul/toolset.py` loads tools by import path, injects dependencies,
  and runs tool calls. Built-in tools live in `src/pythinker_code/tools/` (agent, ask_user,
  background, dmail, file, plan, shell, think, todo, web). MCP tools are loaded via `fastmcp`;
  CLI management is in `src/pythinker_code/cli/mcp.py` and stored in the share dir.
- **Subagents**: `LaborMarket` in `src/pythinker_code/subagents/registry.py` registers builtin
  subagent types. The `Agent` tool (`src/pythinker_code/tools/agent/`) creates or resumes subagent
  instances, while `SubagentStore` persists instance metadata, prompts, wire logs, and context under
  `session/subagents/<agent_id>/`.
- **Core loop**: `src/pythinker_code/soul/pythinkersoul.py` is the main agent loop. It accepts user input,
  handles slash commands (`src/pythinker_code/soul/slash.py`), appends to `Context`
  (`src/pythinker_code/soul/context.py`), calls the LLM (pythinker-core), runs tools, and performs compaction
  (`src/pythinker_code/soul/compaction.py`) when needed.
- **Approvals**: `src/pythinker_code/soul/approval.py` is the tool-facing facade. `ApprovalRuntime`
  in `src/pythinker_code/approval_runtime/` is the session-level source of truth for pending approvals,
  and approval requests are projected onto the root wire stream for Shell/Web style UIs.
- **UI/Wire**: `src/pythinker_code/soul/run_soul` connects `PythinkerSoul` to a `Wire`
  (`src/pythinker_code/wire/`) so UI loops can stream events. UIs live in `src/pythinker_code/ui/`
  (shell/print/acp); the wire protocol/runtime lives in `src/pythinker_code/wire/`.
- **Shell UI**: `src/pythinker_code/ui/shell/` handles interactive TUI input, shell command mode,
  and slash command autocomplete; it is the default interactive experience.
- **Slash commands**: Soul-level commands live in `src/pythinker_code/soul/slash.py`; shell-level
  commands live in `src/pythinker_code/ui/shell/slash.py`. The shell UI exposes both and dispatches
  based on the registry. Standard skills register `/skill:<skill-name>` and load `SKILL.md`
  as a user prompt; flow skills register `/flow:<skill-name>` and execute the embedded flow.

## Multi-provider auth and usage

Pythinker CLI is a multi-provider agent: a single session can be wired to any of
several upstream LLM platforms, each authenticated by either OAuth or an API key.
Provider-aware code (login flows, usage reports, future per-provider features)
should always scope to **the active model's provider**, not iterate every
configured one.

- **Supported providers** (`src/pythinker_code/auth/`): `openai` (API + ChatGPT
  OAuth), `anthropic_direct` (API + Anthropic OAuth), `opencode_go` (OAuth),
  `minimax` (OAuth), `deepseek` (API key), `openrouter` (API key). Each module
  owns its login UX and token plumbing; `OAuthManager` in
  `src/pythinker_code/auth/oauth.py:754` is the shared token store / refresher.
- **Platform registry**: `src/pythinker_code/auth/platforms.py` defines
  `Platform` records and the key conventions every provider-aware subsystem
  uses:
  - Provider key: `managed:<platform_id>` (built via `managed_provider_key()`,
    parsed via `parse_managed_provider_key()`).
  - Managed model id: `<platform_id>/<model_id>` (built via
    `managed_model_key()`).
- **Config wiring** (`src/pythinker_code/config.py`): `LLMProvider` (line 35)
  holds the credential/endpoint shape; `LLMModel` (line 60) carries
  `provider: str` (the `managed:<platform_id>` key) so each model maps back to
  exactly one provider.
- **Active model lookup**: the runtime's currently selected model is
  `soul.runtime.llm.model_config` (an `LLMModel`); its `.provider` field is the
  provider key. The helper `current_model_key(soul)` in
  `src/pythinker_code/ui/shell/oauth.py:122` returns the model name for display.
  Use these instead of guessing from `config.default_model`.
- **Usage adapters** (`src/pythinker_code/ui/shell/usage_adapters/`): one
  adapter per platform, registered in `ADAPTERS` by `platform_id`
  (`anthropic`, `deepseek`, `openai`, `openai-chatgpt`, `openrouter`,
  `pythinker-code`). Each implements the `UsageAdapter` Protocol in `base.py`.
- **`/usage` semantics** (`src/pythinker_code/ui/shell/usage.py`): default
  (`/usage`) scopes to the active model's provider; `/usage all` shows every
  configured provider; `/usage <provider_key>` filters to one. Adding a new
  provider therefore requires both an auth module under `src/pythinker_code/auth/`
  and a matching usage adapter under `src/pythinker_code/ui/shell/usage_adapters/`,
  plus a `Platform` entry in `auth/platforms.py`.
- **Universal rate-limit fallback**: chat-completion HTTP responses are piped
  through a per-provider httpx response hook into `RateLimitCache`
  (`src/pythinker_code/usage_ratelimit_cache.py`). `/usage` consults it when an
  adapter is missing or returned no data, so providers without dedicated
  adapters (e.g. MiniMax, OpenCode Go) still surface live rate-limit panels.

When in doubt, derive provider from the active model — never hard-code a
provider list and never fan out across all configured providers unless the
user explicitly asks for an aggregate (e.g. the `all` escape hatch).

## Major modules and interfaces

- `src/pythinker_code/app.py`: `PythinkerCLI.create(...)` and `PythinkerCLI.run(...)` are the main programmatic
  entrypoints; this is what UI layers use.
- `src/pythinker_code/soul/agent.py`: `Runtime` (config, session, builtins) and `Agent` (system prompt +
  toolset); builtin subagent registration lives in `src/pythinker_code/subagents/registry.py`.
- `src/pythinker_code/soul/pythinkersoul.py`: `PythinkerSoul.run(...)` is the loop boundary; it emits Wire
  messages and executes tools via `PythinkerToolset`.
- `src/pythinker_code/soul/context.py`: conversation history + checkpoints; used by DMail for
  checkpointed replies.
- `src/pythinker_code/soul/toolset.py`: load tools, run tool calls, bridge to MCP tools.
- `src/pythinker_code/ui/*`: shell/print/acp frontends; they consume `Wire` messages.
- `src/pythinker_code/wire/*`: event types and transport used between soul and UI.

## Repo map

- `src/pythinker_code/agents/`: built-in agent YAML specs and prompts
- `src/pythinker_code/auth/`: OAuth/login provider integration
- `src/pythinker_code/background/`: background task worker/runtime support
- `src/pythinker_code/cli/`: Typer command tree, including MCP, plugin, web, vis, info, export, and term commands
- `src/pythinker_code/hooks/`: hook definitions and execution engine
- `src/pythinker_code/plugin/`: plugin discovery and installation support
- `src/pythinker_code/prompts/`: shared prompt templates
- `src/pythinker_code/skill/`, `src/pythinker_code/skills/`: skill discovery, loading, and bundled skills
- `src/pythinker_code/soul/`: core runtime/loop, context, compaction, approvals
- `src/pythinker_code/subagents/`: subagent registry, store, builders, and runners
- `src/pythinker_code/tools/`: built-in tools
- `src/pythinker_code/ui/`: UI frontends (shell/print/acp)
- `src/pythinker_code/acp/`: ACP server components
- `src/pythinker_code/web/`, `src/pythinker_code/vis/`: backend integration for web and visualization UIs
- `web/`, `vis/`: frontend apps built into the CLI package
- `packages/pythinker-core/`, `packages/pythinker-host/`, `packages/pythinker-code/`: workspace deps
  + Pythinker Core is an LLM abstraction layer designed for modern AI agent applications.
    It unifies message structures, asynchronous tool orchestration, and pluggable
    chat providers so you can build agents with ease and avoid vendor lock-in.
  + Pythinker Host is a lightweight Python library providing an abstraction layer for agents
    to interact with operating systems. File operations and command executions via Host
    can be easily switched between local environment and remote systems over SSH.
  + Pythinker Code is a thin distribution package that depends on `pythinker-code` and
    exposes the `pythinker-code` console script (re-exports `pythinker_code.__main__:main`).
- `sdks/pythinker-sdk/`: Python SDK package
- `tests/`, `tests_e2e/`, `tests_ai/`: unit/integration, wire/CLI e2e, and AI-driven test suites
- `examples/`: example integrations and custom soul/tool projects
- `plips`: Pythinker CLI Improvement Proposals

## Conventions and quality

- Python >=3.12 (ty config uses 3.14); line length 100.
- Ruff handles lint + format (rules: E, F, UP, B, SIM, I); pyright + ty for type checks.
- Tests use pytest + pytest-asyncio; files are `tests/test_*.py`.
- CLI entry points: `pythinker` / `pythinker-code` -> `src/pythinker_code/__main__.py` (routes to `src/pythinker_code/cli/__init__.py`).
- User config: `~/.pythinker/config.toml`; logs, sessions, and MCP config live in `~/.pythinker/`.

## Git commit messages

Conventional Commits format:

```
<type>(<scope>): <subject>
```

Allowed types:
`feat`, `fix`, `test`, `refactor`, `chore`, `style`, `docs`, `perf`, `build`, `ci`, `revert`.

## Versioning

The project follows a **minor-bump-only** versioning scheme (`MAJOR.MINOR.PATCH`):

- **Patch** version is always `0`. Never bump it.
- **Minor** version is bumped for any change: new features, improvements, bug fixes, etc.
- **Major** version is only changed by explicit manual decision; it stays unchanged during
  normal development.

Examples: `1.0.0` → `1.1.0` → `1.2.0`; never `1.0.1`.

This rule applies to release packages in the root project and `packages/*` unless a release task
explicitly targets a package with independent versioning. Do not normalize `sdks/*` or `examples/*`
versions unless the user or release workflow explicitly asks for that package.

## Release workflow

1. Ensure `main` is up to date (pull latest).
2. Create a release branch, e.g. `bump-1.42` or `bump-pythinker-host-1.43`.
3. Update `CHANGELOG.md`: rename `[Unreleased]` to `[1.42] - YYYY-MM-DD`.
4. Update `pyproject.toml` version.
5. Run `uv sync` to align `uv.lock`.
6. Commit the branch and open a PR.
7. Merge the PR, then switch back to `main` and pull latest.
8. Tag and push:
   - `git tag 1.42` or `git tag pythinker-host-1.43`
   - `git push --tags`
9. GitHub Actions handles the release after tags are pushed.
