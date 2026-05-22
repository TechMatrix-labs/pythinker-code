# Blackbox src TUI Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggressively restyle Pythinker's shell TUI around useful `blackbox/src` terminal UX patterns while preserving Pythinker's Python Rich/prompt_toolkit architecture.

**Architecture:** Add shared shell design primitives first, then port motion/thinking, transcript rows, compact tool/subagent activity, shared modal/dialog rendering, prompt/footer surfaces, and command/report views onto those primitives. Keep wire events, approval enforcement, provider behavior, and persisted session formats compatible.

**Tech Stack:** Python 3.12+, Rich, prompt_toolkit, pytest, existing Pythinker wire events, existing `uv`/`make` workflow.

---

## Scope And Sequencing

The approved spec is intentionally broad. Implement it as one coordinated restyle with small commits
and verification after each task. Do not vendor TypeScript, React, Ink, Blackbox hosted services, or
external dependencies. Treat `blackbox/src` as a behavior and design reference, then implement the
useful terminal UX in Python.

Every task below should be completed in order. If a task reveals a missing event field or runtime
constraint, add a narrowly scoped adapter and test instead of changing the wire protocol broadly.

---

## File Structure

Create these new shell UI modules:

- `src/pythinker_code/ui/shell/design_system.py`
  Shared terminal color roles, icons, keyboard hints, row metadata, dialog chrome helpers, and
  width-aware segment composition.
- `src/pythinker_code/ui/shell/motion.py`
  Blackbox-inspired spinner frames, reduced-motion support, elapsed/token status, and stalled-state
  helpers.
- `src/pythinker_code/ui/shell/visualize/_transcript.py`
  User/assistant/system/tool row grammar used by live and flushed output.
- `src/pythinker_code/ui/shell/visualize/_activity_tree.py`
  Compact active subagent/background-task row rendering.
- `src/pythinker_code/ui/shell/visualize/_dialog_shell.py`
  Shared approval/question/modal panel shell.
- `docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md`
  Audit map from `blackbox/src` areas to Pythinker implementation targets and explicit exclusions.

Modify these existing modules:

- `src/pythinker_code/ui/shell/visualize/_blocks.py`
  Replace local thinking/composing/status formatting with `motion.py` and transcript helpers.
- `src/pythinker_code/ui/shell/visualize/_live_view.py`
  Compose compact transcript/activity/dialog/footer output using shared primitives.
- `src/pythinker_code/ui/shell/visualize/_worklog.py`
  Align tool labels, states, cards, and grouped summaries with the design system.
- `src/pythinker_code/ui/shell/visualize/_approval_panel.py`
  Render through the shared dialog shell and standard option rows.
- `src/pythinker_code/ui/shell/visualize/_question_panel.py`
  Render through the shared dialog shell and standard option rows.
- `src/pythinker_code/ui/shell/components/footer.py`
  Restyle footer segments and hints with Blackbox-inspired prompt footer behavior.
- `src/pythinker_code/ui/theme.py`
  Add prompt_toolkit style tokens required by the restyled footer, completion menu, and modal rows.

Add or update tests:

- `tests/ui_and_conv/test_shell_design_system.py`
- `tests/ui_and_conv/test_shell_motion.py`
- `tests/ui_and_conv/test_transcript_rows.py`
- `tests/ui_and_conv/test_activity_tree.py`
- `tests/ui_and_conv/test_dialog_shell.py`
- `tests/ui_and_conv/test_streaming_content_block.py`
- `tests/ui_and_conv/test_tool_call_block.py`
- `tests/ui_and_conv/test_status_block.py`
- `tests/ui_and_conv/test_question_panel.py`
- `tests/ui_and_conv/test_modal_lifecycle.py`
- `tests/ui_and_conv/test_tui_render_snapshots.py`

---

### Task 1: Blackbox Source Audit Map

**Files:**
- Create: `docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md`
- Read: `blackbox/src/components/Spinner/`
- Read: `blackbox/src/components/messages/`
- Read: `blackbox/src/components/PromptInput/`
- Read: `blackbox/src/components/permissions/`
- Read: `blackbox/src/components/design-system/`
- Read: `blackbox/src/components/agents/`
- Read: `blackbox/src/components/tasks/`
- Read: `blackbox/src/commands/`
- Read: `blackbox/src/tools/`

- [ ] **Step 1: Write the port map document**

Create `docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md` with this structure:

````markdown
# Blackbox src Port Map

## Included Terminal UX Patterns

| Blackbox area | Pythinker target | Ported behavior |
| --- | --- | --- |
| `components/Spinner/SpinnerAnimationRow.tsx` | `ui/shell/motion.py`, `_blocks.py`, `_live_view.py` | spinner glyph, elapsed time, token status, stalled state, reduced motion |
| `components/Spinner/TeammateSpinnerLine.tsx` | `visualize/_activity_tree.py`, `_blocks.py` | compact active subagent rows with width-aware truncation |
| `components/messages/*` | `visualize/_transcript.py`, `_worklog.py` | user, assistant, thinking, tool, rejection, error row grammar |
| `components/PromptInput/*` | `components/footer.py`, prompt styles in `ui/theme.py` | stable mode/footer/hint/suggestion display |
| `components/permissions/*` | `visualize/_dialog_shell.py`, `_approval_panel.py` | shared approval modal shell and option rows |
| `components/design-system/*` | `ui/shell/design_system.py` | status icons, keyboard hints, dividers, panes, list rows |
| `components/agents/*`, `components/tasks/*` | `_activity_tree.py`, task browser follow-up renderers | task/subagent list and detail display patterns |
| `commands/*`, `tools/*` | existing slash/CLI commands and tool renderers | compatible command/report display patterns |

## Explicit Exclusions

