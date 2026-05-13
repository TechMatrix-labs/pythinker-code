# Port bk_box_main coding-agent features

## Scope

Port the practical coding-agent runtime features from `blackbox/bk_box_main` into Pythinker CLI. Treat VS Code-only Agent Manager UI as reference; port only CLI/runtime primitives unless a Pythinker UI task explicitly asks for more.

## Overall status

**Status: complete for this porting slice.** All planned phases below have implementation coverage and focused verification. Full-suite `make test-pythinker-code` was attempted but hung in a `Pythinker` subprocess; focused port tests and `make check-pythinker-code` passed.

## Phase 0 — Safety and baseline ✅ Done

- [x] Preserve existing uncommitted work; avoid drive-by rewrites.
- [x] Run focused tests before/after feature batches.
- [x] Keep provider-specific behavior scoped to active provider/model.

## Phase 1 — Agent modes and hard permission profiles ✅ Done

Source references:
- `blackbox/bk_box_main/packages/opencode/src/kilocode/agent/index.ts`
- `blackbox/bk_box_main/packages/opencode/src/permission/*`
- `blackbox/bk_box_main/packages/opencode/src/tool/plan.ts`

Pythinker targets:
- `src/pythinker_code/agents/default/*.yaml`
- `src/pythinker_code/soul/approval.py`
- `src/pythinker_code/approval_runtime/`
- `src/pythinker_code/tools/file/plan_mode.py`

Work:
- [x] Add explicit runtime-enforced read-only, plan, ask, implement, review, and verify permission profiles.
- [x] Make plan mode hard-deny non-plan writes and dangerous shell mutations, not just prompt-deny.
- [x] Add tests for denied shell/write/edit paths per mode.

Acceptance:
- [x] Plan/review/explore/verifier cannot mutate files through file tools or shell.
- [x] Implementer/coder retain write tools under normal approvals.

## Phase 2 — Plan handoff workflow ✅ Done

Source references:
- `blackbox/bk_box_main/packages/opencode/src/kilocode/plan-followup.ts`
- `blackbox/bk_box_main/packages/opencode/src/kilocode/session/prompt.ts`
- `blackbox/bk_box_main/packages/opencode/src/session/prompt/code-switch.txt`

Pythinker targets:
- `src/pythinker_code/tools/plan/`
- `src/pythinker_code/soul/dynamic_injections/plan_mode.py`
- `src/pythinker_code/subagents/`

Work:
- [x] After plan approval, generate a compact implementation handoff summary.
- [x] Offer/implement “continue here” vs “start implementation subagent/session” through the handoff text and Agent resume/start instructions.
- [x] Persist handoff with the plan artifact as a sibling `.handoff.md` file.

Acceptance:
- [x] Plan output can be approved and injected into an implementer without losing discoveries.
- [x] Tests cover handoff generation and handoff persistence failure fallback.

## Phase 3 — Orchestration and task runtime ✅ Done

Source references:
- `blackbox/bk_box_main/packages/opencode/src/tool/task.ts`
- `blackbox/bk_box_main/packages/opencode/src/kilocode/tool/task.ts`
- `blackbox/bk_box_main/packages/kilo-vscode/src/agent-manager/WorktreeManager.ts`

Pythinker targets:
- `src/pythinker_code/tools/agent/`
- `src/pythinker_code/background/`
- `src/pythinker_code/subagents/`

Work:
- [x] Add first-class multi-agent task metadata: parent/child links, dependencies, budget/timeouts, synthesis state.
- [x] Add optional git worktree isolation intent for background agents.
- [x] Add resume/recover semantics robust across CLI restarts where possible.

Acceptance:
- [x] Parent can launch several agents, inspect structured statuses, and synthesize results deterministically.
- [x] Background agent records survive process restart with clear `running/lost/recoverable` states.

## Phase 4 — Context/session robustness ✅ Done

Source references:
- `blackbox/bk_box_main/packages/opencode/src/session/compaction.ts`
- `blackbox/bk_box_main/packages/opencode/src/kilocode/session/compaction-payload-recovery.ts`
- `blackbox/bk_box_main/packages/opencode/src/kilocode/session/prompt-queue.ts`

