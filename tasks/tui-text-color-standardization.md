# Plan: Standardize TUI text/font colors (markdown + agent/subagent)

**Status**: Scouting complete — awaiting design decisions before implementation.
**Created**: 2026-05-24
**Branch**: `feat/tui-brand-rebrand`
**Scope (confirmed by user)**: Keep the coral brand. Standardize *text/font colors* — the
agent/subagent and markdown text colors are the main issue. NOT touching box-drawing
corners, status-glyph vocabulary, or pi's actual color values.

---

## Reference

Design ported from `blackbox/pi-main` (TypeScript/Rich-equivalent). Pythinker already
ported pi's **core token names** (`accent`, `border`, `tool_success_bg`, …) onto the
branded `TuiTokens` palette during this branch. Values diverge by design:
- Pythinker `accent`: **blue** (`#5EA7E8` dark / `#256EA8` light, theme.py:415)
- Pythinker coral brand: logo (`_LOGO_CORAL=#EE9983`) + verb-spinner shimmer (motion.py)
- pi `accent`: teal `#8abeb7`

The brand is intentionally different from pi. The "coral brand" the user refers to is the
logo/shimmer coral, not the structural accent token.

---

## Root cause (the "main issue")

There are **two parallel color systems** in `src/pythinker_code/ui/theme.py`:

1. `TuiTokens` (theme.py:368+) — the branded coral source of truth. Everything routed
   through `tui_rich_style()` / `fg()` / `ShellTone` already resolves here.
2. `MarkdownColors` (theme.py:218–265) — a **separate, hardcoded** palette
   (`heading=#F4F4F5`, `emphasis=#A3A3A3`, `inline_code=#AFE3F1`, …) that is **not**
   derived from `TuiTokens`.

`MarkdownColors` is consumed *only* by `components/markdown.py:_markdown_style_overrides`,
which is the render path for:
- assistant messages (`components/messages.py:67,99,144`)
- special messages — skill / compaction / branch summaries (`components/special_messages.py`)
- worklog, blocks, question panel (`visualize/_worklog.py`, `_blocks.py`, `_question_panel.py`)

**Consequence:** markdown/prose text colors are maintained independently of the brand
tokens. Some values coincide (`link=#AFE3F1` == `info` token) but they drift separately,
and the coral brand never reaches prose.

### Agent/subagent specifics
- `tool_renderers/agent.py` already routes its *chrome* (header, prompt preview, icons)
  through tokens correctly.
- BUT subagent **result text** is rendered by `format_lines_block(... style_token="tool_output")`
  (agent.py:129–134) as **flat single-color lines, not markdown**. So when a subagent
  returns markdown, it shows as flat grey `tool_output` text — visually inconsistent with
  how the assistant's identical markdown renders.

---

## Decisions

- [x] **D1 — Markdown accent role.** RESOLVED: **low-chrome, no coral in prose.** Keep
      the current visual mapping; re-source it from `TuiTokens` for a single source of
      truth. Zero visual change to prose.
- [x] **D2 — Subagent output.** RESOLVED: **keep flat (no markdown parsing)**, ensure the
      color derives from the unified `tool_output` token. (agent.py:133 already passes
      `style_token="tool_output"` → already token-backed. Likely a no-op; verify.)

## ⚠️ Open observation — `accent` token is BLUE, not coral

The structural `accent` token is **blue** (`#5EA7E8` dark / `#256EA8` light, theme.py:415).
Coral `#EE9983` appears only in the **logo** (`__init__.py:1767 _LOGO_CORAL`) and the
**verb-spinner shimmer** (`motion.py:32-38`, marked `brand-exception`). So the current
brand is *blue structural accent + coral logo/motion*. User said "we need coral brand" —
needs a decision on whether `accent` should flip to coral (separate from the markdown work).

---

## Value-preserving token mapping (verified against theme.py:414-475)

Every `MarkdownColors` field equals an existing token in BOTH themes, except
`code_block_bg` (markdown-only). So re-sourcing is a pure refactor — no visual change.

| MarkdownColors field | Dark / Light value | Token (same value) |
|---|---|---|
| heading | #F4F4F5 / #213853 | `tool_title` |
| strong | #F4F4F5 / #213853 | `tool_title` |
| emphasis | #A3A3A3 / #666666 | `muted` |
| inline_code | #AFE3F1 / #176B7E | `info` |
| link | #AFE3F1 / #176B7E | `info` |
| quote | #A3A3A3 / #666666 | `muted` |
| table_border | #2B3A52 / #C8BEC0 | `border_muted` |
| code_block_border | #2B3A52 / #C8BEC0 | `border_muted` |
| spinner_active | #AFE3F1 / #176B7E | `info` |
| spinner_done | #7BC97F / #2C7A39 | `success` |
| spinner_failed | #EF5E62 / #C0392B | `error` |
| code_block_bg | #1f2030 / #f1f5f9 | **none** → add new `code_block_bg` token |

## Proposed plan

