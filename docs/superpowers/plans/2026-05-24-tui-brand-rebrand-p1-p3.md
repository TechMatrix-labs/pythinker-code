# Pythinker TUI Brand Rebrand (P1–P3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every colored element of the Pythinker interactive shell read as the robot-mascot brand palette (coral / cyan / navy / cream) by rebranding the existing theme-token values, closing hardcoded-color bypass sites, and adding light structural polish — without touching the `_LOGO` banner or swapping the rendering engine.

**Architecture:** The semantic-token system already exists in `ui/theme.py` (`TuiTokens` dataclass + `tui_rich_style()`). P1 swaps token *values* (one file) and adds one `info` token. P2 routes the few remaining hardcoded literals through the token system, including converting `design_system._TONE_STYLES` from a static dict into a theme-aware resolver. P3 adds rounded panel borders, a brand-coral spinner color (with a minimal reduced-motion-respecting shimmer), and keeps the already-token-driven footer aligned.

**Tech Stack:** Python 3.12, Rich (`rich.style.Style`, `rich.box`), prompt_toolkit, pytest. Run tests with the project venv: `/home/ai/Projects/pythinker-code-main/.venv/bin/python -m pytest` (or `uv run pytest`).

**Scope:** This plan is the **first PR** (P1+P2+P3, dark + light themes only). The accessibility variants (ANSI-16 + daltonized, theme-set expansion, getter-resolver refactor) are **P4** and ship in a separate follow-up plan.

**Spec:** `docs/superpowers/specs/2026-05-24-tui-brand-rebrand-design.md`

---

## Brand value reference (used throughout)

**Dark theme** (terminal-default background; foreground-driven):

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
| text | `""` | tool_diff_removed | `#EF5E62` |
| thinking_text | `#7FB4C4` | tool_diff_context | `#8B93A3` |
| activity_label | `#F2EBEC` | bash_mode | `#7BC97F` |

**Light theme** (cream background; navy text; foreground tokens are AA-safe):

| token | value | token | value |
|---|---|---|---|
| accent | `#AE5430` | selected_bg | `#F3D9D2` |
| border | `#495F7C` | user_message_bg | `#F0E4E4` |
| border_accent | `#DD786D` | custom_message_bg | `#E6F2F6` |
| border_muted | `#C8BEC0` | custom_message_label | `#176B7E` |
| info *(new)* | `#176B7E` | tool_pending_bg | `#EFE7E8` |
| success | `#2C7A39` | tool_success_bg | `#E4F0E6` |
| warning | `#9A6B18` | tool_error_bg | `#F6E3E3` |
| error | `#C0392B` | tool_title | `""` |
| muted | `#5D6B80` | tool_output | `#5D6B80` |
| dim | `#8A93A0` | tool_diff_added | `#2C7A39` |
| text | `#213853` | tool_diff_removed | `#C0392B` |
| thinking_text | `#5D6B80` | tool_diff_context | `#5D6B80` |
| activity_label | `#213853` | bash_mode | `#2C7A39` |

---

## File Structure

| File | Responsibility | Phase |
|---|---|---|
| `src/pythinker_code/ui/theme.py` | All token/palette values + the new `info` field | P1 |
| `tests/ui_and_conv/test_tui_theme_tokens.py` | Assert new brand token + markdown values, `info` token | P1 |
| `tests/ui_and_conv/test_tui_render_snapshots.py` | Update hardcoded bg RGB to new values | P1 |
| `src/pythinker_code/ui/shell/__init__.py` | `_value_style_for_label` → tokens (NOT `_LOGO`) | P2 |
| `src/pythinker_code/ui/shell/design_system.py` | `_TONE_STYLES` dict → theme-aware resolver | P2 |
| `src/pythinker_code/ui/shell/startup.py` | startup spinner → accent token | P2 |
| `src/pythinker_code/ui/shell/motion.py` | `_VERB_SPINNER_STYLE` → accent token + shimmer | P2/P3 |
| `tests/ui_and_conv/test_shell_design_system.py` | Tones resolve to brand tokens, switch w/ theme | P2 |
| `tests/ui_and_conv/test_shell_welcome_info.py` | Rebranded welcome rows | P2 |
| `src/pythinker_code/ui/shell/components/*` (panels) | Rounded borders via shared helper | P3 |

---

# PHASE 1 — Rebrand token values

### Task 1: Add the `info` token to `TuiTokens`

**Files:**
- Modify: `src/pythinker_code/ui/theme.py` (dataclass `TuiTokens` ~L367-407; `_TUI_TOKENS_DARK` ~L412; `_TUI_TOKENS_LIGHT` ~L445)
- Test: `tests/ui_and_conv/test_tui_theme_tokens.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ui_and_conv/test_tui_theme_tokens.py`:

```python
def test_info_token_exists_and_is_cyan():
    assert get_tui_tokens("dark").info == "#AFE3F1"
    assert get_tui_tokens("light").info == "#176B7E"
    # resolver works for the new token
    set_active_theme("dark")
    assert tui_rich_style("info").color is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_tui_theme_tokens.py::test_info_token_exists_and_is_cyan -v`
Expected: FAIL — `AttributeError: 'TuiTokens' object has no attribute 'info'`

- [ ] **Step 3: Add the field to the dataclass**

In `TuiTokens` (the `# Core` block), add after `border_muted: str`:

```python
    info: str
```

- [ ] **Step 4: Add the value to both constructors**