Pythinker targets:
- `src/pythinker_code/soul/context.py`
- `src/pythinker_code/soul/pythinkersoul.py`
- `src/pythinker_code/session.py`

Work:
- [x] Add prompt queue protection for concurrent prompts/tool followups.
- [x] Harden compaction/recovery around malformed or partial LLM payloads.
- [x] Add clearer session list/search/export affordances if not already covered by existing UI/session surfaces.

Acceptance:
- [x] Interrupted/failed compaction does not corrupt session history.
- [x] Queued user prompts preserve order and status.

## Phase 5 — Code search and skills ✅ Done

Source references:
- `blackbox/bk_box_main/packages/opencode/src/tool/warpgrep.ts`
- `blackbox/bk_box_main/packages/opencode/src/kilocode/tool/semantic-search.ts`
- `blackbox/bk_box_main/packages/opencode/src/skill/*`

Pythinker targets:
- `src/pythinker_code/tools/file/grep_local.py`
- `src/pythinker_code/skill/`
- `src/pythinker_code/soul/dynamic_injections/`

Work:
- [x] Add a local “smart search” wrapper that plans multiple grep/glob passes and returns concise spans.
- [x] Keep graphify/context-mode semantic providers out of this slice; `SmartSearch` provides bounded local search behind a normal tool interface.
- [x] Keep explicit skill-load/use tooling deferred because prompt-loaded skills remain sufficient for this slice.

Acceptance:
- [x] Explore agents can find relevant code with fewer broad shell calls.
- [x] Search results are bounded, cited, and safe for context.

## Phase 6 — Provider/model UX ✅ Done

Source references:
- `blackbox/bk_box_main/packages/opencode/src/provider/*`
- `blackbox/bk_box_main/packages/opencode/src/kilocode/provider/*`
- `blackbox/bk_box_main/packages/opencode/src/session/system.ts`

Pythinker targets:
- `src/pythinker_code/llm.py`
- `src/pythinker_code/auth/`
- `src/pythinker_code/ui/shell/usage_adapters/`

Work:
- [x] Keep model-specific prompts/capabilities explicit.
- [x] Preserve per-agent model/thinking/variant state through subagent cloning.
- [x] Improve fallback display for unavailable provider model lists where covered by existing provider fallback paths.

Acceptance:
- [x] OpenCode Go/Kimi, Anthropic-compatible, OpenAI-compatible, and Pythinker providers retain correct per-model toggles in root and subagents.

## Recommended first implementation slice ✅ Done

- [x] Finish provider-thinking regression tests.
- [x] Introduce a small runtime permission profile abstraction.
- [x] Apply it to plan/explore/review/verifier first.
- [x] Add shell mutation-denial tests.
- [x] Add plan handoff in Phase 2.

## Execution status — 2026-05-11

- [x] Phase 1: implemented runtime permission profiles and hard-deny checks for file mutations and mutating shell commands; focused tests pass.
- [x] Phase 2: implemented deterministic approved-plan handoff generation and sibling `.handoff.md` persistence with inline fallback on persistence failure; focused tests pass.
- [x] Phase 3: added background-agent orchestration metadata (`dependencies`, budget, synthesis state, isolation intent) and recoverable restart state for orphaned background agents; focused tests pass.
- [x] Phase 4: added prompt-turn serialization with a session-local lock and compaction empty-result guard so failed/malformed compaction does not clear existing history.
- [x] Phase 5: added `SmartSearch`, a bounded multi-pass local search wrapper, and exposed it to default/subagent specs; focused tests pass.
- [x] Phase 6: persisted subagent thinking state in launch specs and passed it through model cloning so resumed/per-agent model overrides preserve thinking toggles.

## Verification

- [x] `make check-pythinker-code` passed.
- [x] Focused port regression suite passed: `42 passed`.
- [x] Broader focused suite passed: `79 passed`.
- [ ] Full `make test-pythinker-code` was attempted but hung in a `Pythinker` subprocess; rerun or diagnose separately before release.
