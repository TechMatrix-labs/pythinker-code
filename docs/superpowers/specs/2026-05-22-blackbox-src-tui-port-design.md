# Blackbox src Big-Bang TUI Port Design

**Date:** 2026-05-22
**Status:** Approved
**Scope:** Full Pythinker shell TUI restyle and feature audit using `blackbox/src` as the reference

---

## Problem

Pythinker's shell TUI works, but its live work display, thinking indicator, subagent rendering,
approval panels, prompt footer, slash-command surfaces, and report-style outputs are not yet using
one consistent terminal design language. Long-running agent work can repaint large cards repeatedly,
subagent activity can dominate the viewport, and footer/context information competes with the live
transcript.

The requested direction is an aggressive, big-bang restyle: use `blackbox/src` as the comprehensive
reference for terminal UI behavior, including spinner/thinking display, approval windows, prompt
surfaces, agent/task screens, useful prompt patterns, and design-system primitives.

---

## Goal

Port every useful terminal-facing design and behavior pattern from `blackbox/src` into Pythinker's
Python Rich/prompt_toolkit shell while preserving Pythinker's runtime architecture, wire protocol,
provider model, approval semantics, config compatibility, and no-new-dependency constraint.

"Full port" means:

1. Audit all `blackbox/src` terminal UI, command, prompt, permission, task, agent, and tool-display
   areas for applicable behavior.
2. Recreate the useful patterns in Pythinker's Python codebase using local Rich and prompt_toolkit
   primitives.
3. Standardize Pythinker shell views around one shared design system.
4. Add or adapt user-facing features only when they map cleanly to Pythinker's existing product
   model and do not introduce new hosted services or incompatible runtime assumptions.

It does not mean vendoring the TypeScript/React/Ink renderer, copying product-specific services
verbatim, adding external dependencies, or changing Pythinker's core agent protocol solely to match
Blackbox internals.

---

## Blackbox Areas To Audit And Port

### Design System

Reference directories:

- `blackbox/src/components/design-system/`
- `blackbox/src/components/ui/`
- `blackbox/src/ink/`

Port into Python render primitives:

- color roles and status styles
- status icons
- dividers
- keyboard shortcut hints
- bylines and secondary metadata
- panes/dialog shells
- list rows and selected-row states
- compact progress/loading states
- tab-like segmented choices where useful
- width-aware wrapping and truncation rules

Pythinker should keep Rich as the renderer. Blackbox's Ink renderer should inform layout rules, not
be copied as a runtime.

### Live Transcript And Messages

Reference directories:

- `blackbox/src/components/messages/`
- `blackbox/src/components/Spinner/`
- `blackbox/src/components/tasks/renderToolActivity.tsx`

Port behavior:

- one consistent transcript grammar for user, assistant, tool, error, notification, and system rows
- collapsed thinking by default, expanded thinking in verbose/transcript-style modes
- single-line active thinking/composing status with spinner glyph, elapsed time, token counts, and
  interrupt hints
- stalled/no-token visual state, reduced-motion behavior, and responsive hiding of secondary status
  parts
- grouped tool-use output summaries
- compact active subagent/teammate rows
- detailed finished cards only when a tool result has meaningful content

### Prompt Input And Footer

Reference directories:

- `blackbox/src/components/PromptInput/`
- `blackbox/src/hooks/usePromptSuggestion.ts`
- `blackbox/src/services/PromptSuggestion/`

Port behavior:

- stable footer segments for mode, model/provider, context, approvals, background work, and hints
- standardized `esc`, history, slash-command, file mention, shell-mode, and agent-selection hints
- input mode indicator styled consistently with the transcript
- queued/stashed prompt notices when equivalent state exists in Pythinker
- prompt suggestions only where they can be implemented locally and safely
- shimmered/working input state during active agent work

### Approval, Permission, And Modal Windows

Reference directories:

- `blackbox/src/components/permissions/`
- `blackbox/src/components/design-system/Dialog.tsx`
- `blackbox/src/components/TrustDialog/`
- `blackbox/src/components/*Dialog.tsx`
- `blackbox/src/services/mcpServerApproval.tsx`

Port behavior:

- a shared modal/dialog shell for approval, question, trust, MCP, config, task, and picker flows
- clear titles, risk explanations, primary/secondary choices, and keyboard hints
- file edit/write/read, shell, web, skill, MCP, plan-mode, sandbox, and fallback permission variants
  mapped onto Pythinker's existing approval runtime
- approval decisions must remain backed by Pythinker's current policy and wire events
- no bypass of existing approval enforcement

### Agents, Tasks, Teams, And Background Work

Reference directories:

- `blackbox/src/components/agents/`
- `blackbox/src/components/tasks/`
- `blackbox/src/components/teams/`
- `blackbox/src/tools/AgentTool/`
- `blackbox/src/tasks/`

Port behavior where it maps to Pythinker:

