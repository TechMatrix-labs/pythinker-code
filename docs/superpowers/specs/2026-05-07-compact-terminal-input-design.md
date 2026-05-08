# Compact Terminal Input Design

## Summary

Update the shell input area to match the compact Claude-style layout supplied by the user. The input block should reserve two visible rows, use thin horizontal separators above and below the editable area, and keep the existing bottom status toolbar behavior.

## Goals

- Show a compact two-row input area instead of reserving a large prompt region.
- Use a `>`-style prompt marker visually aligned with the screenshot.
- Keep multiline editing, command handling, modals, and existing prompt-toolkit behaviors intact.
- Preserve the current shell architecture and avoid a broad terminal UI rewrite.

## Non-Goals

- Rebuild the shell UI around a new layout engine.
- Change agent event rendering, work-log cards, or interactive visualization behavior unrelated to the input area.
- Change permission, model, or branch semantics beyond their visual placement in the existing toolbar.

## Design

The implementation should make a focused change in `src/pythinker_code/ui/shell/prompt.py`:

- Render compact input chrome without hard-capping the prompt-toolkit buffer window, so cursor-anchored completion menus can still expand normally.
- Render thin separators around the input block, matching the screenshot's simple horizontal-rule treatment.
- Keep the editable prompt line minimal, with a left prompt marker and no heavy bordered panel.
- Leave the bottom toolbar as the source of status information, but style it to remain visually compatible with the compact input block.

The resulting layout should look like:

```text
────────────────────────────────────────
> user input

────────────────────────────────────────
model / effort / repo / branch / permission hint
```

## Behavior

- The visible input chrome stays compact and does not reserve the old large titled prompt area.
- Long or multiline input continues to use prompt-toolkit's existing editing behavior within the smaller visible region.
- Modal delegates still suppress the normal input chrome as they do today.
- Existing key bindings and prompt session configuration remain unchanged unless required for the two-row height.

## Testing

- Add or update focused shell prompt tests for the configured prompt height and rendered input chrome.
- Run the relevant `tests/ui_and_conv` tests that cover shell prompt/render behavior.
- Run a formatter/check command if practical; note any existing tooling blocker separately.

## Risks

- Prompt-toolkit sizing can differ slightly by terminal height, so tests should assert configuration/render intent rather than pixel-perfect terminal behavior.
- Hard-capping the prompt-toolkit input window can clip cursor-anchored slash completion menus, so the compact layout should be achieved through prompt chrome rather than a fixed buffer-window maximum.