- Do not vendor React, Ink, TypeScript, or Blackbox custom renderer internals.
- Do not add hosted service integrations, telemetry endpoints, or new dependencies.
- Do not change Pythinker approval enforcement, provider scoping, or persisted session formats.
- Do not copy product-specific commands unless Pythinker already has an equivalent workflow.

## Verification Source

The implementation is complete only after the visual smoke command runs:

```bash
uv run pythinker --yolo --prompt "scan code base "
```
````

- [ ] **Step 2: Commit the audit map**

Run:

```bash
git add docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md
git commit -m "docs(ui): map blackbox tui port scope"
```

Expected: commit succeeds and includes only the audit map.

---

### Task 2: Shared Shell Design System

**Files:**
- Create: `src/pythinker_code/ui/shell/design_system.py`
- Create: `tests/ui_and_conv/test_shell_design_system.py`
- Modify: `src/pythinker_code/ui/theme.py`

- [ ] **Step 1: Write failing tests for design primitives**

Create `tests/ui_and_conv/test_shell_design_system.py`:

```python
from __future__ import annotations

from rich.console import Console

from pythinker_code.ui.shell.design_system import (
    ShellTone,
    dialog_title,
    keyboard_hint,
    render_segment_line,
    status_icon,
)


def _plain(renderable, *, width: int = 80) -> str:
    console = Console(record=True, width=width, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_status_icon_names_are_stable():
    assert status_icon("running").plain
    assert status_icon("completed").plain
    assert status_icon("failed").plain
    assert status_icon("denied").plain


def test_keyboard_hint_uses_key_and_label():
    output = _plain(keyboard_hint("esc", "interrupt"))
    assert "esc" in output
    assert "interrupt" in output


def test_segment_line_hides_right_segments_before_wrapping():
    line = render_segment_line(
        left=["Pythinker Code", "insert"],
        right=["very-long-context-value", "shift+up/down agents"],
        width=32,
        tone=ShellTone.MUTED,
    )
    output = _plain(line, width=32)
    assert "Pythinker Code" in output
    assert all(len(row) <= 33 for row in output.splitlines() if row)


def test_dialog_title_includes_icon_and_title():
    output = _plain(dialog_title("approval", "Run shell command"))
    assert "Run shell command" in output
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/ui_and_conv/test_shell_design_system.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pythinker_code.ui.shell.design_system'`.

- [ ] **Step 3: Implement `design_system.py`**

Create `src/pythinker_code/ui/shell/design_system.py`:

```python
"""Shared Rich primitives for the Pythinker shell TUI."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from pythinker_code.ui.shell.components.render_utils import cell_width, truncate_to_width


class ShellTone(StrEnum):
    NORMAL = "normal"
    MUTED = "muted"
    ACCENT = "accent"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


StatusName = Literal[
    "running",
    "completed",
    "failed",
    "denied",
    "interrupted",
    "waiting",
    "question",
    "approval",
]


_TONE_STYLES: dict[ShellTone, Style] = {
    ShellTone.NORMAL: Style(color="default"),
    ShellTone.MUTED: Style(color="grey50"),
    ShellTone.ACCENT: Style(color="cyan"),
    ShellTone.SUCCESS: Style(color="green"),
    ShellTone.WARNING: Style(color="yellow"),
    ShellTone.ERROR: Style(color="red"),
    ShellTone.INFO: Style(color="blue"),
}

_STATUS: dict[StatusName, tuple[str, ShellTone]] = {
    "running": ("●", ShellTone.ACCENT),
    "completed": ("✓", ShellTone.SUCCESS),
    "failed": ("!", ShellTone.ERROR),
    "denied": ("×", ShellTone.WARNING),
    "interrupted": ("■", ShellTone.MUTED),
    "waiting": ("○", ShellTone.MUTED),
    "question": ("?", ShellTone.WARNING),
    "approval": ("?", ShellTone.ACCENT),
}


def shell_style(tone: ShellTone) -> Style:
    return _TONE_STYLES[tone]


def status_icon(name: StatusName) -> Text:
    icon, tone = _STATUS[name]
    return Text(icon, style=shell_style(tone))


def keyboard_hint(key: str, label: str) -> Text:
    text = Text()
    text.append(key, style=Style(color="cyan", bold=True))
    if label:
        text.append(f" {label}", style=shell_style(ShellTone.MUTED))
    return text


def dialog_title(kind: StatusName, title: str) -> Text:
    text = Text()
    text.append_text(status_icon(kind))
    text.append(f" {title}", style=Style(bold=True))
    return text


def render_segment_line(
    *,
    left: list[str],
    right: list[str],
    width: int,
    tone: ShellTone = ShellTone.MUTED,
) -> Text:
    left_text = " | ".join(part for part in left if part)
    right_parts = [part for part in right if part]
    right_text = " | ".join(right_parts)
    if width <= 0:
        return Text("")
    while right_parts and cell_width(left_text) + 2 + cell_width(right_text) > width:
        right_parts.pop()
        right_text = " | ".join(right_parts)
    if not right_text:
        return Text(truncate_to_width(left_text, width), style=shell_style(tone))
    gap = max(2, width - cell_width(left_text) - cell_width(right_text))
    return Text(left_text + (" " * gap) + right_text, style=shell_style(tone))


def render_row(icon: RenderableType, content: RenderableType) -> RenderableType:
    return Group(Text.assemble(icon, " "), content)
```