1. **Add `code_block_bg` token** to `TuiTokens` (#1f2030 dark / #f1f5f9 light) +
   `TUI_TOKEN_NAMES` → `verify`: token tests pass.
2. **Rebuild `_MARKDOWN_DARK`/`_MARKDOWN_LIGHT`** to read every field from the token
   palette instead of hardcoded hex (keep the `MarkdownColors` dataclass + `get_markdown_colors`
   API unchanged so `markdown.py` needs no structural change) → `verify`: resolved values
   byte-identical to current; `tests/ui_and_conv/` snapshots unchanged.
3. **Confirm subagent output** is token-backed (agent.py:133) → `verify`: no raw color in path.
4. **Text/copy micro-pass** (only if quick, in scope): standardize error-message
   punctuation (setup.py:44 vs oauth.py:165).
5. **Run full TUI suite** + lint/format.

---

## Out of scope (flagged, not doing)

- Switching `box.ROUNDED` → pi's square corners (visible change, fights the rebrand).
- Flattening pythinker's 7 status glyphs to pi's 4 (`✓`/`✗`).
- Porting pi's fixed-hex syntax theme — pythinker's `ANSISyntaxTheme`
  (`utils/rich/syntax.py`) is terminal-native and *better*; porting pi's would regress it.
- Per-thinking-level border colors (pi has 6; pythinker has the levels but one color).
  Genuinely portable later, but it's a *new feature*, not text-color standardization.
- Centralizing prompt symbols (`✨`/`›`/`$`) into `glyphs.py` — tidiness, separate task.

---

## Broader roadmap (from deep scan — validated 2026-05-24)

Source: TUI deep scan analysis vs pi-main. Claims below have been validated against actual
source files. See correction notes.

**Correction notes** (errors in the raw analysis, do not carry into work):
- Analysis claims `accent="#EE9983 (coral)"` — WRONG. Actual: `#5EA7E8` dark / `#256EA8`
  light (theme.py:415). Coral is logo/shimmer only.
- Analysis claims "restart required for theme switching" — WRONG. `/theme` slash command
  exists (tips.py:17); `set_active_theme()` called at runtime (__init__.py:545).
- Analysis claims "$COLORFGBG fallback" for terminal detection — UNCONFIRMED. No such code
  found in source.

### P1 — Thinking level color gradient (0.5 day, medium impact)

Port pi's 6 thinking-level border tokens into TuiTokens. Pythinker already exposes all 6
levels (off/minimal/low/medium/high/xhigh) in the ThinkingLevel literal (selectors/thinking.py:7)
but has only one `thinking_text` color. pi maps levels to a gradient from muted→vivid.

Proposed tokens to add to TuiTokens:
```
thinking_off:     ""          # no border tint (terminal default)
thinking_minimal: "#6e6e6e"   # subtle
thinking_low:     "#5f87af"   # blue-grey
thinking_medium:  "#81a2be"   # blue
thinking_high:    "#b294bb"   # purple
thinking_xhigh:   "#d183e8"   # vivid purple
```
Use in the thinking block renderer to color the border by active level.

### P1 — Missing markdown tokens (0.5 day, medium impact)

Add to MarkdownColors (and route through TuiTokens after Phase 0):
- `md_quote_border` — separate from quote text color
- `md_hr` — horizontal rule color
- `md_list_bullet` — bullet/number color (currently reuses `quote`)
- `md_link_url` — URL part of links (currently same as link text)

### P2 — Syntax highlighting token system (2–3 days, medium impact)

Create a bridge that maps TuiTokens syntax fields → Rich/pygments ANSISyntaxTheme,
replacing the current standalone PYTHINKER_ANSI_THEME with one that respects the active
brand palette. Tokens to add: `syntax_comment`, `syntax_keyword`, `syntax_function`,
`syntax_variable`, `syntax_string`, `syntax_number`, `syntax_type`, `syntax_operator`,
`syntax_punctuation`.

Note: pythinker's current ANSISyntaxTheme is *terminal-native* (uses ANSI color names,
not hex) which is actually the right approach. A bridge that passes through the terminal
palette is preferable to pi's hard-coded VS-Code hex approach. Preserving terminal-
adaptability is a feature.

### P2 — Terminal background auto-detection (1 day, nice-to-have)

Auto-select dark/light theme on startup by detecting terminal background color. pi uses
OSC 11 query → $COLORFGBG env var → luminance analysis. Fallback chain should be:
OSC 11 → COLORFGBG → TERM heuristics → "dark".

Note: pythinker currently has no terminal background detection (no COLORFGBG code found).

### P3 — JSON theme file system (3–4 days, high architectural impact)

Externalize TuiTokens + MarkdownColors + DiffColors as JSON files with a `vars` section
for color aliasing. Enable user custom themes in `~/.pythinker/themes/`. This is the
highest-leverage infrastructure investment — it unlocks runtime switching, hot-reload,
and user customization without code changes.

Implementation shape:
1. `ui/theme_loader.py` — JSON parser with var indirection + circular detection + schema validation
2. Built-in `dark.json`/`light.json` as package data (ship with pythinker-code)
3. User override search path: `~/.pythinker/themes/<name>.json`
4. `set_active_theme()` gains `theme_name` param; resolves from loader

Note: The `/theme` command already exists for dark/light switching (tips.py:17). This
phase extends it to arbitrary named themes.

### P3 — Component-level theme factories (1–2 days, architecture)

Add bridge factories matching pi's `getMarkdownTheme()` / `getEditorTheme()` pattern:
```python
def get_markdown_component_theme() -> MarkdownComponentTheme: ...
def get_prompt_component_theme() -> PromptComponentTheme: ...
def get_tool_render_theme() -> ToolRenderTheme: ...
```
Reduces consumers needing to know token names directly. Lower priority — current
`tui_rich_style()` API is workable.

---

## Review section

_(to be filled after implementation)_