- compact agent/task status lines in the live transcript
- detail dialogs for background tasks and subagents
- agent list/detail/editor-style screens for Pythinker agent specs and subagent types
- tool selection affordances for agent creation/editing when compatible with Pythinker specs
- background task stop/detail/output actions using existing Pythinker task APIs
- useful agent prompt patterns and built-in agent taxonomy ideas, adapted to Pythinker's YAML
  agent-spec system and skill model

### Commands And Utility Screens

Reference directories:

- `blackbox/src/commands/`
- `blackbox/src/components/HelpV2/`
- `blackbox/src/components/Settings/`
- `blackbox/src/components/mcp/`
- `blackbox/src/components/memory/`
- `blackbox/src/components/diff/`
- `blackbox/src/components/StructuredDiff/`

Audit and port applicable command-display patterns for:

- help/keybindings
- model/provider selection
- usage/cost/rate-limit displays
- status/context/compact screens
- MCP server/tool views and approval screens
- plugin/skills screens
- config/settings validation screens
- session/resume/export/share-style views where Pythinker has an equivalent
- diff, review, plan, todos, memory, and task displays

The work should not add product-specific hosted integrations unless the maintainer separately
approves them.

### Tools And Tool Result Displays

Reference directories:

- `blackbox/src/tools/`
- `blackbox/src/components/messages/AssistantToolUseMessage.tsx`
- `blackbox/src/utils/groupToolUses.ts`
- `blackbox/src/services/toolUseSummary/`

Port display behavior:

- human-friendly labels for read/search/edit/write/shell/web/MCP/skill/agent/todo/plan tools
- grouped tool summaries for batches of related work
- compact running rows and richer completed cards
- structured shell output previews with failure emphasis
- structured diffs and file edit summaries
- tool rejection and fallback error messages that are clear but not noisy

Tool semantics stay in Pythinker. This design targets rendering, grouping, and UI affordances first.

### Prompts, Output Styles, And Skills

Reference areas:

- `blackbox/src/constants/systemPromptSections.ts`
- `blackbox/src/utils/systemPrompt.ts`
- `blackbox/src/outputStyles/`
- `blackbox/src/skills/bundled/`
- `blackbox/src/tools/AgentTool/builtInAgents.ts`
- `blackbox/src/services/autoDream/`
- `blackbox/src/services/MagicDocs/`

Audit and adapt useful ideas:

- reusable prompt sections that improve TUI-facing agent behavior
- concise tool-summary prompt patterns
- output style concepts that can map to Pythinker's agent specs or shell settings
- bundled skill ideas that fit Pythinker's skill system
- memory/docs/task prompt patterns only if they do not introduce new services, unsafe automation, or
  incompatible persistence models

Prompt changes must be tested through focused invariants and must preserve Pythinker's existing
provider-aware behavior.

---

## Proposed Pythinker Architecture

### Shell Design System Layer

Add a focused Python shell design-system layer under `src/pythinker_code/ui/shell/`, split into
modules such as:

- `design.py` or `theme.py` for color roles, status styles, icons, and typography helpers
- `motion.py` for spinner frames, reduced motion, elapsed time, token counters, shimmer/stall state
- `layout.py` for responsive truncation, segment hiding, and compact row composition
- `dialogs.py` for shared approval/question/modal shells
- `transcript.py` for user/assistant/tool/message rows if current files become too broad

These helpers should be private shell UI infrastructure until another package needs them.

### Live View Restyle

Refactor the live render path around a consistent transcript model:

- assistant content remains streamed in the current turn
- active thinking/composing renders as one compact status row
- active tools render as compact rows
- active subagents render as a capped tree of responsive rows
- completed tools flush as compact rows or detailed cards depending on content
- notifications and errors use the same row grammar
- context/model/status moves into a stable footer instead of competing with live output

This keeps `_LiveView` wired to the existing wire events while reducing repaint height and noise.

### Prompt And Footer Restyle

Standardize prompt_toolkit-facing shell components:

- footer segments use shared style primitives
- mode and context indicators share names/colors with the transcript
- slash autocomplete, suggestions, history search, and queued input states get consistent selected
  row, hint, and divider styling
- interrupt and background-agent hints are width-aware

### Approval And Modal Restyle

Introduce a shared approval/modal renderer and map existing approval flows onto it:

- shell command approvals
- file edit/write approvals
- web/MCP/skill/tool approvals
- plan/question approvals
- trust/config/MCP setup and validation screens where Pythinker has matching flows

The renderer can change presentation only. Approval state and policy decisions remain in
`ApprovalRuntime` and existing wire events.

### Agent And Task Screens

Use Blackbox agent/task UX as a reference for Pythinker equivalents:

- list subagents/background tasks compactly
- open detail views for task output and metadata
- provide stop/return-to-task affordances where existing commands support them
- expose agent specs and tool availability with a consistent list/detail design

Agent prompt or built-in agent additions should be handled as separate, tested changes inside this
same program of work, not mixed into renderer-only commits.

---

## Compatibility And Boundaries

The restyle must preserve:

