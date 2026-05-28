# Changelog

This page documents the changes in each Pythinker Code release.

All notable changes to `pythinker-code` are tracked in this file.

Pythinker Code uses a `0.MINOR.PATCH` version scheme. `MINOR` is a release
counter that continues advancing with each release. `PATCH` is reserved for
hotfixes against an already-released `MINOR`. There is no `1.0.0` milestone
planned on this line.

Releases earlier than `0.8.0` were published as `pythinker-code` 1.x/2.x
under a different scheme. The full pre-`0.8.0` history is preserved in
[`../../history/CHANGELOG-pre-0.8.0.md`](../../history/CHANGELOG-pre-0.8.0.md).
All 1.x and 2.x releases have been yanked from PyPI and removed from the
GitHub Releases page; `0.8.0` is the new starting line.

## Unreleased

## 0.20.0 (2026-05-28)

### What changed in this release

- **Ranked recall injection and Scratchpad working memory.** The memory subsystem gains a dependency-free lexical retriever, ranked recall injection replacing the previous verbatim memory dump, and a new root-only `Scratchpad` tool that lets the agent record structured notes across tool calls during a session.
- **Full memory lifecycle: Phases B–D.** A unified injection bus re-arms recall on every Memory or Scratchpad write (Phase B), session-end episodic recaps are harvested before compaction into a per-project journal (Phase C, off by default), and an approval-gated inbox consolidation flow (`/memory inbox`) proposes—but never auto-applies—memory merges (Phase D).
- **Context-aware and web-fresh agent subagents.** Code-reviewer, security-reviewer, coder, and plan specialists now mandate a context7-first / web-fallback freshness check before scoring third-party findings or writing against a library. The system prompt gains a Granular Todo discipline (one in-progress sub-todo per dispatched subagent) and an Engineering Discipline section.
- **Memory robustness hardening.** Compaction harvest failures are now isolated per-phase (a broken prepare step no longer silently cancels recall), inbox JSON-parse errors log and skip instead of dropping silently, and the recall injection bus uses a knapsack budget that continues filling with lower-priority candidates after a high-priority slot overflows.
- **Animated robot logo in all native installers.** The curl-bash and PowerShell native installers now display a Tetris-style animated robot-head logo on supported terminals, with a static fallback for CI, `NO_COLOR`, dumb-term, or `PYTHINKER_NO_ANIMATION=1`.

Upgrade with `pythinker update`, `pip install --upgrade pythinker-code==0.20.0`, or use the native installer for your OS (see the README install table).

## 0.19.0 (2026-05-27)

### What changed in this release

- **Central per-project agent memory.** Pythinker now keeps a durable per-project memory (`MEMORY.md` / `USER.md`) under `~/.pythinker/projects/<key>/memory/`, written through a new root-only `Memory` tool with content guards and secret-shape detection, recalled into the root agent's first wakeup prompt within a bounded budget, and inspectable with the new `/memory` command.
- **Non-blocking update flow.** The blocking pre-start update prompt is replaced by a cached, no-network startup notice plus a triggerable `/update` command, and the native Windows installer now waits on the launching process before swapping files and cleans up its staged installer.
- **Fully native Homebrew formula.** Brew installs are generated from the same GitHub Release tarballs as the curl installer (including macOS Intel native assets), so they no longer depend on PyPI virtualenv resources.
- **Release pipeline hardening.** TestPyPI publishing is now non-blocking and publish steps carry timeouts, so a transient staging flake no longer fails a release.

Upgrade with `pythinker update`, `pip install --upgrade pythinker-code==0.19.0`, or use the native installer for your OS (see the README install table).

## 0.18.0 (2026-05-27)

### What changed in this release

- **Live subagent activity streaming.** Subagent tool calls now stream live into the transcript, with safe pending headers for in-flight tool calls, new transcript progress events, and a unified shimmer animation across active-work labels so long-running exploration stays legible.
- **Smarter delegation and orchestration.** A Context-First Orchestration Protocol guides the default agent, specialist subagents receive prompt packets for single-objective delegation plus evidence and verification gates, and overflow RunAgents children are deferred instead of hard-failing.
- **Calmer, more resilient TUI.** In-flight and singular Ask payloads no longer flash an invalid badge, MCP startup status is cleaner, and shell rendering and MCP guidance are refined.
- **Sturdier configuration handling.** Incompatible legacy JSON config is now preserved instead of being silently reset to defaults.
- **Security and shell hardening.** The security scan and shell execution paths were hardened against unexpected input.

