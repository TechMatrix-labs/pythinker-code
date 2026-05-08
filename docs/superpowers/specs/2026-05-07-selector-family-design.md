# Selector Family Port — Design Spec

**Date:** 2026-05-07
**Branch:** tui-pi-foundation
**Status:** Approved

---

## Summary

Port all 11 Pi-style selector screens to Pythinker using Approach B: `run_selector()` where the UX fits a flat filterable list; focused standalone modules for UX paradigms that fundamentally differ (settings key/value editor, multi-toggle ordering, grouped resource manager, tree navigation).

---

## File Map

```
src/pythinker_code/ui/shell/
  selector.py                 ← extend: SelectorHeader + on_change callback
  selectors/
    __init__.py               ← re-exports all run_* functions
    theme.py                  ← run_theme_selector()
    thinking.py               ← run_thinking_selector()
    show_images.py            ← run_show_images_selector()
    extension.py              ← run_extension_selector()
    oauth.py                  ← run_oauth_selector()
    model.py                  ← run_model_selector()  (replaces model_picker.py)
    session.py                ← run_session_selector() (replaces session_picker.py)
    settings.py               ← run_settings_selector()
    scoped_models.py          ← run_scoped_models_selector()
    config.py                 ← run_config_selector()
    tree.py                   ← run_tree_selector() — stub (NotImplementedError)

tests/ui_and_conv/
  test_selectors_simple.py    ← Tier 1 unit tests
  test_selector_groups.py     ← group-header nav unit tests
  test_settings_selector.py   ← SettingItem cycling + cancel
  test_scoped_models_selector.py ← toggle / reorder / enable-all / clear-all
```

Existing `model_picker.py` and `session_picker.py` become one-line delegation wrappers for one release cycle, then are deleted once all callers are updated.

---

## Section 1: `selector.py` Extensions

Two small additions to `selector.py` — no behavior changes to existing code:

### 1a. `SelectorHeader`

```python
@dataclass(frozen=True, slots=True)
class SelectorHeader:
    label: str  # rendered as a section divider, not selectable
```

`SelectorConfig.items` type changes from `Sequence[SelectorItem[T]]` to
`Sequence[SelectorItem[T] | SelectorHeader]`.

Render loop: header rows use a distinct style (e.g. `class:slash-completion-menu.meta`)
and are skipped by cursor nav (up/down wraps past them).

### 1b. `on_change` callback

```python
@dataclass(frozen=True, slots=True)
class SelectorConfig[T]:
    ...
    on_change: Callable[[T], None] | None = None
```

Called whenever the cursor moves to a new `SelectorItem`. Used by `theme_selector`
for live preview. No-op when `None`.

---

## Section 2: Tier 1 — Simple Selectors

All four call `run_selector()` directly. Each file is ~20–40 lines.

### `selectors/theme.py`

```
run_theme_selector(
    current_theme: str,
    available_themes: list[str],
    on_preview: Callable[[str], None] | None = None,
) -> str | None
```

- Items built from `available_themes`; item matching `current_theme` gets `is_current=True`.
- `SelectorConfig.on_change = on_preview` for live preview.

### `selectors/thinking.py`

```
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]

LEVEL_DESCRIPTIONS: dict[ThinkingLevel, str] = {
    "off": "No reasoning",
    "minimal": "Very brief reasoning (~1k tokens)",
    "low": "Light reasoning (~2k tokens)",
    "medium": "Moderate reasoning (~8k tokens)",
    "high": "Deep reasoning (~16k tokens)",
    "xhigh": "Maximum reasoning (~32k tokens)",
}

run_thinking_selector(
    current_level: ThinkingLevel,
    available_levels: list[ThinkingLevel],
) -> ThinkingLevel | None
```

### `selectors/show_images.py`

```
run_show_images_selector(current: bool) -> bool | None
```

2-item list: `Yes` / `No`. Filter disabled (`enable_filter=False`).

### `selectors/extension.py`

```
run_extension_selector(
    title: str,
    options: list[str],
    *,
    current: str | None = None,
    timeout: float | None = None,
) -> str | None
```

Generic caller-supplied option list. `timeout` is best-effort (cancels after N seconds
via `asyncio.wait_for`).

---

## Section 3: Tier 2 — OAuth Selector Migration

`selectors/oauth.py` extracts the provider-picker part of the existing `oauth.py`
slash command handler.

```python
@dataclass(frozen=True, slots=True)
class OAuthProviderEntry:
    id: str    # platform id (e.g. "anthropic", "openrouter")
    label: str # display name

run_oauth_selector(
    providers: list[OAuthProviderEntry],
    *,
    action: Literal["login", "logout"] = "login",
) -> str | None  # returns provider id
```

Auth steps (API key prompts, browser launch) remain in `oauth.py` — only the
provider list is migrated. The existing `/login` slash command calls
`run_oauth_selector()` then dispatches to the appropriate auth flow.

---

## Section 4: Tier 3 — Existing Picker Migration

### `selectors/model.py` — migrates `model_picker.py`

Uses `SelectorHeader` to render provider group names as non-selectable dividers.

```
run_model_selector(
    groups: list[ProviderGroup],
    *,
    current_model_name: str | None = None,
) -> str | None  # returns model config key
```

