# Agent Live Tool Stream — Design Spec

**Date:** 2026-05-26  
**Status:** Approved

## Problem

When a subagent is running inside an `Agent` tool call, the TUI shows only:
- The agent card header with a spinner
- Finished sub-tool calls in a static activity tree

In-flight sub-tool calls — the `Read`, `Bash`, `Glob` calls the agent is actively making — are tracked internally (`_ongoing_subagent_tool_calls`) but never rendered. The user sees a frozen card with no indication of what the agent is doing moment-to-moment.

## Goal

Show the agent "skimming and checking and reading files" in real time: ongoing sub-tool calls appear as shimmering live rows, and shell output streams in below the active call.

## Design

### Section 1 — Event Flow

`_live_view.py:handle_subagent_event()` currently ignores `ToolExecutionStarted` and `ToolOutputPart` subagent events with a "summarized at the parent Agent-card level for now" comment.

**Change:** forward both events into the parent `_ToolCallBlock` via two new methods:

```
SubagentEvent(event=ToolCall)            → block.append_sub_tool_call()           [already wired]
SubagentEvent(event=ToolCallPart)        → block.append_sub_tool_call_part()       [already wired]
SubagentEvent(event=ToolExecutionStarted) → block.mark_sub_execution_started()     [NEW]
SubagentEvent(event=ToolOutputPart)      → block.append_sub_output_part()          [NEW]
SubagentEvent(event=ToolResult)          → block.finish_sub_tool_call()            [already wired]
```

No changes needed to the wire protocol or event types — both event types already arrive via `SubagentEvent`.

### Section 2 — State in `_ToolCallBlock`

Two new fields added to `__init__`:

```python
self._subagent_output_parts: dict[str, list[str]] = {}
# Keyed by sub-tool tool_call_id. Accumulates ToolOutputPart chunks.

self._subagent_execution_started: set[str] = set()
# Sub-tool calls that have passed approval/hooks and are executing.
```

**`mark_sub_execution_started(tool_call_id)`**: adds to `_subagent_execution_started`, triggers recompose.

**`append_sub_output_part(tool_call_id, text)`**: appends to `_subagent_output_parts[tool_call_id]`. Silently discards if `tool_call_id` not in `_ongoing_subagent_tool_calls`. Triggers recompose.

**`finish_sub_tool_call()`** (existing, modified): also removes from `_subagent_output_parts` and `_subagent_execution_started` to free memory.

### Section 3 — Rendering

New layout inside the Agent card while running:

```
⠿ Agent(security-reviewer · Deep security code scan)     ← existing spinner
  ├─ agent  Read src/pythinker_code/session.py           ← NEW: shimmer (running)
  │    def _reset_live_shape(self, live: Live) -> None:  ← NEW: stdout preview
  │    live._live_render._shape = None
  └─ agent  Bash grep -n "SubagentEvent" ...             ← existing: completed
```

**Running rows**: `_ongoing_subagent_tool_calls` → `ActivityRow(state="running")` with shimmer, rendered *above* finished rows.

**Output preview**: for the single most-recent ongoing call that has streamed output, show the last 4 lines below its activity row. Lines are:
- Indented with `│  ` prefix (or `   ` on the last line)
- Truncated to `current_console_width() - 6` chars per line
- Styled `muted` for stdout, `error` for stderr

**Cap on running rows**: max 2 ongoing rows shown. If more in flight, prepend `… N more running` in muted style.

**Cleanup on finish**: output buffer discarded when the sub-call completes. The finished `ActivityRow` shows tool name + key arg only — no trailing output.

### Section 4 — Error Handling & Edge Cases

| Scenario | Handling |
|---|---|
| Args not yet fully streamed | `extract_key_argument` returns `None`; row shows bare tool name (e.g. `Read`) until path arrives |
| `ToolOutputPart` arrives before `ToolCall` | Silently discarded — `tool_call_id` not in `_ongoing_subagent_tool_calls` |
| Output buffer growth | Capped at 200 chars total per sub-call (keep tail, discard head); discarded on finish |
| Background-pending agents | By the time `_is_background_pending` is set, `_ongoing_subagent_tool_calls` is empty — no change needed |
| Card style (`is_card_style()`) | New rendering only touches the worklog `_compose()` path; `_compose_card()` / `tool_renderers/agent.py` unchanged (follow-up if needed) |
| Stderr mixed with stdout | Track `_subagent_output_had_stderr: dict[str, bool]`; use `error` style if any stderr seen |

## Files Changed

| File | Change |
|---|---|
| `src/pythinker_code/ui/shell/visualize/_live_view.py` | Forward `ToolExecutionStarted` and `ToolOutputPart` subagent events to block |
| `src/pythinker_code/ui/shell/visualize/_blocks.py` | New fields + methods on `_ToolCallBlock`; update `_compose()` to render running rows + output preview |

No changes to wire types, event bus, tool renderers, or activity tree.

## Out of Scope

- Card-style (`is_card_style()`) rendering — follow-up
- Multi-level nested subagents (agent spawning agent) — existing TODO in `_live_view.py`
- Showing subagent thinking/content blocks in the parent card
