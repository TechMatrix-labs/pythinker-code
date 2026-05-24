# Pythinker TUI brand rebrand + accessibility theme variants

**Date:** 2026-05-24
**Status:** Draft for review
**Scope owner:** TUI / shell rendering

## Summary

Propagate Pythinker's robot-mascot brand palette (coral / cyan / navy / cream)
across the entire interactive shell, replacing the generic catppuccin-style
colors currently hardcoded in the theme tokens and several bypass sites. Adopt
the structural polish and accessibility-variant *mechanics* from the reference
codebase `blackbox/src` (Claude Code's source) — **without** copying any of its
brand assets (Claude orange, the "Clawd" mascot, or Claude/Anthropic naming).

The visual architecture this depends on **already exists**: `ui/theme.py`
defines a `TuiTokens` semantic-token dataclass with per-theme variants resolved
by role (`accent`, `border`, `success`, `tool_pending_bg`, …) and a
`tui_rich_style()` resolver. This work changes **values**, closes **bypass
gaps**, adds **structural polish**, and extends the theme set with
**accessibility variants** — it does not introduce a new rendering engine. We
stay on Rich + prompt_toolkit; we do **not** port Ink/flexbox.

### Phasing (one spec, independently-mergeable phases)

This spec covers the full scope the user approved. The implementation plan will
deliver it in independently-mergeable phases so value ships incrementally:

- **Phase 1** — Rebrand token values (highest impact, one file).
- **Phase 2** — Close hardcoded-color bypass gaps (incl. `design_system.py`).
- **Phase 3** — Structural polish (rounded borders, coral spinner shimmer, footer alignment).
- **Phase 4** — Accessibility theme variants (ANSI-16 + daltonized) + theme set expansion.

> **Delivery decision (confirmed at review):** P4 stays in this spec as the
> intended end-state, but **does not block P1–P3**. The implementation plan ships
> **P1–P3 as the first PR** (rebrand + gap-closing + structural polish, dark +
> light) and **P4 as a clean follow-up phase/PR** (a11y variants + theme-set
> expansion). P4's getter-resolver refactor is sequenced first within P4.

## Brand source colors

Authoritative values, transferred from `web/dist/brand/icon.svg` (and already
used by the welcome logo at `ui/shell/__init__.py:1746-1761`):

| Role family | Hex | Notes |
|---|---|---|
| Coral (primary) | `#EE9983` | accent; the robot antenna/ears |
| Coral (deep) | `#DD786D` | accent on light backgrounds, emphasis |
| Coral (light) | `#F0AB9E` | hover/wash |
| Cyan | `#AFE3F1` | secondary / info; the robot's eyes |
| Navy | `#213853` | structure / outline / dark base |
| Slate | `#3A506D`, `#495F7C` | borders, secondary structure |
| Cream | `#F9F2F5`, `#F2EBEC` | light text, light-mode background |

The brand defines **no** semantic state colors, so `success` / `warning` /
`error` are proposed (harmonized) additions. **Error stays clearly red** so it
can never be confused with the coral accent.

## Out of scope / invariants

- **The robot welcome banner is already brand-correct.** `ui/shell/__init__.py:1746-1761`
  already uses `#213853 / #F9F2F5 / #EE9983 / #AFE3F1`. **No phase touches the
  `_LOGO` glyphs or its color constants.** The welcome *work* is the surrounding
  rows (`_value_style_for_label` hardcodes `cyan`/`magenta`/`yellow`/`grey39`).
- **Mascot display timing is unchanged:** the logo shows on **every launch**
  today; we keep that. *(Confirm at review that every-launch is intended; first-run-only / opt-in are alternatives but not part of this scope.)*
- No rendering-engine swap (no Ink/Textual). Rich + prompt_toolkit stay.
- No new runtime dependencies.

---

## Phase 1 — Rebrand token values

**File:** `src/pythinker_code/ui/theme.py` only.

Swap the dark/light values in `_TUI_TOKENS_*`, `_MARKDOWN_*`, `_PROMPT_STYLE_*`,
`_TOOLBAR_*`, `_MCP_PROMPT_*`, `_task_browser_style_*`, and `_DIFF_*` to
brand-derived colors. Add one new token, `info`, for the cyan secondary role
(touches the `TuiTokens` dataclass, both existing variant constructors, and
`TUI_TOKEN_NAMES`).

### Proposed `TuiTokens` — dark (terminal default background; foreground-driven, minimal bg fills)

| token | value | token | value |
|---|---|---|---|
| accent | `#EE9983` | selected_bg | `#243C54` |
| border | `#3A506D` | user_message_bg | `#1B2738` |
| border_accent | `#EE9983` | custom_message_bg | `#16242E` |
| border_muted | `#2B3A52` | custom_message_label | `#AFE3F1` |
| info *(new)* | `#AFE3F1` | tool_pending_bg | `#1B2230` |
| success | `#7BC97F` | tool_success_bg | `#16271C` |
| warning | `#E6B450` | tool_error_bg | `#2E1D24` |
| error | `#EF5E62` | tool_title | `#8B93A3` |
| muted | `#8B93A3` | tool_output | `#8B93A3` |
| dim | `#5F6B7E` | tool_diff_added | `#7BC97F` |
| text | `""` (default) | tool_diff_removed | `#EF5E62` |
| thinking_text | `#7FB4C4` | tool_diff_context | `#8B93A3` |
| activity_label | `#F2EBEC` | bash_mode | `#7BC97F` |

### Proposed `TuiTokens` — light (cream background; navy text)

**Two-tier light accents (contrast rule).** On cream `#FAF4F4`, the soft brand
hues are too weak for normal text: `#DD786D` coral = 2.77:1, `#2F8FA8` cyan =
3.44:1 (verified, WCAG). So light mode splits the roles:

- **Foreground / text tokens** (`accent`, `info`, `custom_message_label`) carry
  AA-safe darkened values: coral-text `#AE5430` (4.70:1, orange-leaning so it
  stays distinct from error red `#C0392B`), cyan-text `#176B7E` (5.61:1).
- **Border / background tokens** (`border_accent`, `*_bg`, `selected_bg`) keep
  the softer brand hues (`#DD786D` / `#2F8FA8` family) — fine for 1px rules and
  fills.

Navy text `#213853` on cream = 11:1. Dark mode is unchanged (reviewed as good).

| token | value | token | value |
|---|---|---|---|
| accent | `#AE5430` *(text-safe coral)* | selected_bg | `#F3D9D2` |
| border | `#495F7C` | user_message_bg | `#F0E4E4` |
| border_accent | `#DD786D` *(soft, border-use)* | custom_message_bg | `#E6F2F6` |
| border_muted | `#C8BEC0` | custom_message_label | `#176B7E` |
| info *(new)* | `#176B7E` *(text-safe cyan)* | tool_pending_bg | `#EFE7E8` |
| success | `#2C7A39` | tool_success_bg | `#E4F0E6` |
| warning | `#9A6B18` | tool_error_bg | `#F6E3E3` |
| error | `#C0392B` | tool_title | `""` |
| muted | `#5D6B80` | tool_output | `#5D6B80` |
| dim | `#8A93A0` | tool_diff_added | `#2C7A39` |
| text | `#213853` | tool_diff_removed | `#C0392B` |
| thinking_text | `#5D6B80` | tool_diff_context | `#5D6B80` |
| activity_label | `#213853` | bash_mode | `#2C7A39` |

### Secondary palette role mapping (strict — no implementation discretion)

The other palette tables map to brand roles by these fixed rules. "coral" =
`accent` token value for that theme (dark `#EE9983` / light text-safe `#AE5430`),
"cyan" = `info` (dark `#AFE3F1` / light `#176B7E`), "slate"/"navy" = `border`/
`border_muted`, "green/amber/red" = `success`/`warning`/`error`.

- **`_MARKDOWN_*`**: `heading` → coral; `strong` → coral; `emphasis` → muted;
  `inline_code` → cyan; `link` → cyan; `quote` → muted; `table_border` →
  border_muted; `code_block_border` → border_muted; `code_block_bg` → unchanged
  surface tint (dark `#1f2030` / light `#f1f5f9`); `spinner_active` → coral;
  `spinner_done` → success; `spinner_failed` → error.
- **`_PROMPT_STYLE_*`**: `compact-input.prompt` → coral bold; `*.frame` /
  separators → border_muted; completion `*.match` / `*.current` accents → coral;
  `*.row.current` bg → selected_bg; `shell-footer.warning` → warning;
  `shell-footer.error` → error; dialog title → text bold, dialog option current
  → selected_bg + coral.
- **`_TOOLBAR_*`**: `separator` → border_muted; `yolo_label` → warning bold;
  `auto_label` → coral bold; `plan_label`/`plan_prompt` → cyan; `cwd`/`tip` →
  dim; `bg_tasks`/`tip_key` → muted.
- **`_MCP_PROMPT_*`**: `text` → text; `detail` → muted; `connected` → success;
  `connecting` → cyan; `pending` → warning; `failed` → error.
- **`_task_browser_style_*`**: header bg stays a neutral surface; `header.title`/
  `frame.label`/`footer.key` → coral; `status.running`/`status.success` →
  success; `status.warning` → warning; `status.error` → error; `status.info` →
  cyan; `task-list.checked` → selected_bg + cyan; `footer.warning` → warning.
- **`_DIFF_*`**: `add_bg`/`add_hl` → success-tinted surfaces; `del_bg`/`del_hl`
  → error-tinted surfaces (keep current dark/light bg tints, re-keyed to the
  green/red brand semantics).

**Verification:** update `tests/ui_and_conv/test_tui_theme_tokens.py` and
`tests/ui_and_conv/test_theme.py` to assert the new brand values; regenerate
`tests/ui_and_conv/test_tui_render_snapshots.py` snapshots.

---

## Phase 2 — Close hardcoded-color bypass gaps

Route every remaining hardcoded literal through the token system so nothing
escapes the brand.

1. **`ui/shell/__init__.py` `_value_style_for_label`** — replace `cyan` /
   `magenta` / `yellow` / `grey39` / `grey50` literals with token lookups
   (`info`, `accent`, `muted`, …).
2. **`ui/shell/design_system.py` `_TONE_STYLES`** — **structural change, not a
   value swap.** Today it is a module-level `dict[ShellTone, Style]` built at
   import with catppuccin literals (`#A6E3A1`, `#F38BA8`, `#F2CC60`, `#B8D7FF`,
   …) and is **not theme-aware**. Convert the dict to a per-call resolver
   (`shell_style(tone)` maps `ShellTone` → token name → `tui_rich_style(...)`,
   honoring the active theme). Callers already invoke `shell_style()` as a
   function, so call sites are unaffected; only the storage is lifted.
3. **`ui/shell/startup.py`** — replace the literal cyan startup spinner with the
   `accent` token.
4. Sweep for any other `#`-literal or Rich-named colors in
   `ui/shell/**` that should be tokens; route them through `tui_rich_style` /
   `shell_style`. Document any intentional exceptions inline.

**Verification:** extend `tests/ui_and_conv/test_shell_design_system.py` to
assert tones resolve to brand tokens and switch with the active theme; extend
`tests/ui_and_conv/test_shell_welcome_info.py` for the rebranded rows.

---

## Phase 3 — Structural polish (from `blackbox/src`, recolored)

Adopt the *mechanics*, render with Pythinker brand colors.

1. **Rounded panel borders** — use Rich `box.ROUNDED` for shell panels/cards
   (matching blackbox's `borderStyle="round"`), with `border` (slate) for normal
   and `border_accent` (coral) for active/focused.
2. **Coral spinner shimmer** — apply a subtle shimmer (lightness/hue ramp) in
   the coral family to the active spinner and active border, mirroring
   blackbox's shimmer system. Respect the existing `PYTHINKER_REDUCED_MOTION`
   env var (no animation → static glyph). Spinner glyph frames/cadence stay as
   they are unless trivially improved; this item is about *color motion*, not
   new frames.
3. **Footer alignment** — tighten `components/footer.py` segment spacing and
   left/right alignment to the blackbox 3-line structure (pwd · stats · status),
   using `render_segment_line` and brand tokens.

**Verification:** snapshot the welcome screen, an active spinner frame, a tool
card, and the footer before/after; regenerate affected snapshots; manual visual
check in dark + light.

---

## Phase 4 — Accessibility theme variants

Port `blackbox/src`'s accessibility theme strategy (6 named themes) to
Pythinker.

### Theme set expansion

- `ui/theme.py`: expand `type ThemeName = Literal["dark","light"]` to
  `"dark" | "light" | "dark-ansi" | "light-ansi" | "dark-daltonized" | "light-daltonized"`.
- `config.py:294`: expand the `theme` Literal identically; keep `"dark"` default.
- Build four new `TuiTokens` instances (`_TUI_TOKENS_DARK_ANSI`, `_LIGHT_ANSI`,
  `_DARK_DALTONIZED`, `_LIGHT_DALTONIZED`) and a `resolve_palette(name)` mapping.
- `ui/shell/selectors/theme.py` + the `/theme` slash command: list all six
  variants with labels.
- **Replace every binary `name == "light" else <dark>` getter with the
  resolver.** Today `get_diff_colors`, `get_task_browser_style`,
  `get_prompt_style`, `get_toolbar_colors`, `get_mcp_prompt_colors`,
  `get_markdown_colors`, and `get_tui_tokens` all branch on a two-value
  light/dark test — under six themes those would **silently fall back** to
  dark/light. Each getter must key its palette by the full theme name (or by a
  decomposed `(base, mode)` family map), so `dark-ansi` / `*-daltonized` resolve
  to their own tables everywhere, not just for `TuiTokens`. This is a required
  part of P4, not optional.

### ANSI-16 variants — *explicitly chosen palette, not a fallback*

Rich already auto-downgrades hex to the nearest available color. The `*-ansi`
themes are **not** that mechanism; they are deliberately authored palettes using
the 16 standard ANSI color **names** (`red`, `cyan`, `bright_black`, …) for
terminals where auto-degrading `#EE9983` looks muddy. Map roles to ANSI names
(accent→`bright_red`/coral-ish, info→`cyan`, success→`green`, error→`red`,
warning→`yellow`, borders→`bright_black`, etc.).

> **Sub-decision (flag at review):** should Pythinker *auto-select* a `*-ansi`
> variant when `console.color_system not in ("truecolor", "256")`? This adds
> detection logic and test surface. Default proposal: **expose as explicit
> config choices only**; add auto-selection as a follow-up if wanted.

### Daltonized variants — same vetted strategy, equivalent contrast-tested values

Color-blind-safe palettes are vetted work, so we **apply the same accessibility
strategy** the reference uses and **author our own equivalent, contrast-tested
values** — we do **not** copy source from `blackbox/src` (it is Claude Code's
source; provenance/licensing is not cleared for verbatim reuse). The reference
is consulted only to confirm the strategy. Core principle: **blue/orange
replaces the green/red axis**; error stays pure red. All values below must be
contrast-checked against their background (≥4.5:1 for text) during
implementation.

Role mapping (Pythinker values, following the standard daltonization strategy):

| role | dark-daltonized | light-daltonized |
|---|---|---|
| success | `#3399FF` (blue, not green) | `#006699` (`rgb(0,102,153)`, blue) |
| error | `#FF6666` | `#CC0000` |
| warning | `#FFCC00` | `#FF9900` |
| info / accent-alt | `#99CCFF` (light blue) | `#3366FF` (bright blue) |
| diff added | `#004466` | `#99CCFF` |
| diff removed | `#660000` | `#FFCCCC` |
| structure (border/base) | navy `#213853` *(Pythinker-retained)* | slate `#495F7C` *(retained)* |
| accent | daltonized orange `#FF9933` *(coral substitute — coral reads as error red for deuteranopia)* | `#FF9933` |

> Navy structure is **retained** for brand continuity (it's hue-neutral and
> color-blind safe). Coral is the one brand color **replaced** in daltonized
> mode, because a reddish coral is indistinguishable from error red under
> red-green color blindness.

**Verification:** parametrize theme tests across all six variants (every
`TuiTokens` field non-empty where required, resolver returns the right set);
`/theme` selector test lists six options; config accepts/rejects the expanded
Literal (`tests/core/test_config.py`).

---

## Risks & mitigations

- **Snapshot churn:** color changes invalidate render snapshots. Mitigation:
  regenerate per phase; review the diffs visually, not just mechanically.
- **`_TONE_STYLES` import-time→call-time change** could shift behavior if any
  caller cached the dict. Mitigation: grep for direct `_TONE_STYLES` access;
  keep `shell_style()` the only public path.
- **Contrast regressions** in light mode (coral on cream, cyan on cream).
  Mitigation: use the deeper coral `#DD786D` and darker cyan `#2F8FA8` in light;
  spot-check WCAG-ish contrast on the key pairs.
- **256-color terminals:** truecolor hex auto-maps; verify the coral/cyan don't
  collapse to the same 256 index as error red on common terminals.

## Success criteria

1. Every colored shell element (welcome rows, tones, spinner, prompt, footer,
   markdown, diffs, tool cards, dialogs) reads as coral/cyan/navy/cream brand.
2. No hardcoded color literals remain in `ui/shell/**` outside `theme.py` /
   `design_system.py` resolvers, **with one explicit exception: the `_LOGO`
   glyph and its color constants (`_LOGO_NAVY/_FACE/_CORAL/_IRIS`) at
   `ui/shell/__init__.py:1746-1761` remain hardcoded and byte-for-byte
   unchanged** — they are the canonical brand source. Any other intentional
   exception must be documented inline.
3. Six themes selectable; daltonized variants match blackbox values; ANSI
   variants render cleanly on a 16-color terminal.
4. All theme/token/snapshot/design-system tests pass; snapshots regenerated and
   reviewed.
5. The robot logo is byte-for-byte unchanged.
