# Changelog

All notable changes to `pythinker-code` are tracked in this file.

Pythinker Code uses a `0.MINOR.PATCH` version scheme. `MINOR` is a release
counter that continues advancing with each release. `PATCH` is reserved for
hotfixes against an already-released `MINOR`. There is no `1.0.0` milestone
planned on this line.

Releases earlier than `0.8.0` were published as `pythinker-code` 1.x/2.x
under a different scheme. The full pre-`0.8.0` history is preserved in
[`docs/history/CHANGELOG-pre-0.8.0.md`](docs/history/CHANGELOG-pre-0.8.0.md).
All 1.x and 2.x releases have been yanked from PyPI and removed from the
GitHub Releases page; `0.8.0` is the new starting line.

## Unreleased

## 0.11.0 (2026-05-22)

### What changed in this release

- **Fixed PyPI install conflict (was failing on Windows and every other platform).** `pip install pythinker-code==0.10.0` failed with `fastmcp 3.2.0 depends on mcp<2.0 and >=1.24.0` vs `pythinker-core 1.1.0 depends on mcp<1.17 and >=1`. 0.11.0 pins the republished `pythinker-core 1.1.1`, whose widened `mcp>=1.23,<2` constraint lets the resolver pick a single `mcp` version compatible with `fastmcp==3.2.0`.
- **Blackbox-style TUI port — phase 1.** Shell design primitives, compact transcript activity rows, blackbox-style motion status, standardized shell dialogs, aligned footer status styling, and a restyled tool-result surface land together. The TUI now shares a coherent visual language across rows, dialogs, and motion.
- **Refreshed TUI accent palette.** Dark/light theme accent retuned to a cleaner sky-blue (`#7dd3fc` dark, `#0284c7` light) for better contrast against the new tool-result surfaces.
- **Markdown + report polish.** Report spacing and markdown code blocks render with improved breathing room and consistent fences.
- **Rotating thinking-word indicator restored** with a leading space before the live stream status so the spinner no longer abuts surrounding text.
- **Internal audit + smoke evaluation.** A blackbox TUI scope map, prompt/agent audit, and a recorded visual smoke evaluation join the repo to govern future TUI work.

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==0.11.0`.

## 0.10.0 (2026-05-22)

### What changed in this release

- **Tool failure recovery improvements.** The agent loop now handles malformed or empty tool-call responses more gracefully and can continue the session instead of leaving the UI stuck after a bad provider turn.
- **Safer file edits.** File write and replace tools now create restore points before mutating files, giving sessions a clearer recovery path after risky changes.
- **Session UX state tracking.** Runtime session state now records additional UX metadata so shell surfaces can provide better continuity across long-running work.
- **Shell command enhancements.** New shell slash-command plumbing improves discoverability and keeps interactive workflows smoother.
- **TUI renderer polish.** Tool cards now share more consistent status glyphs, truncation behavior, and result summaries across bash, read, write, edit, grep, find, web, subagent, background, ask-user, and think renderers.
- **Clipboard handling hardening.** Clipboard helpers now degrade more cleanly when platform clipboard access is unavailable.
- **Release and TUI specs.** The repository now includes the blackbox TUI port design and a visual smoke-test criterion for future terminal UI work.

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==0.10.0`.

## 0.9.0 (2026-05-21)

### What changed in this release

- **Cleaner TUI — tool card backgrounds removed.** The grey pending/running
  background overlay that appeared behind every tool execution card (subagents,
  bash executions, reads, etc.) has been removed. Only user-message blocks
  retain a background tint, keeping the visual hierarchy focused on your input.
- **Welcome screen enhancements.** The startup info panel now shows the current
  git branch (when inside a git repo) and the session auto-save path alongside
  the working directory and session ID. Branch name is highlighted in magenta
  for quick scanning.
- **Bash header strip styling.** The `$ command` portion of bash execution
  headers now picks up the `tool_pending_bg` token for the strip background,
  matching the reference renderer style and providing consistent visual weight
  across themes.
- **Pythinker markdown renderer wired into message components.** User messages,
  assistant messages, and custom messages now render through `pythinker_markdown`
  (the project's own Markdown renderer) instead of raw `rich.markdown.Markdown`,
  giving consistent heading, code-block, and table styling everywhere.
- **Expanded theme palette.** `theme.py` gains a full `MarkdownColors` /
  `markdown_rich_style` subsystem with dark and light palettes covering headings,
  emphasis, inline code, links, blockquotes, table borders, code-block borders
  and backgrounds, and spinner states (active/done/failed).
- **Improved tool fallback renderers.** The call fallback now emits a
  status-glyph header (`✔`/`✘`/`●`) instead of a bare label. The result
  fallback now truncates long outputs at 60 lines / 4000 chars with an
  italicised note (matching the card renderer's behaviour), and applies the
  correct theme tokens for error vs. muted output.

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==0.9.0`.

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
  `docs/history/CHANGELOG-pre-0.8.0.md`; this file starts fresh at `0.8.0`.
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

See [`docs/history/CHANGELOG-pre-0.8.0.md`](docs/history/CHANGELOG-pre-0.8.0.md)
for the archived pre-reset release-by-release notes.

Upgrade with `pythinker update` or `pip install --upgrade pythinker-code==0.8.0`.