`ProviderGroup` is imported from `model_picker.py` (no API change).
`model_picker.py` becomes:

```python
async def pick_model(...) -> str | None:
    return await run_model_selector(groups=..., current_model_name=...)
```

### `selectors/session.py` — migrates `session_picker.py`

Session picker keeps a thin custom `Application` because the Ctrl+A scope-toggle
requires async session reload that doesn't fit `run_selector()` cleanly.
The custom app is moved/cleaned up into `selectors/session.py`.

```
run_session_selector(
    work_dir: HostPath,
    current_session: Session,
) -> str | None  # returns session id
```

`session_picker.py` becomes a one-line wrapper.

---

## Section 5: Tier 4 — Complex New Selectors

### `selectors/settings.py`

Mirrors Pi's `SettingsList`. A key/value editor where Enter cycles a setting's
value; Esc exits with changes applied.

```python
@dataclass(frozen=True, slots=True)
class SettingItem:
    id: str
    label: str
    description: str
    current_value: str
    values: list[str]   # options to cycle through

run_settings_selector(items: list[SettingItem]) -> dict[str, str] | None
# Returns {id: new_value} for changed items, or None on cancel.
```

Custom `Application` (not `run_selector()`). No type-to-filter — settings list
is short. Key bindings: ↑↓ navigate, Enter cycle value, Esc cancel, Ctrl+C cancel.

The `/settings` slash command builds `SettingItem` rows from `Config` fields and
applies returned diffs to the live config.

### `selectors/scoped_models.py`

Multi-toggle with ordering. Session-local override of which models are active.

```
SCOPED_UNCHANGED: Final = object()  # sentinel returned on Esc (distinct from "all enabled")

run_scoped_models_selector(
    all_models: list[ModelEntry],
    enabled_ids: list[str] | None,  # None = all enabled
) -> list[str] | None | object
# Returns:
#   list[str]        — new ordered list of enabled model ids
#   None             — "all models enabled" (cleared filter)
#   SCOPED_UNCHANGED — user cancelled (Esc); caller should discard
```

Key bindings: ↑↓ navigate, Space toggle, Alt+↑/↓ reorder, `a` enable-all, `A` clear-all, Enter commit, Esc cancel.
Custom `Application`.

### `selectors/config.py`

Grouped resource manager. Enables/disables extensions, skills, prompts, themes
by source scope (user / project).

```
@dataclass
class ConfigResource:
    path: str
    display_name: str
    resource_type: Literal["extensions", "skills", "prompts", "themes"]
    scope: Literal["user", "project"]
    enabled: bool

run_config_selector(resources: list[ConfigResource]) -> dict[str, bool] | None
# Returns {path: enabled} for changed items, or None on cancel.
```

Key bindings: ↑↓ navigate, Space toggle, type to filter, Enter commit, Esc cancel.
Custom `Application` with grouped rendering.

### `selectors/tree.py`

Conversation tree navigation — **stub only in this spec**.

```python
async def run_tree_selector(*args, **kwargs) -> None:
    raise NotImplementedError(
        "tree_selector is not yet implemented; "
        "blocked on session tree data model verification"
    )
```

Depends on `SessionManager.get_tree()` or equivalent, which needs separate
investigation. Full implementation is a follow-up spec.

---

## Section 6: Slash-Command Wiring

Updates to `slash.py`:

| Command | Calls | Notes |
|---------|-------|-------|
| `/model` | `run_model_selector()` | Replace `ModelPickerApp` call |
| `/theme` | `run_theme_selector()` | New command |
| `/thinking` | `run_thinking_selector()` | New command |
| `/settings` | `run_settings_selector()` | Replace `ChoiceInput` call |
| `/login` | `run_oauth_selector()` | Migrate provider picker |
| `/models-scope` | `run_scoped_models_selector()` | New command |
| `/config` | `run_config_selector()` | New command |
| `/session` | `run_session_selector()` | Replace `SessionPickerApp` call |

---

## Section 7: Testing

All tests follow the pattern in `test_tui_card_selector.py` — pure state/render
logic, no TTY.

| Test file | What it tests |
|-----------|---------------|
| `test_selectors_simple.py` | `SelectorConfig` builds correctly for theme, thinking, show_images, extension; `is_current` placement |
| `test_selector_groups.py` | Header rows appear in correct positions; cursor nav skips headers; group nav wraps correctly |
| `test_settings_selector.py` | Cycling values; multi-item changes accumulate; cancel returns `None` |
| `test_scoped_models_selector.py` | Toggle, reorder (Alt+↑↓), enable-all, clear-all, cancel returns `_Unchanged` |

Manual smoke tests: each slash command opens without crashing in an interactive shell.

---

## Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| `SelectorHeader` sentinel vs. separate grouped-selector | Minimal change; no new layout machinery; mirrors how Pi renders group dividers inline |
| Session picker stays custom `Application` | Ctrl+A scope-toggle requires async reload; not worth overloading `SelectorConfig` for one outlier |
| Settings as standalone (not on `run_selector`) | Fundamentally different UX (cycle-in-place, not pick-from-list); mirrors Pi's `SelectList` vs `SettingsList` split |
| Tree as stub | Blocked on tree data model; better a clear `NotImplementedError` than a broken implementation |
| Existing pickers become delegation wrappers | Safe migration path; callers don't break on day 1 |
