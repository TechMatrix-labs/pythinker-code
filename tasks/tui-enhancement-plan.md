# TUI / CLI Render Enhancement — Comprehensive Plan

Single source of truth for the terminal-UI render overhaul. Merges the validated spacing
standardization (Track A, `63 passed` baseline) with the markdown, file/diff, and hardening
tracks surfaced by the render investigations.

**Verified facts** (checked against the tree): `render_dialog()` exists at
`_dialog_shell.py:35`; Makefile has `check-pythinker-code` / `test-pythinker-code`; `uv` is
available; `markdown.py` uses a literal `Syntax(..., padding=(0,1))` (L58–63); `edit.py:117`
holds a stray `Text("")` while its second diff path (L161–162) already omits it.

---

## Design principles (best practices applied throughout)

> **Stream owns the gaps between blocks. Cards, panels, markdown, and code renderers own only
> their internal layout. The canonical blank row is `Text("")`; the prompt preamble uses a
> newline helper, not hand-written `endswith("\n")` guards.**

1. **One source of truth per visual concept** — a gap, glyph, hint string, color, or padding
   defined once and imported. No literals at call sites.
2. **Layered ownership of space** — never let two layers space the same seam (today's tinted-
   card double/triple-gap).
3. **Theme tokens, never raw colors** — every style via `tui_rich_style(token)` / the
   markdown palette. Zero `"grey50"` / `#hex` in render paths.
4. **One engine per job** — one diff renderer, one line-block helper, one truncation-hint
   formatter, one syntax highlighter.
5. **Deterministic + snapshot-tested** — pure render (state in → renderable out); golden tests
   prove refactors are behavior-preserving.
6. **Degrade gracefully** — `NO_COLOR`, `PYTHINKER_REDUCED_MOTION`, narrow widths; diffs use
   `+`/`-` markers, not color alone (a11y).
7. **Surgical, collision-aware migration** — tests green at every step; read each file's
   current (uncommitted) state before editing.

Baseline that must stay green:
```bash
uv run pytest tests/ui_and_conv/test_empty_think_part_indicator.py \
  tests/ui_and_conv/test_tui_card_tool_renderers.py \
  tests/ui_and_conv/test_visualize_running_prompt.py::test_render_agent_status_uses_compose_agent_output_not_compose -q
# expect: 63 passed
```

---

# TRACK A — Spacing standardization (authoritative; do first)

### A1. Add one spacing-primitive module
Create `src/pythinker_code/ui/shell/spacing.py`:
```python
from rich.text import Text

BLANK_ROW = Text("")
STREAM_GAP_ROWS = 1
SECTION_GAP_ROWS = 1

CARD_PADDING = (0, 1)          # untinted/success cards (horizontal only)
TINTED_CARD_PADDING = (0, 1)   # pending/error tinted cards (horizontal only)
DIALOG_PANEL_PADDING = (0, 1)
WORKLOG_PANEL_PADDING = (0, 1)
CODE_BLOCK_PADDING = (0, 1)

def blank_row() -> Text:
    return Text("")

def append_gap(renderables: list, rows: int = 1) -> None:
    for _ in range(rows):
        renderables.append(blank_row())

def ensure_prompt_newline(fragments) -> None:
    if fragments and not fragments[-1][1].endswith("\n"):
        fragments.append(("", "\n"))
```
**Rule:** no `Text(" ")` for vertical spacing — blank rows are `Text("")`.

### A2. Live stream owns inter-block spacing — `visualize/_live_view.py`
- `_ACTION_SPACER = BLANK_ROW` (or drop it and call `blank_row()`).
- Keep: *the live stream owns spacing between* content block / tool card / retry row /
  spinner / notification. Individual cards must not create external top/bottom spacing.
- Fixes the triple-row issue (tinted-pad-top + stream-spacer + tinted-pad-bottom).