- [ ] **Step 4: Run design-system tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_shell_design_system.py -q
```

Expected: PASS.

- [ ] **Step 5: Add prompt_toolkit style tokens**

Modify `_PROMPT_STYLE_DARK` and `_PROMPT_STYLE_LIGHT` in `src/pythinker_code/ui/theme.py` by
adding these keys to both dictionaries with the explicit colors below:

```python
"shell-dialog": "fg:#d1d5db",
"shell-dialog.title": "fg:#e5e7eb bold",
"shell-dialog.border": "fg:#4b5563",
"shell-dialog.option": "fg:#9ca3af",
"shell-dialog.option.current": "bg:#1f2937 fg:#67e8f9 bold",
"shell-footer.key": "fg:#67e8f9 bold",
"shell-footer.meta": "fg:#9ca3af",
"shell-footer.warning": "fg:#fbbf24",
"shell-footer.error": "fg:#fca5a5",
```

For light theme, use the same keys with readable light colors already used by nearby prompt tokens.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add src/pythinker_code/ui/shell/design_system.py src/pythinker_code/ui/theme.py tests/ui_and_conv/test_shell_design_system.py
git commit -m "feat(ui): add shell design primitives"
```

Expected: commit succeeds.

---

### Task 3: Motion And Thinking Status

**Files:**
- Create: `src/pythinker_code/ui/shell/motion.py`
- Create: `tests/ui_and_conv/test_shell_motion.py`
- Modify: `src/pythinker_code/ui/shell/visualize/_blocks.py`
- Modify: `src/pythinker_code/ui/shell/visualize/_live_view.py`
- Test: `tests/ui_and_conv/test_streaming_content_block.py`

- [ ] **Step 1: Write failing motion tests**

Create `tests/ui_and_conv/test_shell_motion.py`:

```python
from __future__ import annotations

from rich.console import Console

from pythinker_code.ui.shell.motion import ActivitySnapshot, activity_status_line, spinner_frame_at


def _plain(renderable) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_spinner_frame_changes_with_time():
    assert spinner_frame_at(0.0) != spinner_frame_at(0.2)


def test_reduced_motion_uses_static_glyph():
    assert spinner_frame_at(0.2, reduced_motion=True) == "●"


def test_activity_status_line_contains_label_elapsed_tokens_and_interrupt_hint():
    line = activity_status_line(
        ActivitySnapshot(label="Thinking", elapsed_s=12.0, tokens=2400, token_rate=42)
    )
    output = _plain(line)
    assert "Thinking" in output
    assert "12s" in output
    assert "2.4k tokens" in output
    assert "42 tok/s" in output
    assert "esc to interrupt" in output


def test_activity_status_line_hides_secondary_parts_at_narrow_width():
    line = activity_status_line(
        ActivitySnapshot(label="Thinking", elapsed_s=12.0, tokens=2400, token_rate=42),
        width=24,
    )
    output = _plain(line)
    assert "Thinking" in output
    assert "42 tok/s" not in output
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/ui_and_conv/test_shell_motion.py -q
```

Expected: FAIL with missing `pythinker_code.ui.shell.motion`.

- [ ] **Step 3: Implement `motion.py`**

Create `src/pythinker_code/ui/shell/motion.py`:

```python
"""Blackbox-inspired motion helpers for the shell TUI."""

from __future__ import annotations

import os
from dataclasses import dataclass

from rich.text import Text

from pythinker_code.soul import format_token_count
from pythinker_code.ui.shell.components.render_utils import cell_width
from pythinker_code.ui.shell.design_system import ShellTone, shell_style
from pythinker_code.utils.datetime import format_elapsed

_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_FRAME_INTERVAL_S = 0.08


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    label: str
    elapsed_s: float
    tokens: int = 0
    token_rate: int | None = None
    stalled: bool = False
    interrupt_hint: str = "esc to interrupt"
    reduced_motion: bool = False


def reduced_motion_enabled() -> bool:
    return os.environ.get("PYTHINKER_REDUCED_MOTION", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def spinner_frame_at(elapsed_s: float, *, reduced_motion: bool = False) -> str:
    if reduced_motion:
        return "●"
    index = int(max(0.0, elapsed_s) / _FRAME_INTERVAL_S) % len(_FRAMES)
    return _FRAMES[index]


def _candidate_parts(snapshot: ActivitySnapshot) -> list[str]:
    parts = [format_elapsed(snapshot.elapsed_s)]
    if snapshot.tokens:
        parts.append(f"{format_token_count(snapshot.tokens)} tokens")
    if snapshot.token_rate:
        parts.append(f"{snapshot.token_rate} tok/s")
    if snapshot.interrupt_hint:
        parts.append(snapshot.interrupt_hint)
    return parts


def activity_status_line(snapshot: ActivitySnapshot, *, width: int | None = None) -> Text:
    reduced = snapshot.reduced_motion or reduced_motion_enabled()
    glyph_style = ShellTone.WARNING if snapshot.stalled else ShellTone.ACCENT
    text = Text(spinner_frame_at(snapshot.elapsed_s, reduced_motion=reduced), style=shell_style(glyph_style))
    text.append(" ")
    text.append(snapshot.label, style="italic" if snapshot.label.lower() == "thinking" else "")

    parts = _candidate_parts(snapshot)
    if width is not None:
        base_width = cell_width(text.plain)
        kept: list[str] = []
        for part in parts:
            candidate = " · ".join([*kept, part])
            if base_width + 2 + cell_width(candidate) <= width:
                kept.append(part)
        parts = kept
    if parts:
        text.append(" ")
        text.append(" · ".join(parts), style=shell_style(ShellTone.MUTED))
    return text
```