Upgrade with `pythinker update`, `pip install --upgrade pythinker-code==0.18.0`, or use the native installer for your OS (see the README install table).

## 0.17.0 (2026-05-25)

### What changed in this release

- **Sharper compaction continuity.** PreCompact now carries custom instructions, restores skill and hook context after compaction, triggers SessionStart after restore, and preserves the `Conversation compacted.` handoff so long sessions resume cleanly.
- **Better subagent orchestration.** Subagent specs merge inherited subagent maps, foreground and background launches preserve parent-agent IDs for spawn-tree tracking, RunAgents fingerprints include agent names, and markdown agent discovery warns on unknown models instead of silently falling back.
- **Polished terminal workflow.** The shell adopts the robot-brand palette, compact transcript/agent/file-mention menus, pinned live todo activity, calmer tool output, safer auto-backgrounding for long shell commands, and updated render snapshots.
- **Release and installer hardening.** Interactive sessions show a blocking pre-start update prompt, update exits wait for acknowledgement, Homebrew publish retries package installs, and native installers gain a friendlier animated path with Windows User PATH automation.
- **Provider compatibility refresh.** Anthropic SDK support is updated for 0.101 tool-result block types so direct Anthropic sessions continue to stream tool output correctly.

Upgrade with `pythinker update`, `pip install --upgrade pythinker-code==0.17.0`, or use the native installer for your OS (see the README install table).

## 0.8.0 (2026-05-21)

Version-scheme reset. `pythinker-code` now ships as `0.8.0` under the new
`0.MINOR.PATCH` line.

### What changed in this release

- **Version line reset.** `pyproject.toml` `version` is `0.8.0` under the new release design.
  All prior `pythinker-code` 1.x/2.x releases have been yanked from PyPI and
  removed from the GitHub Releases page. New installs of
  `pip install --upgrade pythinker-code==0.8.0` resolve to the `0.x` line.
- **Tag scheme standardised** on `v<MAJOR>.<MINOR>.<PATCH>`. The
  `release-pythinker-cli.yml` workflow trigger now matches `v[0-9]+.[0-9]+.[0-9]+`
  and `scripts/check_version_tag.py` strips the leading `v` before comparing the
  tag to `pyproject.toml`.
- **Release gate preserved.** The `What's New in <version>` section,
  `pythinker-code==<version>` install snippet, and `## <version> (YYYY-MM-DD)`
  CHANGELOG entry are still required for every tag — only the version values
  change.
- **CHANGELOG restart.** Pre-`0.8.0` history archived to
  `../../history/CHANGELOG-pre-0.8.0.md`; this file starts fresh at `0.8.0`.
- **README "What's New" trimmed.** The cascading 2.x "What's New" wall is
  replaced by a single `0.8.0` section. Past release notes live in the archived
  CHANGELOG and the per-tag GitHub Releases (from `v0.8.0` onward).
- **Test refactor.** `tests/telemetry/test_otel_resource.py` now reads the
  expected service version from `importlib.metadata.version("pythinker-code")`
  instead of a hard-coded string, so future version bumps don't require a test
  edit.

### Included in 0.8.0

All functionality included in `pythinker-code` 0.8.0 is preserved:
review-first workflows (`pythinker review`, `pythinker secscan`,
`pythinker security-scan`, `pythinker debug`), Reviewflow stateful
review/fix workflows, the new `code-reviewer` / `security-reviewer` /
`debugger` subagent roles, hardened review-output validation, and the
read-only PR artifact helpers (`describe`, `improve` / `suggest`, `ask`,
`labels`, `changelog`, `docs`, `compliance`, etc.).

See [`../../history/CHANGELOG-pre-0.8.0.md`](../../history/CHANGELOG-pre-0.8.0.md)
for the archived pre-reset release-by-release notes.

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==0.8.0`.