In `_TUI_TOKENS_DARK`, add after `border_muted="#2B3A52",` (see Task 2 for the full block) — for now add `info="#AFE3F1",`. In `_TUI_TOKENS_LIGHT`, add `info="#176B7E",`. (Both full blocks are rewritten in Task 2; this step just makes the field present.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_tui_theme_tokens.py::test_info_token_exists_and_is_cyan -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/ui/theme.py tests/ui_and_conv/test_tui_theme_tokens.py
git commit -m "feat(tui): add cyan info token to TuiTokens"
```

---

### Task 2: Rebrand `_TUI_TOKENS_DARK` and `_TUI_TOKENS_LIGHT`

**Files:**
- Modify: `src/pythinker_code/ui/theme.py` (`_TUI_TOKENS_DARK` ~L412-442, `_TUI_TOKENS_LIGHT` ~L445-473)
- Test: `tests/ui_and_conv/test_tui_theme_tokens.py`

- [ ] **Step 1: Update the failing tests to the new brand values**

Replace `test_dark_tokens_have_pi_reference_values` and `test_light_tokens_have_pi_reference_values`:

```python
def test_dark_tokens_have_brand_values():
    set_active_theme("dark")
    t = get_tui_tokens()
    assert t.accent == "#EE9983"          # coral
    assert t.border == "#3A506D"          # slate
    assert t.info == "#AFE3F1"            # cyan
    assert t.success == "#7BC97F"
    assert t.error == "#EF5E62"
    assert t.tool_pending_bg == "#1B2230"
    assert t.tool_error_bg == "#2E1D24"


def test_light_tokens_have_brand_values():
    set_active_theme("light")
    t = get_tui_tokens()
    assert t.accent == "#AE5430"          # text-safe coral
    assert t.info == "#176B7E"            # text-safe cyan
    assert t.text == "#213853"            # navy text
    assert t.error == "#C0392B"
    assert t.tool_pending_bg == "#EFE7E8"
```

Also update `test_get_tui_tokens_with_explicit_theme_arg` (the `#e8` prefix assertion still holds for light `tool_pending_bg = #EFE7E8` → change to `.startswith("#EF")`).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_tui_theme_tokens.py -v`
Expected: FAIL on the new assertions (old values still in place).

- [ ] **Step 3: Rewrite `_TUI_TOKENS_DARK`**

```python
_TUI_TOKENS_DARK = TuiTokens(
    accent="#EE9983",
    border="#3A506D",
    border_accent="#EE9983",
    border_muted="#2B3A52",
    info="#AFE3F1",
    success="#7BC97F",
    error="#EF5E62",
    warning="#E6B450",
    muted="#8B93A3",
    dim="#5F6B7E",
    text="",
    thinking_text="#7FB4C4",
    activity_label="#F2EBEC",
    selected_bg="#243C54",
    user_message_bg="#1B2738",
    user_message_text="",
    custom_message_bg="#16242E",
    custom_message_text="",
    custom_message_label="#AFE3F1",
    tool_pending_bg="#1B2230",
    tool_success_bg="#16271C",
    tool_error_bg="#2E1D24",
    tool_title="#8B93A3",
    tool_output="#8B93A3",
    tool_diff_added="#7BC97F",
    tool_diff_removed="#EF5E62",
    tool_diff_context="#8B93A3",
    bash_mode="#7BC97F",
)
```

- [ ] **Step 4: Rewrite `_TUI_TOKENS_LIGHT`**

```python
_TUI_TOKENS_LIGHT = TuiTokens(
    accent="#AE5430",
    border="#495F7C",
    border_accent="#DD786D",
    border_muted="#C8BEC0",
    info="#176B7E",
    success="#2C7A39",
    error="#C0392B",
    warning="#9A6B18",
    muted="#5D6B80",
    dim="#8A93A0",
    text="#213853",
    thinking_text="#5D6B80",
    activity_label="#213853",
    selected_bg="#F3D9D2",
    user_message_bg="#F0E4E4",
    user_message_text="",
    custom_message_bg="#E6F2F6",
    custom_message_text="",
    custom_message_label="#176B7E",
    tool_pending_bg="#EFE7E8",
    tool_success_bg="#E4F0E6",
    tool_error_bg="#F6E3E3",
    tool_title="",
    tool_output="#5D6B80",
    tool_diff_added="#2C7A39",
    tool_diff_removed="#C0392B",
    tool_diff_context="#5D6B80",
    bash_mode="#2C7A39",
)
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_tui_theme_tokens.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/ui/theme.py tests/ui_and_conv/test_tui_theme_tokens.py
git commit -m "feat(tui): rebrand TuiTokens dark+light to robot palette"
```

---

### Task 3: Rebrand `_MARKDOWN_DARK` / `_MARKDOWN_LIGHT`

**Files:**
- Modify: `src/pythinker_code/ui/theme.py` (`_MARKDOWN_DARK` ~L236, `_MARKDOWN_LIGHT` ~L251)
- Test: `tests/ui_and_conv/test_tui_theme_tokens.py`

Role mapping (from spec): heading/strong → coral; emphasis/quote → muted; inline_code/link → cyan; table_border/code_block_border → border_muted; code_block_bg unchanged; spinner_active → coral; spinner_done → success; spinner_failed → error.

- [ ] **Step 1: Update the failing markdown test**

Replace `test_dark_markdown_is_minimal_two_colour` with:

```python
def test_dark_markdown_uses_brand_roles():
    colors = get_markdown_colors("dark")
    assert colors.heading == "#EE9983"      # coral
    assert colors.strong == "#EE9983"
    assert colors.emphasis == "#8B93A3"     # muted
    assert colors.inline_code == "#AFE3F1"  # cyan
    assert colors.link == "#AFE3F1"
    assert colors.spinner_active == "#EE9983"
    assert markdown_rich_style("link", theme="dark").color is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_tui_theme_tokens.py::test_dark_markdown_uses_brand_roles -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `_MARKDOWN_DARK`**

```python
_MARKDOWN_DARK = MarkdownColors(
    heading="#EE9983",
    emphasis="#8B93A3",
    strong="#EE9983",
    inline_code="#AFE3F1",
    link="#AFE3F1",
    quote="#8B93A3",
    table_border="#2B3A52",
    code_block_border="#2B3A52",
    code_block_bg="#1f2030",
    spinner_active="#EE9983",
    spinner_done="#7BC97F",
    spinner_failed="#EF5E62",
)
```

- [ ] **Step 4: Rewrite `_MARKDOWN_LIGHT`**

```python
_MARKDOWN_LIGHT = MarkdownColors(
    heading="#AE5430",
    emphasis="#5D6B80",
    strong="#AE5430",
    inline_code="#176B7E",
    link="#176B7E",
    quote="#5D6B80",
    table_border="#C8BEC0",
    code_block_border="#C8BEC0",
    code_block_bg="#f1f5f9",
    spinner_active="#AE5430",
    spinner_done="#2C7A39",
    spinner_failed="#C0392B",
)
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_tui_theme_tokens.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/ui/theme.py tests/ui_and_conv/test_tui_theme_tokens.py
git commit -m "feat(tui): rebrand markdown palette to brand roles"
```

---

### Task 4: Rebrand prompt / toolbar / mcp / task-browser / diff palettes

**Files:**
- Modify: `src/pythinker_code/ui/theme.py` (`_PROMPT_STYLE_DARK` ~L104, `_PROMPT_STYLE_LIGHT` ~L137, `_TOOLBAR_DARK` ~L185, `_TOOLBAR_LIGHT` ~L197, `_MCP_PROMPT_DARK` ~L302, `_MCP_PROMPT_LIGHT` ~L311, `_task_browser_style_dark` ~L51, `_task_browser_style_light` ~L75, `_DIFF_DARK`/`_DIFF_LIGHT` ~L31-43)
- Test: `tests/ui_and_conv/test_theme.py`

Apply the spec's strict role mapping (§"Secondary palette role mapping"). coral = dark `#EE9983` / light `#AE5430`; cyan = dark `#AFE3F1` / light `#176B7E`; slate/navy borders = dark `#3A506D`/`#2B3A52` / light `#495F7C`/`#C8BEC0`; success/warning/error per the brand tables.

- [ ] **Step 1: Keep the existing diff-color test honest**

`tests/ui_and_conv/test_theme.py::test_diff_colors_by_theme` asserts `#12261e` (dark add_bg) and `#dafbe1` (light add_bg). The spec keeps the current diff bg *tints* (re-keyed semantically), so **leave `_DIFF_DARK`/`_DIFF_LIGHT` values unchanged** and this test stays green. No edit to diff colors in this task.

- [ ] **Step 2: Add an assertion that prompt caret uses coral (dark)**

Add to `tests/ui_and_conv/test_theme.py`:

```python
def test_prompt_caret_is_coral_dark():
    set_active_theme("dark")
    style = get_prompt_style()
    # PTKStyle stores rules as (class, definition) pairs.
    rules = dict(style.class_names_and_attrs) if hasattr(style, "class_names_and_attrs") else {}
    # Fallback: render the style dict via the module constant.
    from pythinker_code.ui.theme import _PROMPT_STYLE_DARK
    assert "#EE9983" in _PROMPT_STYLE_DARK["compact-input.prompt"]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_theme.py::test_prompt_caret_is_coral_dark -v`
Expected: FAIL (current value is `#9CA3AF`).

- [ ] **Step 4: Rewrite `_PROMPT_STYLE_DARK`** (coral caret/accents, slate frames, selected_bg rows)

```python
_PROMPT_STYLE_DARK = {
    "bottom-toolbar": "noreverse",
    "compact-input": "",
    "compact-input.prompt": "fg:#EE9983 bold",
    "compact-input.frame": "fg:#3A506D",
    "running-prompt-placeholder": "fg:#8B93A3 italic",
    "running-prompt-separator": "fg:#2B3A52",
    "slash-completion-menu": "",
    "slash-completion-menu.separator": "fg:#2B3A52",
    "slash-completion-menu.marker": "fg:#2B3A52",
    "slash-completion-menu.marker.current": "fg:#EE9983 bold",
    "slash-completion-menu.command": "fg:#c4c9e8",
    "slash-completion-menu.command.match": "fg:#EE9983 bold",
    "slash-completion-menu.meta": "fg:#8B93A3",
    "slash-completion-menu.command.current": "bg:#243C54 fg:#EE9983 bold",
    "slash-completion-menu.command.match.current": "bg:#243C54 fg:#EE9983 bold",
    "slash-completion-menu.meta.current": "bg:#243C54 fg:#c4c9e8",
    "slash-completion-menu.row.current": "bg:#243C54",
    "shell-dialog": "fg:#d7dcff",
    "shell-dialog.title": "fg:#f4f6ff bold",
    "shell-dialog.border": "fg:#2B3A52",
    "shell-dialog.option": "fg:#aeb6df",
    "shell-dialog.option.current": "bg:#243C54 fg:#EE9983 bold",
    "shell-footer.key": "fg:#EE9983 bold",
    "shell-footer.meta": "fg:#aeb6df",
    "shell-footer.warning": "fg:#E6B450",
    "shell-footer.error": "fg:#EF5E62",
}
```

- [ ] **Step 5: Rewrite `_PROMPT_STYLE_LIGHT`** (text-safe coral caret/accents)

```python
_PROMPT_STYLE_LIGHT = {
    "bottom-toolbar": "noreverse",
    "compact-input": "",
    "compact-input.prompt": "fg:#AE5430 bold",
    "compact-input.frame": "fg:#495F7C",
    "running-prompt-placeholder": "fg:#5D6B80 italic",
    "running-prompt-separator": "fg:#C8BEC0",
    "slash-completion-menu": "",
    "slash-completion-menu.separator": "fg:#C8BEC0",
    "slash-completion-menu.marker": "fg:#8A93A0",
    "slash-completion-menu.marker.current": "fg:#AE5430 bold",
    "slash-completion-menu.command": "fg:#4b5563",
    "slash-completion-menu.command.match": "fg:#AE5430 bold",
    "slash-completion-menu.meta": "fg:#5D6B80",
    "slash-completion-menu.command.current": "bg:#F3D9D2 fg:#AE5430 bold",
    "slash-completion-menu.command.match.current": "bg:#F3D9D2 fg:#AE5430 bold",
    "slash-completion-menu.meta.current": "bg:#F3D9D2 fg:#4b5563",
    "slash-completion-menu.row.current": "bg:#F3D9D2",
    "shell-dialog": "fg:#374151",
    "shell-dialog.title": "fg:#213853 bold",
    "shell-dialog.border": "fg:#C8BEC0",
    "shell-dialog.option": "fg:#5D6B80",
    "shell-dialog.option.current": "bg:#F3D9D2 fg:#AE5430 bold",
    "shell-footer.key": "fg:#AE5430 bold",
    "shell-footer.meta": "fg:#5D6B80",
    "shell-footer.warning": "fg:#9A6B18",
    "shell-footer.error": "fg:#C0392B",
}
```

- [ ] **Step 6: Rewrite `_TOOLBAR_DARK` / `_TOOLBAR_LIGHT`**

```python
_TOOLBAR_DARK = ToolbarColors(
    separator="fg:#2B3A52",
    yolo_label="bold fg:#E6B450",
    auto_label="bold fg:#EE9983",
    plan_label="bold fg:#AFE3F1",
    plan_prompt="fg:#AFE3F1",
    cwd="fg:#5F6B7E",
    bg_tasks="fg:#8B93A3",
    tip="fg:#5F6B7E",
    tip_key="fg:#8B93A3 bold",
)

_TOOLBAR_LIGHT = ToolbarColors(
    separator="fg:#C8BEC0",
    yolo_label="bold fg:#9A6B18",
    auto_label="bold fg:#AE5430",
    plan_label="bold fg:#176B7E",
    plan_prompt="fg:#176B7E",
    cwd="fg:#8A93A0",
    bg_tasks="fg:#5D6B80",
    tip="fg:#8A93A0",
    tip_key="fg:#5D6B80 bold",
)
```

- [ ] **Step 7: Rewrite `_MCP_PROMPT_DARK` / `_MCP_PROMPT_LIGHT`**

```python
_MCP_PROMPT_DARK = MCPPromptColors(
    text="fg:#d4d4d4",
    detail="fg:#8B93A3",
    connected="fg:#7BC97F",
    connecting="fg:#AFE3F1",
    pending="fg:#E6B450",
    failed="fg:#EF5E62",
)

_MCP_PROMPT_LIGHT = MCPPromptColors(
    text="fg:#213853",
    detail="fg:#5D6B80",
    connected="fg:#2C7A39",
    connecting="fg:#176B7E",
    pending="fg:#9A6B18",
    failed="fg:#C0392B",
)
```

- [ ] **Step 8: Rewrite the task-browser styles** — apply coral to `header.title`/`frame.label`/`footer.key`, success/warning/error/info per brand, `task-list.checked` → cyan-tinted. Edit `_task_browser_style_dark()` and `_task_browser_style_light()`:

`_task_browser_style_dark()` dict values:
```python
{
    "header": "bg:#1f2937 #e5e7eb",
    "header.title": "bg:#1f2937 #EE9983 bold",
    "header.meta": "bg:#1f2937 #8B93A3",
    "status.running": "bg:#1f2937 #7BC97F bold",
    "status.success": "bg:#1f2937 #7BC97F",
    "status.warning": "bg:#1f2937 #E6B450",
    "status.error": "bg:#1f2937 #EF5E62",
    "status.info": "bg:#1f2937 #AFE3F1",
    "task-list": "bg:#111827 #d1d5db",
    "task-list.checked": "bg:#164e63 #ecfeff bold",
    "frame.border": "#3A506D",
    "frame.label": "bg:#17182a #EE9983 bold",
    "footer": "bg:#17182a #d7dcff",
    "footer.key": "bg:#17182a #EE9983 bold",
    "footer.text": "bg:#17182a #d7dcff",
    "footer.warning": "bg:#4a3315 #E6B450 bold",
    "footer.meta": "bg:#17182a #9aa4d6",
}
```

`_task_browser_style_light()` dict values:
```python
{
    "header": "bg:#e5e7eb #1f2937",
    "header.title": "bg:#e5e7eb #AE5430 bold",
    "header.meta": "bg:#e5e7eb #5D6B80",
    "status.running": "bg:#e5e7eb #2C7A39 bold",
    "status.success": "bg:#e5e7eb #2C7A39",
    "status.warning": "bg:#e5e7eb #9A6B18",
    "status.error": "bg:#e5e7eb #C0392B",
    "status.info": "bg:#e5e7eb #176B7E",
    "task-list": "bg:#f9fafb #374151",
    "task-list.checked": "bg:#cffafe #164e63 bold",
    "frame.border": "#495F7C",
    "frame.label": "bg:#f1f5f9 #AE5430 bold",
    "footer": "bg:#f1f5f9 #475569",
    "footer.key": "bg:#f1f5f9 #AE5430 bold",
    "footer.text": "bg:#f1f5f9 #475569",
    "footer.warning": "bg:#fee2e2 #C0392B bold",
    "footer.meta": "bg:#f1f5f9 #64748b",
}
```

- [ ] **Step 9: Run the full theme test file**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_theme.py -v`
Expected: PASS (including `test_all_getters_respond_to_theme_switch`, `test_ptk_styles_valid_for_both_themes`, `test_prompt_caret_is_coral_dark`).

- [ ] **Step 10: Commit**

```bash
git add src/pythinker_code/ui/theme.py tests/ui_and_conv/test_theme.py
git commit -m "feat(tui): rebrand prompt/toolbar/mcp/task-browser palettes"
```

---

### Task 5: Regenerate / update render snapshots for new bg values

**Files:**
- Modify: `tests/ui_and_conv/test_tui_render_snapshots.py`

The snapshot tests hardcode old token RGB. New dark bg RGB: `tool_pending_bg #1B2230` → `48;2;27;34;48`; `tool_success_bg #16271C` → `48;2;22;39;28`; `tool_error_bg #2E1D24` → `48;2;46;29;36`.

- [ ] **Step 1: Run the snapshot tests to see them fail**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_tui_render_snapshots.py -v`
Expected: FAIL on `test_pending_card_uses_tool_pending_bg` and `test_error_card_uses_tool_error_bg` (old RGB no longer present).

- [ ] **Step 2: Update the asserted RGB triples**

In `test_pending_card_uses_tool_pending_bg`:
```python
    # Default dark theme tool_pending_bg = #1B2230 -> rgb(27,34,48).
    assert "48;2;27;34;48" in coloured
```
In `test_error_card_uses_tool_error_bg` and `test_denied_card_uses_error_bg`:
```python
    # Default dark theme tool_error_bg = #2E1D24 -> rgb(46,29,36).
    assert "48;2;46;29;36" in coloured
```
In `test_success_card_renders_compact_without_success_bg`:
```python
    # Compact cards no longer paint a full success background.
    assert "48;2;22;39;28" not in coloured
```
In `test_self_shell_skips_padding`:
```python
    # No tool_pending_bg fill should be applied when render_shell == "self".
    assert "48;2;27;34;48" not in coloured
```

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_tui_render_snapshots.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/ui_and_conv/test_tui_render_snapshots.py
git commit -m "test(tui): update render snapshots to brand bg values"
```

---

# PHASE 2 — Close hardcoded-color bypass gaps

### Task 6: Route `_value_style_for_label` (welcome rows) through tokens

**Files:**
- Modify: `src/pythinker_code/ui/shell/__init__.py` (`_value_style_for_label` ~L1776-1791) — **do NOT touch `_LOGO`/`_LOGO_*` at L1746-1761**
- Test: `tests/ui_and_conv/test_shell_welcome_info.py`

Current code maps labels to Rich names: Directory→`cyan`, Session→`grey39`, Model→`bold bright_white`, Branch→`magenta`, Auto-save→`grey50`.

- [ ] **Step 1: Read the existing welcome test for shape**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_welcome_info.py -v` (note what it asserts; keep those behaviors).

- [ ] **Step 2: Write a failing test that Directory uses the cyan brand token**

Add to `tests/ui_and_conv/test_shell_welcome_info.py`:

```python
def test_directory_label_uses_brand_info_token():
    from pythinker_code.ui.shell import _value_style_for_label
    from pythinker_code.ui.shell.__init__ import WelcomeInfoItem
    from pythinker_code.ui.theme import get_tui_tokens, set_active_theme
    set_active_theme("dark")
    style = _value_style_for_label("Directory", WelcomeInfoItem.Level.INFO)
    assert get_tui_tokens("dark").info in style  # "#AFE3F1"
```

(If `WelcomeInfoItem` import path differs, import it from `pythinker_code.ui.shell`.)

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_welcome_info.py::test_directory_label_uses_brand_info_token -v`
Expected: FAIL (returns `"cyan"`).

- [ ] **Step 4: Rewrite `_value_style_for_label` to use tokens**

```python
def _value_style_for_label(label: str, level: WelcomeInfoItem.Level) -> str:
    """INFO-level styling per label; WARN/ERROR colors always win."""
    if level is not WelcomeInfoItem.Level.INFO:
        return level.value
    from pythinker_code.ui.theme import get_tui_tokens

    tokens = get_tui_tokens()
    label = label.strip()
    if label == "Directory":
        return tokens.info or "cyan"
    if label == "Session":
        return tokens.dim or "grey39"
    if label == "Model":
        return f"bold {tokens.text}" if tokens.text else "bold bright_white"
    if label == "Branch":
        return tokens.accent or "magenta"
    if label == "Auto-save":
        return tokens.muted or "grey50"
    return level.value
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_welcome_info.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/ui/shell/__init__.py tests/ui_and_conv/test_shell_welcome_info.py
git commit -m "feat(tui): route welcome info rows through brand tokens"
```

---

### Task 7: Convert `design_system._TONE_STYLES` to a theme-aware resolver

**Files:**
- Modify: `src/pythinker_code/ui/shell/design_system.py` (L37-60)
- Test: `tests/ui_and_conv/test_shell_design_system.py`

**Mapping** `ShellTone` → token name: NORMAL→`text`, MUTED→`muted`, ACCENT→`accent`, SUCCESS→`success`, WARNING→`warning`, ERROR→`error`, INFO→`info`.

- [ ] **Step 1: Write the failing test (tones resolve to brand tokens + switch with theme)**

Add to `tests/ui_and_conv/test_shell_design_system.py`:

```python
def test_shell_style_resolves_brand_tokens_and_switches_theme():
    from pythinker_code.ui.theme import set_active_theme
    set_active_theme("dark")
    assert shell_style(ShellTone.ACCENT).color.triplet.hex.lower() == "#ee9983"
    assert shell_style(ShellTone.SUCCESS).color.triplet.hex.lower() == "#7bc97f"
    set_active_theme("light")
    assert shell_style(ShellTone.ACCENT).color.triplet.hex.lower() == "#ae5430"
    set_active_theme("dark")
```

(Add `from pythinker_code.ui.shell.design_system import shell_style` to imports.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_design_system.py::test_shell_style_resolves_brand_tokens_and_switches_theme -v`
Expected: FAIL (`#9ca3af`, no theme switch).

- [ ] **Step 3: Replace the static dict with a resolver**

Replace the `_TONE_STYLES` dict (L37-45) and `shell_style` (L59-60) with:

```python
from pythinker_code.ui.theme import tui_rich_style

_TONE_TOKEN: dict[ShellTone, str] = {
    ShellTone.NORMAL: "text",
    ShellTone.MUTED: "muted",
    ShellTone.ACCENT: "accent",
    ShellTone.SUCCESS: "success",
    ShellTone.WARNING: "warning",
    ShellTone.ERROR: "error",
    ShellTone.INFO: "info",
}


def shell_style(tone: ShellTone) -> Style:
    """Resolve a ShellTone to a Rich Style via the active theme tokens.

    NORMAL maps to the ``text`` token, which is empty (terminal default) and
    yields ``Style(color="default")`` so existing behavior is preserved.
    """
    style = tui_rich_style(_TONE_TOKEN[tone])
    return style if style.color is not None else Style(color="default")
```

Keep `_STATUS`, `status_icon`, `keyboard_hint`, `dialog_title`, `render_segment_line`, `render_row` unchanged (they call `shell_style`).

- [ ] **Step 4: Confirm no other module imports `_TONE_STYLES` directly**

Run: `grep -rn "_TONE_STYLES" src tests`
Expected: no matches outside the (now-removed) definition. If any exist, repoint them to `shell_style`.

- [ ] **Step 5: Run the design-system tests**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_design_system.py -v`
Expected: PASS (icon names + new resolver test).

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/ui/shell/design_system.py tests/ui_and_conv/test_shell_design_system.py
git commit -m "feat(tui): make ShellTone resolve brand tokens per active theme"
```

---

### Task 8: Route startup spinner and verb-spinner color through the accent token

**Files:**
- Modify: `src/pythinker_code/ui/shell/startup.py` (L19), `src/pythinker_code/ui/shell/motion.py` (L26, L92-93)
- Test: `tests/ui_and_conv/test_shell_design_system.py` (new small test)

- [ ] **Step 1: Write a failing test that the verb-spinner style is the accent token**

Add to `tests/ui_and_conv/test_shell_design_system.py`:

```python
def test_verb_spinner_uses_accent_token():
    from pythinker_code.ui.shell.motion import verb_spinner_style
    from pythinker_code.ui.theme import set_active_theme
    set_active_theme("dark")
    assert verb_spinner_style().color.triplet.hex.lower() == "#ee9983"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_design_system.py::test_verb_spinner_uses_accent_token -v`
Expected: FAIL (`verb_spinner_style` undefined).

- [ ] **Step 3: Replace the hardcoded `_VERB_SPINNER_STYLE` in `motion.py`**

Remove `_VERB_SPINNER_STYLE = Style(color="#F5A97F")` (L26). `motion.py:14` already imports `ShellTone, shell_style` from `design_system`, so do **not** re-import them — just add the helper below the imports:

```python
def verb_spinner_style() -> Style:
    """Brand-coral style for the active verb spinner (resolves per theme)."""
    return shell_style(ShellTone.ACCENT)
```

In `activity_status_line`, replace the two `_VERB_SPINNER_STYLE` references (L92, L93) with `verb_spinner_style()`:
```python
    else:
        glyph_style = verb_spinner_style()
    label_style = snapshot.label_style if snapshot.label_style is not None else verb_spinner_style()
```

- [ ] **Step 4: Replace startup spinner literal cyan**

In `startup.py`, change `update`:
```python
    def update(self, message: str) -> None:
        if not self._enabled:
            return
        from pythinker_code.ui.theme import get_tui_tokens

        accent = get_tui_tokens().accent or "cyan"
        status_message = f"[{accent}]{message}[/{accent}]"
        if self._status is None:
            self._status = console.status(status_message, spinner="dots")
            self._status.start()
            return
        self._status.update(status_message)
```

- [ ] **Step 5: Run to verify pass + motion still imports cleanly**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_design_system.py -v`
Then: `.venv/bin/python -c "import pythinker_code.ui.shell.motion, pythinker_code.ui.shell.startup"`
Expected: PASS, no import error/cycle.

> Note: `motion.py` imports from `design_system`, which now imports from `theme`. Verify no circular import (`theme` imports neither). If a cycle appears, keep the `get_tui_tokens` import inside `verb_spinner_style` local.

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/ui/shell/motion.py src/pythinker_code/ui/shell/startup.py tests/ui_and_conv/test_shell_design_system.py
git commit -m "feat(tui): brand-color the startup and verb spinners"
```

---

### Task 9: Sweep `ui/shell/**` for remaining hardcoded colors

**Files:**
- Audit: `src/pythinker_code/ui/shell/**`

- [ ] **Step 1: Grep for hex literals and Rich color names outside theme/design_system**

Run:
```bash
grep -rn "#[0-9A-Fa-f]\{6\}\|color=\"\(cyan\|magenta\|yellow\|green\|red\|grey[0-9]*\|bright_[a-z]*\)\"" \
  src/pythinker_code/ui/shell --include="*.py" \
  | grep -v "theme.py\|design_system.py\|_LOGO\|test"
```

- [ ] **Step 2: For each genuine UI-color hit, repoint to `tui_rich_style(...)` / `shell_style(...)`**

For each match that is a semantic UI color (not a diff/syntax library color, not the `_LOGO` constants), replace with the matching token. Leave anything ambiguous and add an inline comment `# brand-exception: <reason>`.

- [ ] **Step 3: Re-run the grep to confirm only documented exceptions remain**

Run the Step-1 grep again; every remaining line must be the `_LOGO` block or carry a `# brand-exception` comment.

- [ ] **Step 4: Run the shell UI test suite**

Run: `.venv/bin/python -m pytest tests/ui_and_conv tests/ui -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A src/pythinker_code/ui/shell
git commit -m "refactor(tui): route stray shell colors through brand tokens"
```

---

# PHASE 3 — Structural polish

### Task 10: Shared rounded-border helper + sweep panel call sites

**Files:**
- Create: `src/pythinker_code/ui/shell/components/panel.py`
- Modify: shell panel call sites (discovered via grep)
- Test: `tests/ui_and_conv/test_shell_panel.py` (new)

- [ ] **Step 1: Write a failing test for the helper**

Create `tests/ui_and_conv/test_shell_panel.py`:

```python
from rich import box
from pythinker_code.ui.shell.components.panel import brand_panel
from pythinker_code.ui.theme import set_active_theme


def test_brand_panel_is_rounded_and_uses_border_token():
    set_active_theme("dark")
    p = brand_panel("hello", title="Demo")
    assert p.box is box.ROUNDED
    # border style resolves to the slate border token
    assert "#3a506d" in str(p.border_style).lower()


def test_brand_panel_active_uses_accent_border():
    set_active_theme("dark")
    p = brand_panel("hi", active=True)
    assert "#ee9983" in str(p.border_style).lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_panel.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the helper**

Create `src/pythinker_code/ui/shell/components/panel.py`:

```python
"""Brand-styled Rich Panel factory: rounded borders + theme tokens."""

from __future__ import annotations

from rich import box
from rich.panel import Panel
from rich.console import RenderableType

from pythinker_code.ui.theme import tui_rich_style


def brand_panel(
    renderable: RenderableType,
    *,
    title: str | None = None,
    active: bool = False,
    padding: tuple[int, int] = (0, 1),
) -> Panel:
    """A Panel with rounded corners and brand border colors.

    ``active=True`` uses the coral accent border; otherwise the slate border.
    """
    border = tui_rich_style("border_accent" if active else "border")
    return Panel(
        renderable,
        title=title,
        box=box.ROUNDED,
        border_style=border,
        padding=padding,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_panel.py -v`
Expected: PASS

- [ ] **Step 5: Find existing Panel call sites and adopt rounded borders**

Run:
```bash
grep -rn "Panel(\|box=box\.\|box\.SQUARE\|box\.HEAVY" src/pythinker_code/ui/shell --include="*.py" | grep -v test
```
For each user-facing shell Panel that builds its own box/border, either switch to `brand_panel(...)` or set `box=box.ROUNDED` + `border_style=tui_rich_style("border")`. Skip panels that intentionally use a different box (document with `# brand-exception`).

- [ ] **Step 6: Run the UI suite**

Run: `.venv/bin/python -m pytest tests/ui_and_conv tests/ui -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/pythinker_code/ui/shell/components/panel.py tests/ui_and_conv/test_shell_panel.py
git add -A src/pythinker_code/ui/shell
git commit -m "feat(tui): rounded brand panels across the shell"
```

---

### Task 11: Minimal coral shimmer on the active spinner (reduced-motion safe)

**Files:**
- Modify: `src/pythinker_code/ui/shell/motion.py`
- Test: `tests/ui_and_conv/test_shell_motion_shimmer.py` (new)

A *minimal* shimmer: ramp the coral glyph between the base accent and a lighter coral over a few frames, keyed off `elapsed_s`. Reduced motion → static base accent.

- [ ] **Step 1: Write the failing test**

Create `tests/ui_and_conv/test_shell_motion_shimmer.py`:

```python
from pythinker_code.ui.shell.motion import shimmer_spinner_style
from pythinker_code.ui.theme import set_active_theme


def test_shimmer_returns_base_accent_when_reduced_motion():
    set_active_theme("dark")
    s = shimmer_spinner_style(0.0, reduced_motion=True)
    assert s.color.triplet.hex.lower() == "#ee9983"


def test_shimmer_varies_over_time_when_motion_enabled():
    set_active_theme("dark")
    first = shimmer_spinner_style(0.0, reduced_motion=False).color.triplet.hex
    later = shimmer_spinner_style(0.4, reduced_motion=False).color.triplet.hex
    # At least one sampled frame differs from the base when animating.
    assert first != later or first.lower() != "#ee9983"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_motion_shimmer.py -v`
Expected: FAIL (`shimmer_spinner_style` undefined).

- [ ] **Step 3: Implement the shimmer helper**

Add to `motion.py`:

```python
from rich.color import Color

# Coral shimmer ramp: base accent -> lighter coral and back.
_SHIMMER_CORALS: tuple[str, ...] = ("#EE9983", "#F2A892", "#F6B7A2", "#F2A892")
_SHIMMER_INTERVAL_S = 0.12


def shimmer_spinner_style(elapsed_s: float, *, reduced_motion: bool = False) -> Style:
    """Coral spinner color that gently shimmers over time.

    Reduced motion (or the env var) pins to the base accent.
    """
    if reduced_motion or reduced_motion_enabled():
        return verb_spinner_style()
    idx = int(max(0.0, elapsed_s) / _SHIMMER_INTERVAL_S) % len(_SHIMMER_CORALS)
    return Style(color=Color.parse(_SHIMMER_CORALS[idx]))
```

- [ ] **Step 4: Use the shimmer for the braille verb spinner glyph**

In `activity_status_line`, where `glyph_style` is set for the non-stalled, non-shape branch (the `else: glyph_style = verb_spinner_style()` from Task 8), replace with:
```python
    else:
        glyph_style = shimmer_spinner_style(snapshot.elapsed_s, reduced_motion=reduced)
```
Leave `label_style` on `verb_spinner_style()` (label shouldn't shimmer).

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui_and_conv/test_shell_motion_shimmer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pythinker_code/ui/shell/motion.py tests/ui_and_conv/test_shell_motion_shimmer.py
git commit -m "feat(tui): subtle coral shimmer on active spinner"
```

---

### Task 12: Full-suite verification + manual visual check

**Files:** none (verification only)

- [ ] **Step 1: Run the whole UI test surface**

Run: `.venv/bin/python -m pytest tests/ui_and_conv tests/ui tests/core/test_config.py -q`
Expected: PASS (no skips of theme/snapshot tests).

- [ ] **Step 2: Lint + type checks the project uses**

Run: `.venv/bin/ruff check src/pythinker_code/ui && .venv/bin/ruff format --check src/pythinker_code/ui`
Expected: clean (fix any new findings in the files you touched only).

- [ ] **Step 3: Manual visual check (dark + light)**

Run the shell and eyeball the welcome screen, an active spinner, a tool card, a diff, and the footer in both themes:
```bash
.venv/bin/pythinker            # dark (default)
# then inside the shell: /theme light   and repeat the eyeball check
```
Confirm: logo unchanged; coral accents on caret/headings/spinner; cyan on directory/links; error stays clearly red; light-mode text is readable on cream.

- [ ] **Step 4: Confirm the `_LOGO` block is byte-for-byte unchanged**

Run: `git diff main -- src/pythinker_code/ui/shell/__init__.py | grep -n "_LOGO"`
Expected: no `_LOGO`/`_LOGO_*` constant or glyph lines appear in the diff.

- [ ] **Step 5: Final commit (if any lint/format fixes were made)**

```bash
git add -A src/pythinker_code/ui
git commit -m "chore(tui): lint/format after brand rebrand"
```

---

## Self-Review (completed against the spec)

- **Spec coverage:** P1 token values (Tasks 1–4), markdown (3), secondary palettes (4), snapshot regen (5) ✓. P2 welcome rows (6), `_TONE_STYLES` resolver (7), startup+verb spinner (8), sweep (9) ✓. P3 rounded borders (10), shimmer (11) ✓; footer is already token-driven (`footer.py` uses `tui_rich_style`/`render_segment_line`) so it inherits the rebrand with no code change — noted, no task needed beyond the visual check in Task 12. P4 (a11y variants) intentionally deferred to a follow-up plan.
- **Invariant:** `_LOGO` untouched is enforced by Task 6 scope note + Task 12 Step 4 check.
- **Placeholder scan:** every code step shows the code; the two sweep tasks (9, 10 Step 5) are discovery+transform with the exact before/after pattern and an explicit "documented exception" rule rather than vague "handle the rest."
- **Type consistency:** `shell_style(tone) -> Style`, `verb_spinner_style() -> Style`, `shimmer_spinner_style(elapsed_s, *, reduced_motion) -> Style`, `brand_panel(...) -> Panel`, `tui_rich_style(name) -> RichStyle` used consistently across tasks.