- [ ] **Step 4: Run motion tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_shell_motion.py -q
```

Expected: PASS.

- [ ] **Step 5: Replace thinking/composing renderers**

Modify `src/pythinker_code/ui/shell/visualize/_blocks.py`:

1. Add import:

```python
from pythinker_code.ui.shell.motion import ActivitySnapshot, activity_status_line
```

2. Replace `_compose_spinner`, `_compose_thinking_spinner`, and `_compose_thinking` bodies with:

```python
    def _activity_snapshot(self, label: str) -> ActivitySnapshot:
        elapsed = time.monotonic() - self._start_time
        tokens_int = int(self._token_count)
        token_rate = None
        if elapsed > 0.5 and tokens_int > 0:
            rate = int(tokens_int / elapsed)
            token_rate = rate if rate > 0 else None
        return ActivitySnapshot(
            label=label,
            elapsed_s=elapsed,
            tokens=tokens_int,
            token_rate=token_rate,
        )

    def _compose_spinner(self) -> Text:
        return activity_status_line(self._activity_snapshot("Composing"), width=console.width)

    def _compose_thinking_spinner(self) -> Text:
        return activity_status_line(self._activity_snapshot("Thinking"), width=console.width)

    def _compose_thinking(self) -> Text:
        return activity_status_line(self._activity_snapshot("Thinking"), width=console.width)
```

Keep `_compose_thinking_stream()` unchanged except that it now calls the new
`_compose_thinking_spinner()`.

- [ ] **Step 6: Replace generic working indicator**

Modify `_working_indicator()` in `src/pythinker_code/ui/shell/visualize/_live_view.py`:

```python
    def _working_indicator(self) -> Text:
        return activity_status_line(
            ActivitySnapshot(label="Working", elapsed_s=time.monotonic()),
            width=console.width,
        )
```

Add import:

```python
from pythinker_code.ui.shell.motion import ActivitySnapshot, activity_status_line
```

Remove unused imports from `pythinker_code.ui.shell.spinner_words`.

- [ ] **Step 7: Update existing content-block tests**

Update `tests/ui_and_conv/test_streaming_content_block.py` so the existing composing and thinking
assertions expect the new status line but not the old dot-only animation. Keep these assertions:

```python
assert "Composing" in output
assert "tokens" in output
```

Add:

```python
def test_thinking_status_line_shows_interrupt_hint():
    block = _ContentBlock(is_think=True)
    block.append("reasoning")
    console = Console(record=True, width=120, color_system=None)
    console.print(block.compose())
    output = console.export_text()
    assert "Thinking" in output
    assert "esc to interrupt" in output
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_shell_motion.py tests/ui_and_conv/test_streaming_content_block.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

Run:

```bash
git add src/pythinker_code/ui/shell/motion.py src/pythinker_code/ui/shell/visualize/_blocks.py src/pythinker_code/ui/shell/visualize/_live_view.py tests/ui_and_conv/test_shell_motion.py tests/ui_and_conv/test_streaming_content_block.py
git commit -m "feat(ui): port blackbox-style motion status"
```

Expected: commit succeeds.

---

### Task 4: Transcript Rows And Compact Activity Tree

**Files:**
- Create: `src/pythinker_code/ui/shell/visualize/_transcript.py`
- Create: `src/pythinker_code/ui/shell/visualize/_activity_tree.py`
- Create: `tests/ui_and_conv/test_transcript_rows.py`
- Create: `tests/ui_and_conv/test_activity_tree.py`
- Modify: `src/pythinker_code/ui/shell/visualize/_blocks.py`
- Test: `tests/ui_and_conv/test_tool_call_block.py`

- [ ] **Step 1: Write transcript row tests**

Create `tests/ui_and_conv/test_transcript_rows.py`:

```python
from __future__ import annotations

from rich.console import Console

from pythinker_code.ui.shell.visualize._transcript import render_transcript_row


def _plain(renderable, *, width: int = 80) -> str:
    console = Console(record=True, width=width, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_user_row_contains_role_and_content():
    output = _plain(render_transcript_row("user", "scan this codebase"))
    assert "You" in output
    assert "scan this codebase" in output


def test_tool_row_contains_label_target_and_status():
    output = _plain(render_transcript_row("tool", "Read src/app.py", status="completed"))
    assert "Read src/app.py" in output
    assert "✓" in output
```

- [ ] **Step 2: Write activity tree tests**

Create `tests/ui_and_conv/test_activity_tree.py`:

```python
from __future__ import annotations

from rich.console import Console

from pythinker_code.ui.shell.visualize._activity_tree import ActivityRow, render_activity_tree


def _plain(renderable, *, width: int = 80) -> str:
    console = Console(record=True, width=width, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_activity_tree_renders_compact_rows():
    output = _plain(
        render_activity_tree(
            [
                ActivityRow(label="explore", detail="Read _live_view.py", state="running"),
                ActivityRow(label="review", detail="Finished audit", state="completed"),
            ],
            width=80,
        )
    )
    assert "explore" in output
    assert "Read _live_view.py" in output
    assert "review" in output


def test_activity_tree_truncates_long_detail():
    output = _plain(
        render_activity_tree(
            [ActivityRow(label="explore", detail="x" * 120, state="running")],
            width=40,
        ),
        width=40,
    )
    assert all(len(row) <= 41 for row in output.splitlines() if row)
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/ui_and_conv/test_transcript_rows.py tests/ui_and_conv/test_activity_tree.py -q
```

Expected: FAIL with missing modules.

- [ ] **Step 4: Implement `_transcript.py`**

Create `src/pythinker_code/ui/shell/visualize/_transcript.py`:

