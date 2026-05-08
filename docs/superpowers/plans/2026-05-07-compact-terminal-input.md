# Compact Terminal Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shell input area use Claude-style separators and a compact prompt marker without deforming slash completions.

**Architecture:** Keep the change inside the existing prompt-toolkit `CustomPromptSession`. Simplify the agent prompt message chrome while leaving the default buffer window uncapped so cursor-anchored slash completion floats can expand normally; preserve modal and toolbar behavior.

**Tech Stack:** Python, prompt-toolkit, pytest.

---

### Task 1: Compact Prompt Input

**Files:**
- Modify: `src/pythinker_code/ui/shell/prompt.py`
- Modify: `tests/ui_and_conv/test_prompt_tips.py`

- [ ] **Step 1: Write failing tests**

Add tests asserting the default buffer window is not hard-capped and the agent prompt message renders a plain separator plus `› ` marker instead of the old titled input header.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/ui_and_conv/test_prompt_tips.py::test_prompt_buffer_window_is_limited_to_two_visible_rows tests/ui_and_conv/test_prompt_tips.py::test_idle_agent_prompt_uses_compact_separator_layout -q`

Expected: FAIL because the old `input` header is still rendered.

- [ ] **Step 3: Implement minimal prompt changes**

Render the compact separator and prompt marker in the agent prompt message. Do not set `Window.height.max=2`, because that clips the slash completion menu.

- [ ] **Step 4: Run targeted tests**

Run: `uv run pytest tests/ui_and_conv/test_prompt_tips.py::test_prompt_buffer_window_is_limited_to_two_visible_rows tests/ui_and_conv/test_prompt_tips.py::test_idle_agent_prompt_uses_compact_separator_layout tests/ui_and_conv/test_prompt_tips.py::test_running_prompt_uses_shared_toolbar_and_separator_layout tests/ui_and_conv/test_prompt_tips.py::test_modal_prompt_hides_normal_separator_and_prompt_label -q`

Expected: PASS.

- [ ] **Step 5: Run prompt test file**

Run: `uv run pytest tests/ui_and_conv/test_prompt_tips.py -q`

Expected: PASS.