- CLI flags and command compatibility
- persisted session compatibility
- wire event compatibility unless a migration is explicitly designed
- existing approval behavior
- provider-aware model/usage scoping
- telemetry behavior and opt-out semantics
- existing Pythinker config keys
- no new third-party dependencies without explicit maintainer approval

Out of scope for this design unless later approved:

- vendoring Blackbox's TypeScript, React, Ink, or custom renderer code
- adding Blackbox-hosted services, telemetry endpoints, account flows, or unrelated cloud features
- changing Pythinker into a different product model
- porting code that has no Pythinker equivalent and no user-facing terminal value

---

## Data Flow

No first-order protocol rewrite is required.

- Existing wire events continue to drive live shell rendering.
- `_LiveView` maps events into transcript rows, active status rows, compact tool rows, cards, and
  modal renderables.
- `_StatusBlock` or its replacement maps runtime state into footer segments.
- Existing prompt_toolkit components consume shared shell styling helpers.
- Approval requests continue through `ApprovalRuntime` and current wire projections.
- Tool results continue to use existing display blocks, with richer grouping/rendering layered on
  top.

If a Blackbox-inspired feature needs data Pythinker does not currently expose, prefer a small
optional field on an existing UI-facing data structure. Do not block the entire restyle on protocol
extensions.

---

## Error Handling

Errors should be explicit, concise, and visually differentiated:

- failed tools show a red status row plus the shortest actionable message
- denied or dismissed actions use muted denied/interrupted styling
- approval windows show risk context without dumping raw payloads
- unknown tools still render as generic tool rows
- unknown display blocks continue to degrade gracefully
- interrupted turns finalize live rows as interrupted and leave readable scrollback
- long shell/tool output stays previewed or paged rather than flooding the transcript

---

## Testing Strategy

Use focused tests before broad checks.

Add or update tests under `tests/ui_and_conv/` for:

- spinner/motion frames, reduced motion, elapsed/token/stalled-state rendering
- collapsed and expanded thinking display
- compact active tool rows
- compact subagent/task trees with width-aware truncation
- completed tool cards for shell, diff, todos, plans, web/MCP, skill, and agent results
- approval/modal variants for shell, file, web/MCP, skill, plan/question, and fallback approvals
- prompt footer segment rendering
- slash autocomplete/history/search selected-row styling
- usage/model/MCP/plugin/auth/info screen rendering where touched
- cleanup/interrupt behavior
- narrow and wide terminal captures

Run the smallest relevant gates during implementation, then before completion:

- focused pytest targets for changed renderers
- `make check-pythinker-code`
- visual smoke test with `uv run pythinker --yolo --prompt "scan code base "`
- targeted CLI smoke tests using `uv run pythinker --yolo --prompt ...` where practical

If broader command surfaces are changed, add command-level parsing/rendering tests.

---

## Acceptance Criteria

- The live TUI uses a Blackbox-inspired, Pythinker-native transcript grammar across user,
  assistant, thinking, tool, subagent, notification, and error rows.
- Thinking/composing is compact, animated, interruptible, width-aware, and supports reduced motion.
- Active subagents and background tasks render as compact trees or rows instead of tall repainting
  cards.
- Approvals, questions, and modal windows use a shared dialog system and preserve existing approval
  enforcement.
- Prompt footer, slash autocomplete, history search, shell mode, and shortcut hints use the same
  design language as the live transcript.
- Tool results, plans, todos, diffs, shell output, MCP/plugin/auth/info/usage screens, and other
  shell views use shared primitives where practical.
- Useful Blackbox agent, prompt, output-style, and skill ideas are audited and adapted only when
  compatible with Pythinker's architecture and safety rules.
- No new third-party dependencies, hosted services, telemetry behavior, or provider fan-out are
  introduced by the restyle.
- Existing CLI flags, wire events, persisted sessions, approvals, and provider-aware behavior remain
  compatible.
- `uv run pythinker --yolo --prompt "scan code base "` runs successfully enough to exercise the
  live scan workflow, and the resulting TUI is visually evaluated for readable thinking status,
  compact subagent/tool activity, stable footer/context display, and non-overlapping layout.
- Focused UI tests and `make check-pythinker-code` pass before the implementation is called done.

---

## Implementation Notes

This should be planned as one coordinated restyle with review checkpoints, not as unrelated drive-by
edits. A practical implementation plan should split work by shell surface:

1. Inventory and mapping from `blackbox/src` to Pythinker shell modules.
2. Shared shell design primitives.
3. Motion/thinking/status row.
4. Transcript, tool, subagent, and task live rendering.
5. Approval/modal rendering.
6. Prompt/footer/autocomplete surfaces.
7. Command/report screens.
8. Agent/prompt/skill audits and compatible adaptations.
9. Focused tests, smoke tests, and final verification.

Each implementation step should keep behavior testable and avoid mixing renderer-only changes with
prompt/agent behavior changes unless the implementation plan explicitly calls for it.
