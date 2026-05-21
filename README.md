<div align="center">

# <img src="https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/docs/media/logo.png" alt="Pythinker logo" width="42" align="top"> Pythinker Code

### *Your terminal-native AI engineering agent.*

**Read code. Edit files. Run commands. Search the web. Plug into your IDE.**
**All from the shell you already live in.**

<br />

[![PyPI](https://img.shields.io/pypi/v/pythinker-code?style=for-the-badge&logo=pypi&logoColor=white&color=2563eb&label=pythinker-code&cacheSeconds=60)](https://pypi.org/project/pythinker-code/)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/pyproject.toml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-16a34a.svg?style=for-the-badge)](https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/mohamed-elkholy95/Pythinker-Code/ci-pythinker-cli.yml?branch=main&label=CI&style=for-the-badge&logo=githubactions&logoColor=white)](https://github.com/mohamed-elkholy95/Pythinker-Code/actions/workflows/ci-pythinker-cli.yml?query=branch%3Amain)

[![Downloads](https://img.shields.io/pepy/dt/pythinker-code?cacheSeconds=300)](https://pepy.tech/projects/pythinker-code)
[![Code style: Ruff](https://img.shields.io/badge/code%20style-ruff-f59e0b.svg?style=flat-square&logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![ACP ready](https://img.shields.io/badge/ACP-ready-7c3aed.svg?style=flat-square)](https://github.com/agentclientprotocol/agent-client-protocol)
[![MCP tools](https://img.shields.io/badge/MCP-tools-0891b2.svg?style=flat-square)](https://modelcontextprotocol.io/)
[![Homepage](https://img.shields.io/badge/home-pythinker.com-ec4899.svg?style=flat-square)](https://pythinker.com)

<br />

<a href="https://pythinker.com">🌐 Website</a> &nbsp;·&nbsp;
<a href="#-quick-start">⚡ Quick Start</a> &nbsp;·&nbsp;
<a href="#-features">✨ Features</a> &nbsp;·&nbsp;
<a href="#-ide-integration-via-acp">🧩 IDE Integration</a> &nbsp;·&nbsp;
<a href="#-mcp-tooling">🔌 MCP</a> &nbsp;·&nbsp;
<a href="#-privacy--telemetry">🔐 Privacy</a> &nbsp;·&nbsp;
<a href="#-development">🛠️ Develop</a>

<br /><br />

<img src="https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/docs/media/pythinker-code.gif" alt="Pythinker Code terminal demo" width="860">

</div>

---

## 💡 What is Pythinker?

**Pythinker Code** is an open-source AI coding agent that lives in your terminal. Unlike chat-based assistants stuck behind a browser tab, Pythinker can **read your repo, edit files, run shell commands, browse the web, and call MCP tools** — all in a single iterative loop driven by the model of your choice.

It speaks the [**Agent Client Protocol (ACP)**](https://github.com/agentclientprotocol/agent-client-protocol), so it slots cleanly into ACP-aware editors like Zed and JetBrains. It loads [**Model Context Protocol (MCP)**](https://modelcontextprotocol.io/) servers, so the same tools your other agents use just work. And it's hackable: subagents, skills, hooks, and plugins are all first-class extension points.

> 🎯 **One agent, one shell, one workflow.** No tab-switching. No context loss. No magic.

---

## 🆕 What's New in 2.7.0

First-class agent-first code review, security review, and root-cause debugging, via the new
`pythinker-review` workspace package.

- **`pythinker review diff`** — runs a code-review pass on the current branch's diff against `origin/main` (or `--base <ref>`, `--staged`, `--working-tree`, `--range A..B`). Outputs pretty / JSON / SARIF. `--fail-on <severity>` makes it a CI gate.
- **`pythinker review diff --with-security`** — runs the code-review and security-review passes in parallel.
- **`pythinker secscan diff`** — security-only pass with Pythinker Security Scan deterministic prompt anchors for secrets, command/SQL/NoSQL injection, deserialization, SSRF, path traversal, XSS, redirects, JWT/CORS issues, prompt-injection surfaces, debug endpoints, weak crypto, and more.
- **`pythinker security-scan scan`** — repo-wide Pythinker Security Scan pipeline for deterministic candidate discovery, model-backed investigation, revalidation, triage, reports, and exports.
- **`pythinker debug failure <log-file>`** — root-cause debugger pass over failing test output, stack traces, logs, and correlated diff context, with secret redaction before prompts.
- **`pythinker review diff --mode deslopify`** — read-only Reviewflow-style simplification review for accidental complexity, duplicate wrappers, dead branches, and brittle test/type band-aids.
- **Evidence validation** — findings outside the reviewed chunk, unsafe paths, stale line ranges, or non-matching evidence snippets are rejected and surfaced as validation failures instead of being silently persisted.
- **Findings store** at `.pythinker-review/runs/<id>/` for inspection via `pythinker review list`, `pythinker review show <id>`, `pythinker review next`, and `pythinker review show-finding <finding-id>`.
- **Code-reviewr PR assistant parity** — read-only `pythinker review describe`, `improve`/`suggest`, `ask`, `labels`, `changelog`, and `docs` commands produce structured PR artifacts without posting or modifying files.
- **Reviewflow workflow substrate** — compatible project/feature/run/finding/patch state models and mapping/reporting utilities are available for future whole-repo audit and revalidation flows.
- **Three new subagent roles** — `code-reviewer`, `security-reviewer`, and `debugger` — usable from any interactive Pythinker session, producing the standard SUMMARY/EVIDENCE/CHANGES/RISKS/BLOCKERS block.
- **Fail-closed by default** — any chunk timeout, malformed model output, or worker exception exits non-zero. `--allow-partial` is the explicit escape hatch and surfaces failures in output.

No new third-party runtime dependencies. Reuses the active Pythinker model when invoked via `pythinker review` / `pythinker secscan` / `pythinker security-scan` / `pythinker debug`; the standalone `pythinker-review` / `pythinker-secscan` / `pythinker-security-scan` / `pythinker-debug` console scripts accept explicit/env configuration.

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==2.7.0`.

## 🆕 What's New in 2.6.0

> **Hotfix release for Kimi K2.x and DeepSeek users on PyPI.**

The runtime fix for the strict-interleaved `thinking is enabled but reasoning_content is missing in assistant tool call message at index N` rejection was in the `pythinker-core` source since 2.4.0, but the published `pythinker-core==1.0.0` on PyPI predates it — so installs of `pythinker-code` 2.4.0 / 2.5.0 from PyPI kept hitting the bug on Kimi K2.5, K2.6, and DeepSeek (including through OpenCode Go). Reported in [#37](https://github.com/mohamed-elkholy95/Pythinker-Code/issues/37).

2.6.0 bumps the pinned dep:

- **`pythinker-core` 1.0.0 → 1.1.0** (published independently to PyPI) — strict-interleaved providers (`kimi-k2*`, `deepseek*`) now always emit `reasoning_content` on assistant turns, with the fallback chain `ThinkPart → extract_text() → "[reasoning unavailable]"`. Multi-step tool flows on Kimi/DeepSeek no longer trip the strict thinking-replay check.
- **Root pin** `pythinker-core[contrib]==1.0.0 → 1.1.0` — new installs of `pip install --upgrade pythinker-code==2.6.0` (and `uv tool install`/`upgrade`) pick up the fix automatically.

No app-level changes vs 2.5.0; everything from the 2.5.0 release is still present. **Existing 2.5.0 users on Kimi K2.x / DeepSeek must upgrade to 2.6.0.**

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==2.6.0`.

### What was new in 2.5.0

## 🆕 What's New in 2.5.0

Coding-agent runtime hardening: runtime-enforced permission profiles, FetchURL SSRF protection, a Windows self-upgrade fix, and a configurable feedback endpoint.

- **Runtime-enforced permission profiles** — every built-in role (`read-only` / `plan` / `ask` / `implement` / `review` / `verify`) is now backed by `src/pythinker_code/soul/permission.py`. Profiles are snapshot per LLM step so a mid-step model switch can't escalate. **Plan mode hard-denies** non-plan writes and dangerous shell mutations instead of relying on prompt-deny.
- **Plan → Implement handoff** — new `tools/plan/handoff.py` plus dynamic injection through `soul/dynamic_injections/plan_mode.py` carries the approved plan into implementation without re-priming the context.
- **FetchURL SSRF + size hardening** — `_validate_fetch_url` blocks private / loopback / link-local / multicast / reserved IPv4 + IPv6 ranges; rejects non-`http`/`https` schemes; non-host URLs. Responses are streamed with a hard **5 MB** ceiling honoring `Content-Length`.
- **Windows self-upgrade fixed** — `pythinker update` on Windows now spawns the upgrade in a **detached console** and exits the parent before `uv tool upgrade` runs, releasing the lock on the running `pythinker.exe`. Eliminates the `os error 32: The process cannot access the file because it is being used by another process` error.
- **Background recovery improved** — `recoverable` (resumable via stored `agent_id`) vs `lost` (worker gone, no resume target). Subagent instances are parked as `idle` when recoverable. `pythinker-host` subprocess teardown kills the entire child process tree and creates a new session group.
- **Feedback endpoint config** — new `feedback` config block (`endpoint_url`, `api_key`, `custom_headers`). The `/feedback` slash command now routes submissions to a user-configured HTTP endpoint instead of being a no-op.
- **Welcome-screen version banner** — installed Pythinker version is now visible up-front.
- **VS 2026 CI forward-compat probe** — non-blocking `windows-2025-vs2026` matrix entry on the host + cli builds validates MSVC v144 ahead of GitHub's eventual `windows-2022` deprecation.
- **anthropic 0.101 compat** — added fallbacks for the six new tool-result block types so `pyright` stays exhaustive.
- **Telemetry hygiene** — OTel `service.name` normalized to a stable value for SigNoz dashboards; Sentry filters drop test and shutdown noise.

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==2.5.0` (note: 2.5.0 PyPI installs are affected by [#37](https://github.com/mohamed-elkholy95/Pythinker-Code/issues/37) on Kimi/DeepSeek — see the 2.6.0 hotfix above).

### What was new in 2.4.0

## 🆕 What's New in 2.4.0

Subagent roles overhaul, Kimi K2 provider support, and a ripgrep-free Grep fallback.

- **New subagents** — `implementer` (scoped edits + verification), `review` (severity-scored read-only review), and `verifier` (`PASS` / `FAIL` / `FLAKY` validation runner). Join the existing `coder` / `explore` / `plan` roster.
- **Structured subagent output** — every default agent now answers with `### SUMMARY / EVIDENCE / CHANGES / RISKS / BLOCKERS`, so the parent agent can consume results without re-parsing prose. New recommended flow: **Scout → Plan → Implement → Review → Verify** (review and verify can run in parallel).
- **Kimi K2.5 / K2.6 support** — `--thinking` is routed via the provider-specific `thinking.type` body field, and assistant tool-call replays always carry `reasoning_content` so multi-step tool flows stop tripping the strict thinking-replay check. Same hardening applied to DeepSeek's strict mode.
- **`Grep` works without `rg`** — pure-Python fallback honors `pattern` / `glob` / `type` / `ignore_case` / `multiline` / `context` / `output_mode` / `offset` / `head_limit` and respects `.gitignore`. The downloader also retries against the upstream GitHub releases mirror and accepts `PYTHINKER_RG_PATH=/absolute/path` plus extra discovery paths (`~/.cargo/bin`, `~/.local/bin`, `~/.pi/agent/bin`, `/usr/bin`, `/usr/local/bin`).
- **`AGENTS.md` rewritten** to match the new roster, and `tools/agent/description.md` documents the parallel-review and cross-check patterns.

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==2.4.0`.

### What was new in 2.3.0

## 🆕 What's New in 2.3.0

Telemetry & observability audit on top of 2.2.1.

- **38 silent-catch sites instrumented** — tool failures, OAuth errors, MCP hiccups, hook callbacks, subagent crashes now surface in Bugsink + SigNoz.
- **`/report-error` slash command** — user-invoked complement to automatic capture.
- **OTel trace sampling tunable** — `PYTHINKER_OTEL_TRACE_SAMPLE_RATE` for operators running their own collector.
- **`pythinker.mcp.call` span** with `mcp.server` attribute.
- **`docs/en/reference/telemetry.md`** documents the full contract.

### What was new in 2.2.1

## 🆕 What's New in 2.2.1

CI hardening on top of 2.2.0.

- **macOS binary build is now optional-codesign** — the release workflow detects whether `APPLE_CERTIFICATE_P12` / `APPLE_NOTARIZATION_KEY_P8` repo secrets are set. When they aren't (the v2.2.0 case), it ships an ad-hoc-signed PyInstaller binary instead of failing the whole release. PyPI install (`pip install pythinker-code`) is unaffected.
- **PyPI publish is idempotent** — `pypa/gh-action-pypi-publish` now runs with `skip-existing: true`, so re-running the release workflow against an already-published version is a no-op.

### What was new in 2.2.0

Animated installer + Windows PATH automation, on top of 2.1.2.

- **Tetris-style logo animation** — both `scripts/install.sh` and `scripts/install.ps1` now build the robot-head logo piece-by-piece (walls → top bar → bottom bar → eyes → ears → antenna), settling into the final mark before the install proceeds. Falls back gracefully to the existing static logo when the terminal isn't interactive (`CI=1`, `NO_COLOR`, `TERM=dumb`, redirected stdout, or `PYTHINKER_NO_ANIMATION=1`).
- **Animation tunables** — `PYTHINKER_LOGO_FRAME_DELAY` / `PYTHINKER_LOGO_STAGGER_DELAY` (bash, seconds) and `PYTHINKER_LOGO_FRAME_DELAY_MS` / `PYTHINKER_LOGO_STAGGER_DELAY_MS` (PowerShell, milliseconds) let you slow down or speed up playback.
- **Windows: idempotent User PATH write** — `install.ps1` now appends `~/.local/bin` to your User PATH via the registry (`[Environment]::SetEnvironmentVariable`) and broadcasts `WM_SETTINGCHANGE` so future shells pick it up. Re-running the installer is a no-op if the directory is already present.

### Carried forward from 2.1.2

Windows installer fix on top of 2.1.1.

- **Windows installer runs in the current shell** — `scripts/install.ps1` is now invoked via `& $installer` instead of a `powershell -File` subprocess, and the bundled `uv` bootstrap is dot-sourced inside an anonymous scope. PATH updates from `uv` now land in the calling PowerShell session, so `uv`, `uvx`, and `pythinker` are immediately runnable after the installer finishes — no "Open a new shell" dance.
- **Diagnostic fallback** — if `pythinker` is somehow still not on PATH (e.g., the script was deliberately run as a subprocess), the installer now prints the absolute path to the shim and tells you what to do.
- **Regression tests** — `tests/test_installation_docs.py` locks in the current-session invocation and the dot-sourced `uv` bootstrap.

### Carried forward from 2.1.1

Documentation refresh + CI hardening on top of 2.1.0.

- **PyPI page rendering** — README image and key file links converted to absolute GitHub URLs so the project page on PyPI renders the logo, demo GIFs, and architecture diagram correctly.
- **Type-checking on Python 3.14** — `@asynccontextmanager` / `@contextmanager` helpers now use `AsyncGenerator` / `Generator` return annotations; container-walk attribute access is properly cast; selector test helpers narrow `SelectorHeader | SelectorItem` unions.
- **`render_plain`** — no longer hits Rich's `is_dumb_terminal` size override (CI sets `TERM=dumb`); the explicit `width=` argument is honored everywhere.
- **License section** — corrected from MIT to Apache-2.0 (matches `pyproject.toml` and the existing badge).
- **CI cleanup** — `release-validate` step now points at the root `pyproject.toml`; PTY-based e2e tests skip on GitHub Actions runners (chronic `prompt_toolkit` hang); typos allowlist for verbatim CLI output.

### Carried forward from 2.1.0

A focused refresh of the TUI and slash-command UX.

- **Selectors package** — interactive `/theme`, `/thinking`, `/model`, `/login`, `/settings`, `/extension`, and `/show-images` panels replace the old numeric/text prompts.
- **`/thinking` slash command** — toggle reasoning effort live, mid-session.
- **`/settings` panel** — a real `SettingsList` over your `Config` (theme, default model, TUI style, default thinking, telemetry, loop limits, background tasks).
- **Card-style TUI polish** — bordered shell card, footer/toolbar, and a full set of tool renderers (read / write / edit / grep / find / bash / agent), plus a diff component. Subagent cards show a running-dots spinner while they work.
- **Selector framework** — `SelectorHeader` sentinel and per-row `on_change` callback for richer custom selectors.
- **Prompt templates** — discovery is now `~/.pythinker/prompts` and `<project>/.pythinker/prompts`. The legacy directory lookup has been retired.
- **TUI style flag** — only `card` (default) and `pythinker` are accepted; the legacy alias has been dropped.


---

## ✨ Features

<table>
<tr>
<td width="50%" valign="top">

### 🖥️ Terminal-First

Plan, edit, run, and verify without leaving your shell. Every action is visible, scriptable, and auditable.

</td>
<td width="50%" valign="top">

### ⚡ Shell Command Mode

Press `Ctrl-X` to drop into a direct shell prompt inside the agent. Run commands, then snap back into AI mode with full context preserved.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🧩 ACP IDE Integration

Run `pythinker acp` and any [Agent Client Protocol](https://github.com/agentclientprotocol/agent-client-protocol) editor — Zed, JetBrains, and more — gets a full Pythinker session inline.

</td>
<td width="50%" valign="top">

### 🔌 MCP Tool Loading

Manage stdio and HTTP MCP servers with `pythinker mcp`. OAuth-backed servers, persistent config, ad-hoc files — all supported.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🤖 Subagents & Skills

Delegate focused work to built-in subagents. Load reusable instructions via `/skill:<name>` and bundled prompt flows via `/flow:<name>`.

</td>
<td width="50%" valign="top">

### 🪝 Hooks & Plugins

Observe or block tool execution with hook events. Install community extensions with `pythinker plugin`.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🌐 Web & Visualization UIs

Optional web frontend and visualization frontend ship alongside the CLI for richer inspection workflows.

</td>
<td width="50%" valign="top">

### 🤖 Bring Your Own Model

Swap providers and models per-session: `--model openai/gpt-5.5`, hosted Pythinker models, or your own keys.

</td>
</tr>
</table>

> [!NOTE]
> Built-in shell commands such as `cd` are not yet supported in shell command mode.

<div align="center">
<img src="https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/docs/media/shell-mode.gif" alt="Shell command mode demo" width="860">
</div>

---

## ⚡ Quick Start

### ✨ Recommended install (clean, with logo)

```sh
curl -fsSL https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/scripts/install.sh | bash
```

Windows PowerShell:

```powershell
$installer = Join-Path $env:TEMP "pythinker-install.ps1"
iwr -UseBasicParsing https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/scripts/install.ps1 -OutFile $installer
& $installer
Remove-Item $installer
```

The installer fetches `uv` if missing, installs `pythinker-code` quietly, and prints a single-line confirmation instead of the full dependency wall. Windows downloads the script to a file (instead of `irm ... | iex`) so PowerShell antivirus scanning is less likely to block it, but it is invoked with `&` in the current session so PATH updates from `uv` are immediately visible — `pythinker` works without opening a new shell.

### 🚀 One-off run with `uvx`

```sh
uvx pythinker-code
```

### 📦 Install as a uv tool

```sh
uv tool install pythinker-code
pythinker
```

### 🔐 Authenticate (optional)

For hosted Pythinker models or ACP terminal auth:

```sh
pythinker login
```

### 💬 Try it out

```sh
# Interactive session
pythinker

# One-shot prompt
pythinker --prompt "summarize this repository and suggest the next test to add"

# Pick a specific model
pythinker --model openai/gpt-5.5

# Inline config override
pythinker --config '{"default_thinking": true}'
```

---

## 🏠 Using Local Models (LM Studio & Ollama)

Run Pythinker entirely on your own machine — no API key, no cloud. Pythinker speaks each runtime's OpenAI-compatible API, so tools, streaming, JSON mode, vision, and `reasoning_effort` all work the same as with hosted providers.

### LM Studio

**1. Set up LM Studio.**
- Install [LM Studio](https://lmstudio.ai/) and download at least one chat model.
- In the LM Studio app, open the model and **raise its Context Length** (gear icon → Context Length). See [Context length matters](#context-length-matters) below.
- Start the server: **Developer → Status: Running** (or `lms server start --port 1234`).

**2. Connect Pythinker.**
```sh
pythinker login --lm-studio
```

This auto-discovers every chat-capable model loaded in LM Studio, registers each as `lm-studio/<model-id>`, and picks the largest-context one as your default. Embedding models are filtered out.

**3. Use it.**
```sh
# Default LM Studio model
pythinker -p "explain quicksort"

# Specific model
pythinker -m lm-studio/qwen/qwen3-coder-next -p "write a python http server"

# Interactive shell, then switch models with /model
pythinker
```

**4. Disconnect.**
```sh
pythinker logout --lm-studio
```

### Ollama

```sh
# 1. start the server in one terminal
ollama serve

# 2. pull a model
ollama pull llama3.1:8b

# 3. connect Pythinker
pythinker login --ollama

# 4. use it
pythinker -p "explain monad transformers"
pythinker -m ollama/llama3.1:8b -p "..."
pythinker logout --ollama
```

Discovery uses Ollama's `/api/tags` for the model list and `/api/show` per model to read the real context window.

### Remote LM Studio / Ollama (LAN host or alternate port)

```sh
pythinker login --lm-studio --base-url http://192.168.1.10:1234/v1
pythinker login --ollama    --base-url http://lan-box:11434/v1
```

The override is saved in your config and used by every subsequent run.

### From inside the interactive shell

The same wiring is available as slash commands:

```
/login lm-studio        # or  /login lmstudio  (no dash also accepted)
/login ollama
/logout lm-studio
/logout ollama
/login                  # opens a chooser; entries 9 and 10 are the local providers
/model lm-studio/google/gemma-4-e4b   # switch model mid-session
```

### <a id="context-length-matters"></a>⚠️ Context length matters (a common gotcha)

Pythinker's agent prompt — system instructions + tool schemas + skills + your message + recent history — is large. **Tens of thousands of tokens before you've even sent your first message.**

LM Studio loads a model with a small default context window (often `4096`). If you start chatting against that, you'll see:

```
LLM provider error: Error: The number of tokens to keep from the initial
prompt is greater than the context length (n_keep: 16690 >= n_ctx: 4096).
```

The shell now prints a friendly recovery hint when this happens, but **the cure is in LM Studio**:

1. In LM Studio, open the model in the **Chat** tab and click the **gear/settings** icon (or **My Models → Edit**).
2. Set **Context Length** to at least **`32768`**, and prefer **`131072`** if your VRAM allows. *Practical experience: 64k still triggers errors during longer sessions; 128k is a safer floor.*
3. Reload the model (LM Studio prompts you).
4. Restart Pythinker so it picks up the new state (`Ctrl+D` then `pythinker`, or `pythinker -r <session-id>` to resume).

**Tip:** the bigger you set the context, the more VRAM the model uses. If you OOM, try a smaller quantization (e.g., Q4_K_M instead of Q8_0) or a smaller model variant.

Ollama configures context per-request and Pythinker reads the model's max from `/api/show`, so this gotcha is mostly LM-Studio-specific.

### VRAM-friendly model picks

Local models vary wildly in memory use. Rough guide on a 16 GB GPU (e.g., RTX 5080 mobile):

| Model size | Quant | Approx. VRAM | Fits 16 GB? |
|------------|-------|--------------|-------------|
| 2-4 B      | Q4-Q8 | 2-4 GB       | Yes, easily |
| 7-8 B      | Q4    | 5-6 GB       | Yes |
| 7-8 B      | Q8    | 8-9 GB       | Yes |
| 13-14 B    | Q4    | 8-10 GB      | Yes |
| 27-31 B    | Q4    | 17-20 GB     | Tight / no |
| 27-31 B    | Q8    | 30-35 GB     | No |

If LM Studio errors with `Failed to load model`, you've exceeded VRAM — pick a smaller model or lower-bit quantization.

### Environment variables

These override the defaults at both login and runtime:

| Variable | Purpose |
|----------|---------|
| `LM_STUDIO_BASE_URL` | Override `http://localhost:1234/v1` |
| `LM_STUDIO_API_KEY`  | Set if you've enabled token auth in LM Studio |
| `OLLAMA_BASE_URL`    | Override `http://localhost:11434/v1` |
| `OLLAMA_API_KEY`     | Rarely needed (Ollama is unauthenticated by default) |

Example:
```sh
LM_STUDIO_BASE_URL=http://workstation.lan:1234/v1 pythinker -p "..."
```

### Refreshing the model list

If you load/unload models in LM Studio (or `ollama pull/rm`), re-run login to refresh:

```sh
pythinker login --lm-studio    # or --ollama
```

(Pythinker intentionally does NOT auto-refresh local providers in the background — login owns that state, so manual edits to your config aren't silently overwritten.)

---

## 🧩 IDE Integration via ACP

Pythinker speaks [**Agent Client Protocol**](https://github.com/agentclientprotocol/agent-client-protocol) natively. Point your ACP-compatible editor at `pythinker acp` and you get a multi-session agent server inside your IDE.

<details>
<summary><b>📝 Configuration for Zed / JetBrains</b></summary>

```json
{
  "agent_servers": {
    "Pythinker Code": {
      "type": "custom",
      "command": "pythinker",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

</details>

The ACP server provides:

| Capability | Description |
|---|---|
| 🔑 **Terminal auth** | `pythinker login` flow exposed to the IDE |
| 📂 **Session listing & resume** | Pick up where you left off |
| 🔄 **Hot model swap** | Change models for a running ACP session |

<div align="center">
<img src="https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/docs/media/acp-integration.gif" alt="ACP IDE integration demo" width="860">
</div>

---

## 🔌 MCP Tooling

Pythinker loads [Model Context Protocol](https://modelcontextprotocol.io/) tools from persistent config or ad-hoc files. Same tools, every agent — no rewriting.

### 🛠️ Manage persistent MCP servers

```sh
# 🌐 Streamable HTTP server with API key
pythinker mcp add --transport http context7 https://mcp.context7.com/mcp \
  --header "CONTEXT7_API_KEY: ctx7sk-your-key"

# 🔐 Streamable HTTP server with OAuth
pythinker mcp add --transport http --auth oauth linear https://mcp.linear.app/mcp

# 💻 stdio server
pythinker mcp add --transport stdio chrome-devtools -- npx chrome-devtools-mcp@latest

# 📋 List, authorize, test, and remove
pythinker mcp list
pythinker mcp auth linear
pythinker mcp test chrome-devtools
pythinker mcp remove chrome-devtools
```

### 📄 Use an ad-hoc MCP config file

```json
{
  "mcpServers": {
    "context7": {
      "url": "https://mcp.context7.com/mcp",
      "headers": {
        "CONTEXT7_API_KEY": "YOUR_API_KEY"
      }
    },
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

```sh
pythinker --mcp-config-file /path/to/mcp.json
```

---

## 🧬 Extensibility

Pythinker is a small, extensible runtime — not a monolith. Build on it.

| Extension Point | What it does | Where to look |
|---|---|---|
| 🤖 **Agents & subagents** | YAML specs define tools, prompts, and built-in subagent types | `src/pythinker_code/agents/` |
| 🎓 **Skills** | `/skill:<name>` loads reusable instructions on demand | bundled & user-defined |
| 🌊 **Flows** | `/flow:<name>` executes bundled prompt flows | bundled & user-defined |
| 🪝 **Hooks** | Observe or block tool execution; integrate policy or automation | hook events API |
| 🧩 **Plugins** | Installable extension packages | `pythinker plugin` |

---

## 🏗️ Architecture

<div align="center">
<img src="https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/docs/media/Architecture.webp" alt="Pythinker Code architecture diagram" width="860">
</div>

---

## 🔐 Privacy & Telemetry

Pythinker is the **agent framework**, not the LLM. You bring your own API key
(OpenAI, Anthropic, your local LM Studio model, etc.); your prompts and the
model's responses go directly between your terminal and the model provider you
configured. Pythinker never sees, stores, or forwards them.

To improve the framework itself we collect a small amount of **diagnostic
telemetry** about how the agent runs. It's strictly anonymous, never includes
your prompts, model output, file contents, file paths, or any user-identifying
data. Two channels:

| Channel | What lands there | Endpoint |
|---|---|---|
| **Errors** (Sentry-protocol) | Unhandled exceptions and crash stack traces, with absolute paths above `site-packages/` rewritten to `<env>/` so home directories don't leak | `errors.pythinker.com` (self-hosted Bugsink) |
| **Traces + structured logs** (OpenTelemetry) | Lifecycle events (`session_started`, `started`, `model_switch`), agent-loop spans (`pythinker.turn` / `pythinker.llm` / `pythinker.tool`), and per-event counters | `otel.pythinker.com` (self-hosted SigNoz) |

### What we collect

- **Lifecycle events**: session start, command-line flags actually used (booleans only), startup timing, model name (just the identifier, e.g. `claude-opus-4-7`), thinking-mode toggle, plan-mode toggle.
- **Agent-loop spans**: turn duration, step count, stop reason (`no_tool_calls` / `max_steps` / `error`), tool name (`Read`, `Bash`, `Edit`, …), tool success/failure, tool duration, LLM call duration, input/output token *counts* (numbers — never the content).
- **Crashes**: exception class name, scrubbed stack trace, library versions. We do **not** send local variable values.
- **Static context**: pythinker version, OS family, Python version, terminal type (`TERM_PROGRAM`), CI flag (`CI` env var presence), locale.
- **A persistent, random `device_id`** so we can count "how many distinct installs" without identifying a person.

### What we never collect

- Your prompts, the model's responses, or any conversation content
- File contents, file paths, working directory names, or workspace structure
- Your API keys, OAuth tokens, environment variables
- Your real name, email, IP address, hostname (host name field is dropped at the edge collector)
- Tool arguments (e.g. what file you read, what command you ran)

### Opting out

Pick whichever fits your workflow — all three are equivalent:

```sh
# 1. Per-invocation CLI flag
pythinker --no-telemetry

# 2. Environment variable (works in shells, .env files, CI configs)
export PYTHINKER_DISABLE_TELEMETRY=1
pythinker

# 3. Permanently in your config file (~/.pythinker/config.toml)
[default]
telemetry = false
```

Setting any of these at startup short-circuits Sentry initialization, OTel
exporter creation, and the in-process event sink. No network requests are made
to the telemetry endpoints.

### Pointing telemetry at your own infrastructure

If you operate pythinker for a team and want telemetry routed to your own
SigNoz / Bugsink instead, override the endpoints via environment variables:

```sh
export PYTHINKER_SENTRY_DSN="https://<key>@your-bugsink.example.com/<project>"
export PYTHINKER_OTEL_ENDPOINT="https://your-otel-collector.example.com"
export PYTHINKER_OTEL_TOKEN="<your bearer token>"
```

The defaults point at infrastructure operated by the pythinker maintainers; you
don't need to set anything to use them.

---

## 🛠️ Development

### 🏁 Prepare the workspace

```sh
git clone https://github.com/mohamed-elkholy95/Pythinker-Code.git
cd Pythinker-Code
make prepare
```

### 🧰 Common commands

<table>
<tr>
<td valign="top">

**▶️ Run & iterate**
```sh
uv run pythinker          # CLI from source
make format               # format all packages
make check                # lint + type-check
```

</td>
<td valign="top">

**🧪 Test**
```sh
make test                 # all unit + e2e tests
make ai-test              # AI-driven tests
make test-pythinker-code   # CLI only
make test-pythinker-core  # Core only
make test-pythinker-host  # Host only
make test-pythinker-sdk   # SDK only
```

</td>
</tr>
<tr>
<td valign="top">

**🌐 Frontends**
```sh
make web-back             # web backend
make web-front            # web frontend
make vis-back             # vis backend
make vis-front            # vis frontend
```

</td>
<td valign="top">

**📦 Build**
```sh
make build                # Python packages
make build-bin            # standalone binary
make help                 # all targets
```

</td>
</tr>
</table>

> 💡 `make build` and `make build-bin` build and embed the web and visualization frontends before packaging.

---

## 🗂️ Project Layout

```
pythinker-code/
├── 📦 src/pythinker_code/         CLI runtime · tools · UIs · ACP · MCP · hooks · plugins · skills · web · vis backends
├── 🧱 packages/
│   ├── pythinker-core/           Provider-agnostic message, tool, and chat-provider abstractions
│   ├── pythinker-host/           Local/remote host filesystem and command execution
│   └── pythinker-code/           Console-script distribution package
├── 🧰 sdks/pythinker-sdk/        Python SDK
└── 🧪 tests/ · tests_e2e/ · tests_ai/   Unit · wire/CLI e2e · AI-driven test suites
```

---

## 🤝 Contributing

Contributions are warmly welcome — bug reports, PRs, plugins, skills, and docs all help.

- 📖 Start with [`CONTRIBUTING.md`](https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/CONTRIBUTING.md)
- 🔐 See [`SECURITY.md`](https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/SECURITY.md) for responsible disclosure
- 📜 Skim [`AGENTS.md`](https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/AGENTS.md) for the agent design notes

If Pythinker helps you, **a ⭐ on GitHub goes a long way.**

---

## 📜 License

Distributed under the **Apache-2.0 License**. See [`LICENSE`](https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/LICENSE) for the full text and [`NOTICE`](https://github.com/mohamed-elkholy95/Pythinker-Code/blob/main/NOTICE) for attributions.

<br />

<div align="center">

**Built with ❤️ for engineers who live in the terminal.**

[🌐 pythinker.com](https://pythinker.com) &nbsp;·&nbsp;
[📦 PyPI](https://pypi.org/project/pythinker-code/) &nbsp;·&nbsp;
[🐙 GitHub](https://github.com/mohamed-elkholy95/Pythinker-Code) &nbsp;·&nbsp;
[🧩 ACP](https://github.com/agentclientprotocol/agent-client-protocol) &nbsp;·&nbsp;
[🔌 MCP](https://modelcontextprotocol.io/)

</div>