```python
"""Shared transcript rows for live and flushed shell output."""

from __future__ import annotations

from typing import Literal

from rich.console import Group, RenderableType
from rich.text import Text

from pythinker_code.ui.shell.design_system import ShellTone, shell_style, status_icon

Role = Literal["user", "assistant", "tool", "system", "notification"]
Status = Literal["running", "completed", "failed", "denied", "interrupted", "waiting"]

_ROLE_LABELS: dict[Role, str] = {
    "user": "You",
    "assistant": "Assistant",
    "tool": "Tool",
    "system": "System",
    "notification": "Notice",
}


def render_transcript_row(
    role: Role,
    content: str | RenderableType,
    *,
    status: Status | None = None,
) -> RenderableType:
    label = _ROLE_LABELS[role]
    prefix = Text()
    if status:
        prefix.append_text(status_icon(status))
        prefix.append(" ")
    prefix.append(label, style=shell_style(ShellTone.MUTED))
    if isinstance(content, str):
        body: RenderableType = Text(content)
    else:
        body = content
    return Group(prefix, body)
```

- [ ] **Step 5: Implement `_activity_tree.py`**

Create `src/pythinker_code/ui/shell/visualize/_activity_tree.py`:

```python
"""Compact active agent and task rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.console import Group, RenderableType
from rich.text import Text

from pythinker_code.ui.shell.components.render_utils import cell_width, truncate_to_width
from pythinker_code.ui.shell.design_system import ShellTone, shell_style, status_icon

ActivityState = Literal["running", "completed", "failed", "waiting", "denied", "interrupted"]


@dataclass(frozen=True, slots=True)
class ActivityRow:
    label: str
    detail: str
    state: ActivityState = "running"
    identity: str | None = None


def render_activity_tree(rows: list[ActivityRow], *, width: int, max_rows: int = 4) -> RenderableType:
    rendered: list[RenderableType] = []
    visible = rows[-max_rows:]
    hidden = max(0, len(rows) - len(visible))
    for index, row in enumerate(visible):
        branch = "└─" if index == len(visible) - 1 else "├─"
        label = row.label if row.identity is None else f"{row.label} {row.identity}"
        prefix = f"{branch} {label} "
        available = max(1, width - cell_width(prefix) - 4)
        text = Text()
        text.append_text(status_icon(row.state))
        text.append(" ")
        text.append(prefix, style=shell_style(ShellTone.MUTED))
        text.append(truncate_to_width(row.detail, available), style=shell_style(ShellTone.MUTED))
        rendered.append(text)
    if hidden:
        rendered.insert(0, Text(f"… {hidden} older agent activities hidden", style=shell_style(ShellTone.MUTED)))
    return Group(*rendered)
```

- [ ] **Step 6: Run new tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_transcript_rows.py tests/ui_and_conv/test_activity_tree.py -q
```

Expected: PASS.

- [ ] **Step 7: Wire compact subagent rows into `_ToolCallBlock`**

Modify `src/pythinker_code/ui/shell/visualize/_blocks.py`:

1. Import:

```python
from pythinker_code.ui.shell.visualize._activity_tree import ActivityRow, render_activity_tree
```

2. In `_ToolCallBlock._compose()`, replace the loop that appends one `BulletColumns` row per
finished sub-call with:

```python
            rows: list[ActivityRow] = []
            for sub_call, sub_result in self._finished_subagent_tool_calls:
                argument = extract_key_argument(
                    sub_call.function.arguments or "", sub_call.function.name
                )
                detail = sub_call.function.name
                if argument:
                    detail = f"{detail} {argument}"
                rows.append(
                    ActivityRow(
                        label="agent",
                        detail=detail,
                        state="failed" if sub_result.is_error else "completed",
                    )
                )
            if rows:
                children.append(render_activity_tree(rows, width=console.width))
```

Keep the existing summary line for completed `Agent` calls so finished background agents remain
readable.

- [ ] **Step 8: Update subagent tests**

Update `tests/ui_and_conv/test_tool_call_block.py::test_completed_subagent_renders_compact_summary`
so it asserts compact activity rows instead of old `Used ReadFile` wording:

```python
assert "Subagent" in output
assert "completed" in output.lower()
assert "7 tool calls" in output
assert output.count("ReadFile") <= 4
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_transcript_rows.py tests/ui_and_conv/test_activity_tree.py tests/ui_and_conv/test_tool_call_block.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 4**

Run:

```bash
git add src/pythinker_code/ui/shell/visualize/_transcript.py src/pythinker_code/ui/shell/visualize/_activity_tree.py src/pythinker_code/ui/shell/visualize/_blocks.py tests/ui_and_conv/test_transcript_rows.py tests/ui_and_conv/test_activity_tree.py tests/ui_and_conv/test_tool_call_block.py
git commit -m "feat(ui): add compact transcript activity rows"
```

Expected: commit succeeds.

---

### Task 5: Shared Dialog Shell For Approvals And Questions

**Files:**
- Create: `src/pythinker_code/ui/shell/visualize/_dialog_shell.py`
- Create: `tests/ui_and_conv/test_dialog_shell.py`
- Modify: `src/pythinker_code/ui/shell/visualize/_approval_panel.py`
- Modify: `src/pythinker_code/ui/shell/visualize/_question_panel.py`
- Test: `tests/ui_and_conv/test_question_panel.py`
- Test: `tests/ui_and_conv/test_modal_lifecycle.py`

- [ ] **Step 1: Write failing dialog shell tests**

Create `tests/ui_and_conv/test_dialog_shell.py`:

```python
from __future__ import annotations

from rich.console import Console
from rich.text import Text

from pythinker_code.ui.shell.visualize._dialog_shell import DialogOption, render_dialog


def _plain(renderable, *, width: int = 80) -> str:
    console = Console(record=True, width=width, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_dialog_renders_title_body_and_options():
    output = _plain(
        render_dialog(
            kind="approval",
            title="Run shell command",
            body=[Text("pytest")],
            options=[
                DialogOption(label="Approve once", selected=True, key="1"),
                DialogOption(label="Reject", selected=False, key="2"),
            ],
        )
    )
    assert "Run shell command" in output
    assert "pytest" in output
    assert "Approve once" in output
    assert "Reject" in output
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/ui_and_conv/test_dialog_shell.py -q
```