### A3. Remove vertical padding from tinted tool cards — `components/tool_execution.py`
- `Padding(body, (1, 1), style=bg_style)` → `Padding(body, TINTED_CARD_PADDING, style=bg_style)`
  (`(0, 1)`).
- Result: pending/error keep the horizontal tint; no hidden top/bottom rows; gap between
  cards becomes exactly the stream spacer → pending/error/success/bash cards consistent.

### A4. Standardize intra-card spacing — `tool_renderers/edit.py`
- **Rule:** inside a tool card the `⎿` gutter is the separator; no blank rows between
  header / summary / result / diff.
- Remove the `Text("")` at `edit.py:117` (between `change_summary_text` and `diff_frame`).
  This matches `write.py` *and* edit.py's own second diff path (L161–162) → one rule across
  all three diff renders.
- Keep truncation hints glued to bodies (already consistent).

### A5. Centralize prompt-preamble newlines — `prompt.py`
- Replace every `if fragments and not fragments[-1][1].endswith("\n"): fragments.append(("","\n"))`
  with `ensure_prompt_newline(fragments)`.
- One policy: agent-status / modal-body blocks are newline-terminated; card-style separator =
  exactly one newline before the prompt label; non-card prompt = exactly one newline before
  `❯`.
- **The prompt layer owns the final gap before input** — this resolves the spinner-verb ↔
  prompt seam (don't rely on whatever the last live action happened to be). This is the home
  of the original "blank row under the spinner verb" request.

### A6. Move modal panel section gaps into `render_dialog()` — `_dialog_shell.py` (+ callers)
- `render_dialog()` (`_dialog_shell.py:35`) becomes the only place that inserts: body→options,
  options→footer, and body→footer (when no options) gaps, via `blank_row()`.
- Clean up callers `_approval_panel.py`, `_question_panel.py`, `_btw_panel.py` so they stop
  sprinkling `Text("")`. **Rule:** panels decide sections semantically; `render_dialog()`
  decides vertical rhythm.
- Keep `DIALOG_PANEL_PADDING = (0, 1)` (no top/bottom panel padding yet — preserve density).

### A7. Markdown/code spacing stays internal — `components/markdown.py`
- Replace the literal `Syntax(..., padding=(0, 1))` (L58–63) with `CODE_BLOCK_PADDING`.
- Do not add external blank rows around markdown/code. **Rule:** markdown/code own internal
  code-block padding only; stream/panels own external gaps.

### A8. Tests for the standard (add with the migration)
1. `blank_row().plain == ""`; no canonical spacer uses `" "`.
2. Live stream: content+spinner = one blank row; tool+tool = one blank row; no `Text(" ")`.
3. Tool cards: pending/error/success add no extra blanks around body; tinted+spacer == 
   untinted+spacer vertical gap count.
4. Diff: edit.py and write.py render summary immediately followed by diff lines.
5. Prompt preamble: status block → prompt = exactly one newline boundary; card separator
   appears once.
6. Dialogs: approval/question/footer gaps come from `render_dialog()`; callers add no blank
   separators beyond semantic body rows.

### A9. Migration order (collision-safe; tests after each step)
1. Add `spacing.py` + primitive tests.
2. Edit `_live_view.py` only →
   `uv run pytest tests/ui_and_conv/test_empty_think_part_indicator.py -q`
3. Edit `tool_execution.py`, `edit.py` →
   `uv run pytest tests/ui_and_conv/test_tui_card_tool_renderers.py -q`
4. Edit `_dialog_shell.py` + approval/question/btw callers →
   `uv run pytest tests/ui_and_conv/test_question_panel.py tests/ui_and_conv/test_visualize_running_prompt.py -q`
5. Edit `prompt.py` last.
6. Broad gate: `make check-pythinker-code && make test-pythinker-code`

---

# TRACK B — File / diff rendering unification

(Markdown/code untouched here; this is tool-card file output and diffs.)

### B1. Collapse two diff engines into one
- Today: `components/diff.py:render_diff` (plain, no highlight, used by tool cards) **and**
  `utils/rich/diff_render.py:render_diff_panel` (Pygments + line numbers + inline highlight).
- Make the panel engine the single engine; `_file_diff.py:diff_frame` calls it in a
  "compact" mode for inline cards. Removes duplicated line-number/marker/inline logic.
- **Wire the unused `width`** (`_file_diff.py:125` binds `_ = width`) so diffs respect
  terminal width instead of implicit wrapping.

### B2. Optional syntax highlighting in tool-card diffs/listings
- Add opt-in highlighting (lexer by extension via `utils/rich/syntax.py:PythinkerSyntax`) to
  `format_numbered_lines_block` and the compact diff, behind a theme/setting flag, reusing
  `_strip_background` so tints don't fight the card bg.

### B3. Line-number + truncation consistency
- Unify the line-number style token: tool renderers use `"muted"`, panels use `"dim"` → pick
  one.
- Unify line-number min-width (today 4 in `_render_utils`, 2 in `diff.py`/`diff_render.py`).
- One `EXPAND_HINT` formatter → `"… +{n} lines (ctrl+o to expand)"`; retire grep's
  `"... (N more lines …)"` and standardize the `…` glyph. Collapse the 8 scattered limits
  (write=10, grep=15, find=20, agent=6, ask_user=8, think=6, todo=12, bash=5) into a
  principled small/medium/large set in a constants module. Document the
  `__suppress_generic_expand_hint__` state flag.

Verification: golden tests for a diff (add/remove/context/inline), a wrapped long line at
narrow width, and a truncated listing with the unified hint.

---

# TRACK C — Markdown rendering polish

Chain: `markdown-it` → `utils/rich/markdown.py:Markdown` →
`components/markdown.py:PythinkerMarkdown`.

### C1. Theme-token bugs
- **H2 loses color** (`components/markdown.py:81`): add `color=heading` (matches H1/H3/H4).
- **Hardcoded `grey50`** in thinking paths (`visualize/_blocks.py`, 9+ sites) → a
  `tui_rich_style("thinking_text")` token so dark/light apply.
- Distinguish `markdown.link` vs `markdown.link_url` styling (currently identical).

### C2. Streaming correctness / perf
- Each flush re-parses the whole committed buffer (`_blocks.py:254`). Either parse only the
  new slice, or wire the already-written-but-unused `PythinkerMarkdownStream`
  (`components/markdown.py:192`); delete the dead path.
- Make hidden vs streamed thinking treatment consistent (plain `Text` vs Markdown).

### C3. Code-block ergonomics
- Optional line numbers in fenced code (today `Syntax()` has none).
- (Padding already handled by Track A7 `CODE_BLOCK_PADDING`.)

Verification: snapshots for H1–H4, lists, blockquote, table (wide→record), inline code, a
fenced python block; a streaming test asserting identical final render for 1-chunk vs
many-chunk arrival.

---

# TRACK D — Cross-cutting hardening

- **Theme-literal lint test:** fails if a render module imports a raw color name.
- **Render matrix:** parametrized snapshots at widths {40, 80, 120}, `NO_COLOR=1`,
  `PYTHINKER_REDUCED_MOTION=1`.
- **Marker-glyph registry:** centralize `●`, `⎿`, `❯`, `├`/`└`, `⧉`, spinner frames so the
  visual language lives in one place.

---

## Overall sequencing & risk

Order: **Track A → B → C → D.** A is the validated, highest-impact, lowest-risk track and
unblocks the rest. Each track = its own branch/commit set, tests green at every step.

Risks / guards:
- **Snapshot tests are the safety net** — regenerate and *review the diff* each step; an
  unreviewed snapshot update hides regressions.
- **Spinner-verb structural tests** (`test_empty_think_part_indicator.py`,
  `test_live_view_notifications.py`) constrain where the under-gap lives (Track A5).
- **Parallel agent:** stashes touch only `packages/pythinker-review/*` + `config`/`slash` —
  no overlap with these files. Target UI files carry uncommitted branch edits; layer on top.
- **Behavior-preserving claims** proven by before/after snapshot diff, never assumed.

**Definition of done:** one `spacing.py` + one render-constants module imported everywhere;
one diff engine; zero raw color literals in render paths; unified truncation hint; H2 +
thinking theme bugs fixed; `make check-pythinker-code && make test-pythinker-code` green plus
the width/`NO_COLOR`/reduced-motion snapshot matrix.

---

## Progress log

### Track A — DONE (2026-05-24)
- A1 `spacing.py` created (`BLANK_ROW`, gap/padding constants, `blank_row`, `append_gap`,
  `ensure_prompt_newline` typed against prompt-toolkit `StyleAndTextTuples`) + 10 unit tests.
- A2 `_live_view.py`: `_ACTION_SPACER = BLANK_ROW` (retired `Text(" ")`).
- A3 `tool_execution.py`: tinted card padding `(1,1)` → `TINTED_CARD_PADDING (0,1)` — kills the
  card/stream double-gap.
- A4 `edit.py`: removed stray `Text("")` between summary and diff (now matches write.py +
  edit.py's own 2nd diff path).
- A5 `prompt.py`: refactored every `endswith("\n")` guard to `ensure_prompt_newline()`; added
  the spinner-verb under-gap at the `_render_agent_status` chokepoint (interactive) and in
  `_live_view.compose()` gated on a non-empty status line (non-interactive).
- A6 `_dialog_shell.py` + approval/question/btw/worklog panels: section gaps via `blank_row()`,
  padding via `DIALOG_PANEL_PADDING`/`WORKLOG_PANEL_PADDING`.
- A7 `markdown.py`: code-block padding → `CODE_BLOCK_PADDING`.
- A8 added under-gap behavior tests (compose under-gap present / no-double-gap when empty).
- Verification: `make check-pythinker-code` clean; `tests/ui_and_conv` + `tests/ui` = 1183
  passed; new spacing/live-view tests = 20 passed. Behavior-preserving except the intended
  card-padding and under-gap changes.

### Track B — DONE (2026-05-24), look-preserving
Decision: the two diff renderers serve different surfaces (inline boxless tool-card diff =
the screenshot; `render_diff_panel`/`_preview` = boxed approval/worklog). "One engine
everywhere" would box-ify the inline diff → rejected by user. Unified via a shared module
instead.
- New `render_constants.py`: `DIFF_CONTEXT_LINES`, `DIFF_LINE_NUMBER_MIN_WIDTH`,
  `LISTING_LINE_NUMBER_MIN_WIDTH`, keymap-driven `expand_hint()` (+4 tests).
- Deduped the two `=3` context constants and `max(…,2)` widths across `components/diff.py`
  and `utils/rich/diff_render.py`; listing width floor via constant in `_render_utils.py`.
- Unified the truncation hint across grep/write/diff-preview — fixes a real bug: the panel
  preview hardcoded `ctrl-e` while the actual expand key is `ctrl+o`; also standardized the
  `…`/`...` glyph + phrasing.
- Verified inline diff stays boxless (matches screenshot); `tests/ui_and_conv`+`ui`+`utils`
  = 1526 passed; checks clean.
- Deferred (rationale): full word-diff engine merge (different internal representations —
  risky, low reward); syntax-highlighting tool cards (would change the boxless look);
  line-number token muted-vs-dim unification (marginal benefit, visible-change risk).

### Tracks C/D — PENDING
C: markdown theme bugs (H2 color, `grey50`→token, link vs link_url) + streaming re-parse /
dead `PythinkerMarkdownStream`. D: theme-literal lint test, width/`NO_COLOR`/reduced-motion
snapshot matrix, marker-glyph registry.
