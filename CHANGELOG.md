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

## 0.14.0 (2026-05-24)

### What changed in this release

- **Install counter and README badge.** `https://pythinker.com/install.sh` and `https://pythinker.com/install.ps1` now route through a Cloudflare Worker-backed counter that records successful installer fetches and exposes both JSON and Shields-compatible badge endpoints. The README now shows the live install badge alongside PyPI downloads.
- **Canonical installer endpoint polish.** The hosted shell endpoint is the documented curl-bash path, the Windows PowerShell endpoint is documented as the native bootstrap, and pinned install examples now target `0.14.0` artifacts.
- **TUI activity and readability refinements.** Tool/agent headers use calmer grey styling, agent task names resolve at call time, live spinner rows stay pinned while status output clips, oversized output is capped, markdown rendering is cleaner, and shell activity indicators are more stable.
- **Release and CI hardening.** Plugin downloads are stricter, pythinker-home sync dispatch now skips when its optional repository-dispatch secret is absent instead of failing the main branch, and release documentation was refreshed for the native installer flow.

Upgrade with `pythinker update`, `pip install --upgrade pythinker-code==0.14.0`, or use the native installer for your OS (see the README install table).

## 0.13.0 (2026-05-22)

### What changed in this release

- **Native installers for macOS and Linux.** `brew install mohamed-elkholy95/pythinker/pythinker-code` (Homebrew tap) covers both macOS (Intel + Apple Silicon) and Linux brew installs from a single auto-generated formula. Debian/Ubuntu users get `pythinker-code_x.y.z_<arch>.deb` and Fedora/RHEL/openSUSE users get `pythinker-code-x.y.z.<arch>.rpm`, both attached to every GitHub Release for `x86_64` and `aarch64`. Together with the Windows `PythinkerSetup-x.y.z.exe` shipped in 0.12.0, Pythinker now ships native installers for every supported platform — no Python, Node, or `uv` prerequisite.
- **Cross-OS curl-bash native installer.** `curl -fsSL https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/scripts/install-native.sh | bash` detects your OS + arch, downloads the matching PyInstaller-frozen tarball from the latest Release, verifies its SHA-256, and lands the binary at `~/.local/bin/pythinker`. Supports `linux-x86_64`, `linux-aarch64`, and `macos-arm64`. Honors `--version`, `--prefix`, and `NO_COLOR`.
- **Homebrew tap auto-published on every release.** A new `.github/workflows/homebrew-tap.yml` waits for the PyPI publish to land, runs an in-tree formula generator (replaces the unmaintained `homebrew-pypi-poet` — see release notes for the why), and pushes `Formula/pythinker-code.rb` to the `homebrew-pythinker` tap repo. 132 transitive deps are enumerated automatically — no hand-curation per release.
- **Tag-triggered Linux package pipeline.** A new `.github/workflows/linux-installer.yml` matrix-builds `.deb` and `.rpm` for `x86_64` and `aarch64` (the latter via QEMU on `ubuntu-latest`), then uploads all six artifacts to the GitHub Release via `softprops/action-gh-release@v2`.
- **Frozen-binary data-files fix.** The PyInstaller specs for both the Windows and Linux pipelines now call `collect_data_files(pkg, include_py_files=False)` per package, so `pythinker_code/prompts/*.md`, `agents/default/*.yaml`, `tools/*/description.md`, `skills/*/SKILL.md`, and similar package resources are bundled into `_internal/`. Without this fix the frozen binary crashed the first time it tried to load `init.md` or an agent yaml. The Windows installer that shipped in 0.12.0 is affected; users on that build should upgrade to 0.13.0.
- **Legacy install paths deprecated.** `scripts/install.sh`, `scripts/install.ps1`, `uvx pythinker-code`, `uv tool install pythinker-code`, `pipx install pythinker-code`, and bare `pip install pythinker-code` continue to work for existing automation. The two helper scripts now print a `[DEPRECATED]` banner at startup, pause 3 s, and point at the OS-specific native installer; set `PYTHINKER_INSTALL_QUIET_DEPRECATION=1` to suppress the banner. README Quick Start now leads with the per-OS install table.

Upgrade with `pythinker update`, `pip install --upgrade pythinker-code==0.13.0`, or use the native installer for your OS (see the README install table).

## 0.12.0 (2026-05-22)

### What changed in this release

- **Native Windows installer.** A signed `PythinkerSetup-x.y.z.exe` is now attached to every GitHub Release — install Pythinker on Windows with one download, no Python / Node / uv prerequisite. The wizard installs per-user (no UAC) into `%LOCALAPPDATA%\Programs\Pythinker`, registers `pythinker` on the user PATH, and broadcasts `WM_SETTINGCHANGE` so new shells pick the change up immediately. Uninstall reverses the PATH edit. Code-signing is wired through `signtool` and ships unsigned until the Authenticode cert lands; from that point forward the same CI job produces signed installers with no code change required.
- **In-app updates for the native build.** `pythinker update` from a native install detects the build (via a `.pythinker-native` sentinel next to `pythinker.exe`), fetches the latest GitHub Release asset, verifies its SHA-256, and re-runs the installer silently (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`). The `PYTHINKER_CLI_NO_AUTO_UPDATE` opt-out env var that the PyPI path already honors now also gates the native auto-update path — one knob, both flows. The update banner shows a human-readable `PythinkerSetup-x.y.z.exe` line instead of leaking internal markers.
- **Tag-triggered Windows build pipeline.** A new `.github/workflows/windows-installer.yml` runs on every `pythinker-code-v*` tag, freezes `pythinker` via PyInstaller (`--onedir` for faster startup and fewer AV false positives), compiles the Inno Setup script, signs the result if `WINDOWS_CERT_PFX_BASE64` / `WINDOWS_CERT_PASSWORD` secrets are populated, and uploads the `.exe` plus its `.sha256` to the corresponding Release.
- **Shell terminal rhythm refinements.** Tone tokens, motion timing, and theme palette were retuned (sky-blue `#7dd3fc` / `#93c5fd` accents) so transcript rows, motion status, and dialog surfaces breathe consistently. UI snapshot tests updated to lock the new rhythm in place.

Upgrade with `pythinker update`, `pip install --upgrade pythinker-code==0.12.0`, or — on Windows — download `PythinkerSetup-0.12.0.exe` from the Releases page.

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