Expected: FAIL with missing `_dialog_shell`.

- [ ] **Step 3: Implement `_dialog_shell.py`**

Create `src/pythinker_code/ui/shell/visualize/_dialog_shell.py`:

```python
"""Shared shell dialog chrome for approvals, questions, and modal-like panels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from pythinker_code.ui.shell.design_system import dialog_title

DialogKind = Literal["approval", "question", "warning", "info"]


@dataclass(frozen=True, slots=True)
class DialogOption:
    label: str
    selected: bool = False
    key: str | None = None
    description: str | None = None


def _render_option(option: DialogOption) -> Text:
    prefix = "→" if option.selected else " "
    key = f"[{option.key}] " if option.key else ""
    style = "cyan bold" if option.selected else "grey50"
    text = Text(f"{prefix} {key}{option.label}", style=style)
    if option.description:
        text.append(f"  {option.description}", style="dim")
    return text


def render_dialog(
    *,
    kind: DialogKind,
    title: str,
    body: list[RenderableType],
    options: list[DialogOption],
    footer: RenderableType | None = None,
    border_style: str = "grey50",
) -> RenderableType:
    lines: list[RenderableType] = []
    lines.extend(body)
    if body and options:
        lines.append(Text(""))
    lines.extend(_render_option(option) for option in options)
    if footer is not None:
        lines.append(Text(""))
        lines.append(footer)
    return Panel(
        Group(*lines),
        title=dialog_title("approval" if kind == "approval" else "question", title),
        title_align="left",
        border_style=border_style,
        padding=(0, 1),
    )
```

- [ ] **Step 4: Run dialog shell tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_dialog_shell.py -q
```

Expected: PASS.

- [ ] **Step 5: Refactor approval panel render**

Modify `ApprovalRequestPanel.render()` in
`src/pythinker_code/ui/shell/visualize/_approval_panel.py`:

1. Import:

```python
from pythinker_code.ui.shell.visualize._dialog_shell import DialogOption, render_dialog
```

2. Replace the final `Panel(...)` construction with:

```python
        dialog_options = [
            DialogOption(
                label=option_text,
                selected=i == self.selected_index,
                key=str(i + 1),
            )
            for i, (option_text, _) in enumerate(self.options)
        ]
        footer = Text("↑/↓ select  ↵ submit  ctrl-e expand", style="dim")
        return render_dialog(
            kind="approval",
            title=f"{self.request.sender} approval",
            body=lines,
            options=dialog_options,
            footer=footer,
            border_style="yellow",
        )
```

Preserve feedback input behavior by keeping the existing inline feedback rows in `lines`.

- [ ] **Step 6: Refactor question panel render**

Modify `QuestionRequestPanel.render()` in
`src/pythinker_code/ui/shell/visualize/_question_panel.py`:

1. Import:

```python
from pythinker_code.ui.shell.visualize._dialog_shell import DialogOption, render_dialog
```

2. Build options with the current selection state:

```python
        dialog_options = [
            DialogOption(
                label=label,
                selected=i == self._selected_index,
                key=str(i + 1),
                description=description or None,
            )
            for i, (label, description) in enumerate(self._options)
        ]
```

3. Replace the final `Panel(...)` with:

```python
        footer = Text("↑/↓ select  ↵ submit  esc exit", style="dim")
        return render_dialog(
            kind="question",
            title="question",
            body=lines,
            options=dialog_options,
            footer=footer,
            border_style="yellow",
        )
```

Keep multi-select checkmarks by placing the checked state in `label` before building
`DialogOption`.

- [ ] **Step 7: Run dialog, question, and modal tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_dialog_shell.py tests/ui_and_conv/test_question_panel.py tests/ui_and_conv/test_modal_lifecycle.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

Run:

```bash
git add src/pythinker_code/ui/shell/visualize/_dialog_shell.py src/pythinker_code/ui/shell/visualize/_approval_panel.py src/pythinker_code/ui/shell/visualize/_question_panel.py tests/ui_and_conv/test_dialog_shell.py tests/ui_and_conv/test_question_panel.py tests/ui_and_conv/test_modal_lifecycle.py
git commit -m "feat(ui): standardize shell dialogs"
```

Expected: commit succeeds.

---

### Task 6: Footer, Prompt, And Status Consistency

**Files:**
- Modify: `src/pythinker_code/ui/shell/components/footer.py`
- Modify: `src/pythinker_code/ui/shell/visualize/_blocks.py`
- Modify: `src/pythinker_code/ui/theme.py`
- Test: `tests/ui_and_conv/test_status_block.py`
- Test: `tests/ui_and_conv/test_tui_card_footer.py`
- Test: `tests/ui_and_conv/test_shell_prompt_router.py`
- Test: `tests/ui_and_conv/test_slash_completer.py`

- [ ] **Step 1: Add footer hint tests**

Extend `tests/ui_and_conv/test_tui_card_footer.py` with:

```python
def test_footer_keeps_context_and_hints_width_safe():
    from pythinker_code.ui.shell.components.footer import FooterState, render_footer
    from pythinker_code.ui.shell.components.render_utils import render_plain

    footer = render_footer(
        FooterState(
            cwd="/tmp/project",
            context_percent=8.9,
            context_window=262000,
            model_id="gpt-5",
            extension_statuses={"agents": "shift+up/down agents", "interrupt": "esc interrupt"},
        ),
        width=48,
    )
    output = render_plain(footer, width=48)
    assert "8.9%" in output
    assert "gpt-5" in output
    assert all(len(row) <= 49 for row in output.splitlines() if row)
