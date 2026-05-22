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
