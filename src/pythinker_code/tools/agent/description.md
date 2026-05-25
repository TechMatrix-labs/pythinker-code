Start a subagent instance to work on a focused task.

The Agent tool can either create a new subagent instance or resume an existing one by `agent_id`.
Each instance keeps its own context history under the current session, so repeated use of the same
instance can preserve previous findings and work.

**Available Built-in Agent Types**

${BUILTIN_AGENT_TYPES_MD}

**Usage**

- Always provide a short `description` (3-5 words).
- Use `subagent_type` to select a built-in agent type. If omitted, `coder` is used.
- Use `model` when you need to override the built-in type's default model or the parent agent's current model.
- Use `resume` when you want to continue an existing instance instead of starting a new one.
- If an existing subagent already has relevant context or the task is a continuation of its prior work, prefer `resume` over creating a new instance.
- Default to foreground execution. Use `run_in_background=true` only when the task can continue independently, you do not need the result immediately, and there is a clear benefit to returning control before it finishes.
- Be explicit about whether the subagent should write code, only research, review, or verify.
- Provide the subagent all required context and success criteria. New subagents do not inherit your transcript automatically.
- Brief the agent like a capable teammate joining mid-task: state the goal, why it matters, what you already learned or ruled out, exact paths/commands when known, and the output format you need.
- Do not delegate synthesis with vague prompts such as "based on your findings, fix it". First understand the finding yourself, then give the subagent a concrete scoped task.
- Spawn multiple subagents in the same turn when they can investigate independent regions concurrently, but keep background launches within available task slots.
- Cross-check at least one load-bearing subagent finding before making changes from it.
- The subagent result is only visible to you. If the user should see it, summarize it yourself.

**Agent Workflow Design**

Use subagents as focused logical roles, not just extra tool capacity:

- `explore` / scout: collect facts, relevant files, constraints, and risks. Read-only.
- `plan`: turn gathered context into an implementation plan. Read-only.
- `coder`: general software engineering work when the brief still needs judgment.
- `implementer`: land a specific, already-scoped change with minimum edits.
- `review`: read and grade changed code with severity-scored findings.
- `verifier`: run validation gates and report PASS / FAIL / FLAKY without fixing.

Recommended workflows:

- Scout → Plan → Implement: run `explore`, then `plan` with the explorer's findings, then `implementer` or `coder` with the plan.
- Implement → Review → Fix → Verify: run `implementer`, then `review`, then resume/launch `implementer` to apply feedback, then `verifier` for the relevant gate.
- Parallel scouting: launch multiple `explore` agents for independent questions, then synthesize their findings before editing. If running them in the background, split batches that would exceed available background task slots.
- Parallel review/verification: when review and tests do not depend on each other, run `review` and `verifier` concurrently.

When chaining manually, include the previous agent's summary in the next agent prompt. Newly-created
subagents do not see your current context automatically.

**Explore Agent — Preferred for Codebase Research**

When you need to understand the codebase before making changes, fixing bugs, or planning features,
prefer `subagent_type="explore"` over doing the search yourself. The explore agent is optimized for
fast, read-only codebase investigation. Use it when:
- Your task will clearly require more than 3 search queries
- You need to understand how a module, feature, or code path works
- You are about to enter plan mode and want to gather context first
- You want to investigate multiple independent questions — launch multiple explore agents concurrently

When calling explore, specify the desired thoroughness in the prompt:
- "quick": targeted lookups — find a specific file, function, or config value
- "medium": understand a module — how does auth work, what calls this API
- "thorough": cross-cutting analysis — architecture overview, dependency mapping, multi-module investigation

**When Not To Use Agent**

- Reading a known file path
- Searching a small number of known files
- Tasks that can be completed in one or two direct tool calls