```

- [ ] **Step 2: Run footer tests and capture current behavior**

Run:

```bash
uv run pytest tests/ui_and_conv/test_status_block.py tests/ui_and_conv/test_tui_card_footer.py -q
```

Expected: either PASS before changes or FAIL only on the new width-safety assertion.

- [ ] **Step 3: Use shared segment line in footer**

Modify `render_footer()` in `src/pythinker_code/ui/shell/components/footer.py`:

1. Import:

```python
from pythinker_code.ui.shell.design_system import ShellTone, render_segment_line
```

2. Replace the manual right-side spacing block for `stats_line` with:

```python
    right = _build_right_side(state, plain_left_width=len(stats_left_plain), width=width)
    stats_line = render_segment_line(
        left=[stats_left_plain],
        right=[right],
        width=width,
        tone=ShellTone.MUTED,
    )
```

3. Preserve colored warning/error context by appending a short pre-check before the replacement:

```python
    if state.context_percent is not None and state.context_percent > 70:
        stats_line.stylize(tui_rich_style("warning" if state.context_percent <= 90 else "error"))
```

- [ ] **Step 4: Keep `_StatusBlock` compatible**

In `src/pythinker_code/ui/shell/visualize/_blocks.py`, keep `_StatusBlock.text` and `.render()`
public behavior intact so `tests/ui_and_conv/test_status_block.py` continues to pass. If rendering
uses shared footer helpers, still expose `self.text` as the plain status line.

- [ ] **Step 5: Run prompt/footer/status tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_status_block.py tests/ui_and_conv/test_tui_card_footer.py tests/ui_and_conv/test_shell_prompt_router.py tests/ui_and_conv/test_slash_completer.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add src/pythinker_code/ui/shell/components/footer.py src/pythinker_code/ui/shell/visualize/_blocks.py src/pythinker_code/ui/theme.py tests/ui_and_conv/test_tui_card_footer.py tests/ui_and_conv/test_status_block.py
git commit -m "feat(ui): align shell footer status styling"
```

Expected: commit succeeds.

---

### Task 7: Tool Cards, Reports, And Command Screens

**Files:**
- Modify: `src/pythinker_code/ui/shell/visualize/_worklog.py`
- Modify: `src/pythinker_code/ui/shell/tool_renderers/generic.py`
- Modify: `src/pythinker_code/ui/shell/tool_renderers/shell.py`
- Modify: `src/pythinker_code/ui/shell/tool_renderers/todo.py`
- Modify: `src/pythinker_code/ui/shell/tool_renderers/agent.py`
- Test: `tests/ui_and_conv/test_worklog_render.py`
- Test: `tests/ui_and_conv/test_tui_card_tool_renderers.py`
- Test: `tests/ui_and_conv/test_tui_render_snapshots.py`

- [ ] **Step 1: Add grouped tool summary test**

Extend `tests/ui_and_conv/test_worklog_render.py`:

```python
def test_worklog_entry_uses_shared_status_language():
    from pythinker_code.ui.shell.components.render_utils import render_plain
    from pythinker_code.ui.shell.visualize._worklog import WorkLogState, render_worklog_entry

    output = render_plain(
        render_worklog_entry(
            label="Shell",
            target="pytest",
            state=WorkLogState.FAILED,
            detail="exit code 1",
        ),
        width=100,
    )
    assert "Shell" in output
    assert "pytest" in output
    assert "failed" in output.lower()
    assert "exit code 1" in output
```

- [ ] **Step 2: Run renderer tests before changes**

Run:

```bash
uv run pytest tests/ui_and_conv/test_worklog_render.py tests/ui_and_conv/test_tui_card_tool_renderers.py -q
```

Expected: PASS or fail only on the newly added expectation if current state language differs.

- [ ] **Step 3: Align worklog labels and status styles**

Modify `src/pythinker_code/ui/shell/visualize/_worklog.py`:

1. Import shared icons and tones:

```python
from pythinker_code.ui.shell.design_system import ShellTone, shell_style, status_icon
```

2. In the worklog entry renderer, use `status_icon()` for completed, running, failed, denied, and
interrupted states. Keep the existing `WorkLogState` enum unchanged.

3. Keep `tool_style()` return values compatible with existing tests and renderers.

- [ ] **Step 4: Restyle generic/shell/todo/agent renderers**

For each touched renderer, use the same rules:

```python
from pythinker_code.ui.shell.components.render_utils import render_message_response
```

Wrap substantial result bodies with `render_message_response(...)`, keep short one-line results
inline, and sanitize shell output before rendering. Existing renderer APIs must remain unchanged.

- [ ] **Step 5: Run renderer and snapshot tests**

Run:

```bash
uv run pytest tests/ui_and_conv/test_worklog_render.py tests/ui_and_conv/test_tui_card_tool_renderers.py tests/ui_and_conv/test_tui_render_snapshots.py -q
```

Expected: PASS. If snapshots fail only because the approved restyle changed output, update the
expected snapshot strings in the same commit and include the changed before/after meaning in the
commit message body.

- [ ] **Step 6: Commit Task 7**

Run:

```bash
git add src/pythinker_code/ui/shell/visualize/_worklog.py src/pythinker_code/ui/shell/tool_renderers/generic.py src/pythinker_code/ui/shell/tool_renderers/shell.py src/pythinker_code/ui/shell/tool_renderers/todo.py src/pythinker_code/ui/shell/tool_renderers/agent.py tests/ui_and_conv/test_worklog_render.py tests/ui_and_conv/test_tui_card_tool_renderers.py tests/ui_and_conv/test_tui_render_snapshots.py
git commit -m "feat(ui): restyle tool result displays"
```

Expected: commit succeeds.

---

### Task 8: Useful Prompt, Agent, Skill, And Command Audits

**Files:**
- Modify: `docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md`
- Modify only if justified by the audit: `src/pythinker_code/agents/*.yaml`
- Modify only if justified by the audit: `src/pythinker_code/agents/**/*.md`
- Modify only if justified by the audit: `src/pythinker_code/skill/`
- Modify only if justified by the audit: `src/pythinker_code/skills/`
- Test: focused prompt/spec/skill tests identified by `rg "agentspec|skill|prompt" tests tests_ai`

- [ ] **Step 1: Add audit outcome sections to the port map**

Append these sections to `docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md`:

````markdown
## Prompt And Agent Ideas Adapted

| Blackbox source | Pythinker destination | Decision |
| --- | --- | --- |
| `constants/systemPromptSections.ts` | Pythinker agent spec prompts | Adapt only reusable terminal-behavior wording that improves tool/result summaries |
| `tools/AgentTool/builtInAgents.ts` | `src/pythinker_code/agents/` | Adapt taxonomy ideas only when they match existing Pythinker subagent roles |
| `services/toolUseSummary/` | UI-only tool summary labels | Use concise label style without adding another LLM call |
| `skills/bundled/` | Pythinker skill system | Adopt only local, safe workflow ideas that fit existing skill loading |

## Rejected Product-Specific Areas

- Hosted account flows, Slack/GitHub app install surfaces, and remote-only services are not ported.
- Analytics-specific prompt or metadata code is not ported.
- Product names, proprietary service endpoints, and unrelated commands are not ported.
```
````

- [ ] **Step 2: Search current Pythinker prompt/spec tests**

Run:

```bash
rg -n "agentspec|agent spec|skill|prompt|system prompt" tests tests_ai src/pythinker_code -g '*.py'
```

Expected: output identifies existing tests or code paths to use for any prompt/spec change.

- [ ] **Step 3: Apply only compatible prompt/spec edits**

If the audit identifies a concrete wording improvement, edit the exact Pythinker prompt/spec file
and add a focused invariant test. Example invariant test pattern:

```python
def test_default_agent_prompt_mentions_concise_tool_summaries():
    text = Path("src/pythinker_code/agents/default/prompt.md").read_text()
    assert "concise" in text.lower()
    assert "tool" in text.lower()
```

If no prompt/spec edit is justified after the audit, commit only the audit map update and mention in
the commit body that incompatible hosted/product-specific features were rejected.

- [ ] **Step 4: Run affected prompt/spec tests**

Run the focused test command identified in Step 2. If no prompt/spec code changed, run:

```bash
uv run pytest tests/ui_and_conv/test_shell_design_system.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 8**

Run:

```bash
git add docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md src/pythinker_code/agents src/pythinker_code/skill src/pythinker_code/skills tests tests_ai
git commit -m "docs(ui): record blackbox prompt and agent audit"
```

Expected: commit succeeds. If `git diff --cached --name-only` includes unrelated files from broad
pathspecs, unstage them with `git restore --staged <path>` before committing.

---

### Task 9: Integration Pass And Visual Smoke Evaluation

**Files:**
- Modify: files touched by Tasks 2-8 only when a verification command identifies a concrete failure.
- Update: `docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md`

- [ ] **Step 1: Run focused UI suite**

Run:

```bash
uv run pytest \
  tests/ui_and_conv/test_shell_design_system.py \
  tests/ui_and_conv/test_shell_motion.py \
  tests/ui_and_conv/test_transcript_rows.py \
  tests/ui_and_conv/test_activity_tree.py \
  tests/ui_and_conv/test_dialog_shell.py \
  tests/ui_and_conv/test_streaming_content_block.py \
  tests/ui_and_conv/test_tool_call_block.py \
  tests/ui_and_conv/test_status_block.py \
  tests/ui_and_conv/test_question_panel.py \
  tests/ui_and_conv/test_modal_lifecycle.py \
  tests/ui_and_conv/test_tui_render_snapshots.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run package check**

Run:

```bash
make check-pythinker-code
```

Expected: PASS. If pyright or ruff fails, fix only the files touched by this plan and rerun.

- [ ] **Step 3: Run required visual smoke command**

Run:

```bash
uv run pythinker --yolo --prompt "scan code base "
```

Expected:

- the command starts successfully
- the TUI shows a compact thinking/composing status
- active subagents/tools use compact rows rather than tall repeated cards
- footer/context/model/hints stay stable
- no rows overlap or render beyond the terminal viewport
- interruptions still leave readable scrollback

Let the command run long enough to exercise subagents and tool calls. Interrupt after the visual
criteria are observable if the scan continues indefinitely.

- [ ] **Step 4: Record visual evaluation**

Append to `docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md`:

````markdown
## Visual Smoke Result

Command:

```bash
uv run pythinker --yolo --prompt "scan code base "
```

Observed:

- Thinking/composing status:
- Subagent/tool activity:
- Footer/context stability:
- Overlap/viewport behavior:
- Interrupt cleanup:
```
````

Fill each bullet with the observed result from the real run. Keep the content concise and avoid
copying secrets or sensitive paths.

- [ ] **Step 5: Commit final verification record**

Run:

```bash
git add docs/superpowers/artifacts/2026-05-22-blackbox-src-port-map.md
git commit -m "test(ui): record tui visual smoke evaluation"
```

Expected: commit succeeds.

---

## Final Completion Criteria

Before calling the implementation complete:

- All tasks above are checked off in this plan.
- Focused UI tests from Task 9 pass.
- `make check-pythinker-code` passes.
- `uv run pythinker --yolo --prompt "scan code base "` has been run and visually evaluated.
- `git status --short` contains no uncommitted implementation changes except intentionally ignored
  local scratch directories such as `.superpowers/`.
- The final response lists the commands run and clearly reports any command that could not be
  completed.
