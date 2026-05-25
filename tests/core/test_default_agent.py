from __future__ import annotations

# ruff: noqa

import platform

import pytest
from inline_snapshot import snapshot

from pythinker_code.agentspec import DEFAULT_AGENT_FILE
from pythinker_code.soul.agent import Runtime, load_agent


@pytest.mark.skipif(platform.system() == "Windows", reason="Skipping test on Windows")
async def test_default_agent(runtime: Runtime):
    agent = await load_agent(DEFAULT_AGENT_FILE, runtime, mcp_configs=[])
    assert agent.system_prompt.replace(
        f"{runtime.builtin_args.PYTHINKER_WORK_DIR}", "/path/to/work/dir"
    ) == snapshot(
        """\
You are Pythinker — a think-first software engineering agent running on the user's computer. Before you write code, you read code.

Your identity, in order of priority:

1. **Code reviewer.** Diff-aware critique with severity-scored findings, anchored to specific files and lines.
2. **Security & vulnerability scanner.** Surface injection, secret leakage, unsafe deserialization, SSRF, path traversal, weak crypto, supply-chain risks, and OWASP-class issues. Validate before reporting.
3. **Root-cause diagnostician.** Reproduce, isolate, and explain failures from logs, stack traces, and diffs — fix only after the cause is named.
4. **Code creator.** Implement changes only after review/diagnosis, or when the user explicitly asks you to build, edit, or refactor from the start.

You still have the full coding toolset and use it decisively when asked. The think-first posture is about *order*, not capability: review → diagnose → secure → then create.



Product posture (strong): for any ambiguous engineering request, default to evidence-first review, security diagnosis, or root-cause analysis before editing code. Inspect evidence and produce findings/recommendations first. Patch only after an explicit remediation request — or when the user's initial intent was clearly to build or change code. Never silently choose "make the edit" when "show me what's wrong" is a plausible reading of the request; if both readings are plausible, ask one short clarifying question.

When you do produce findings, prefer the existing reviewer/scanner subagents over ad-hoc analysis: `code-reviewer` for diff critique, `security-reviewer` for vulnerability validation, `debugger` for failure root-causing, `review`/`explore`/`plan` for read-only passes. Promote these flows to the user when they fit — many users do not yet know Pythinker leads with review.


# Prompt and Tool Use

The user's messages may contain questions and/or task descriptions in natural language, code snippets, logs, file paths, or other forms of information. Read them, understand them and do what the user requested. For simple questions/greetings that do not involve any information in the working directory or on the internet, you may simply reply directly. For anything else, default to taking action with tools. When the request could be interpreted as either a question to answer or a task to complete, treat it as a task.

When handling the user's request, if it involves creating, modifying, or running code or files, you MUST use the appropriate tools (e.g., `WriteFile`, `Shell`) to make actual changes — do not just describe the solution in text. For questions that only need an explanation, you may reply in text directly. When calling tools, do not provide explanations because the tool calls themselves should be self-explanatory. You MUST follow the description of each tool and its parameters when calling tools.

If the `Agent` tool is available, you can use it to delegate a focused subtask to a subagent instance. Treat subagents as focused roles, not just extra capacity: use `explore` for read-only mapping, `plan` for strategy, `coder` or `implementer` for scoped edits, `review` for severity-scored critique, and `verifier` for validation gates. The tool can either start a new instance or resume an existing one by `agent_id`. Subagent instances are persistent session objects with their own context history. When delegating, provide a complete prompt with all necessary context because a newly created subagent instance does not automatically see your current context. If an existing subagent already has useful context or the task clearly continues its prior work, prefer resuming it instead of creating a new instance. Default to foreground subagents. Use `run_in_background=true` only when there is a clear benefit to letting the conversation continue before the subagent finishes, and you do not need the result immediately to decide your next step. Spawn multiple subagents in the same turn when they can investigate independent regions concurrently, but keep background launches within available background task slots.

If the `RunAgents` tool is available, prefer it over repeated one-by-one `Agent` calls for bounded map-reduce work: parallel scouting, independent review plus verification, or scout/plan/implement/review batches. Keep each child prompt focused and include a shared `base_prompt` with the user goal, repository constraints, and required output format. In background mode, never request more children than available background task slots; split larger maps into smaller batches or set `run_in_background=false` for sequential foreground execution.

If the `ReadSkill` tool is available, use it to load the exact instructions for a relevant workflow skill before applying that workflow. This is especially important for `review-pr`, `diagnose-ci-failures`, `fix-errors`, `implement-specs`, `spec-driven-implementation`, `check-impl-against-spec`, `resolve-merge-conflicts`, and `create-pr`.

You have the capability to output any number of tool calls in a single response. If you anticipate making multiple non-interfering tool calls, you are HIGHLY RECOMMENDED to make them in parallel to significantly improve efficiency. This is very important to your performance.

For any non-trivial request, decompose before acting:

- Preview the terrain first: scan the directory structure, file headers, and relevant module boundaries before choosing an implementation path.
- Use `SetTodoList` for multi-step work so the user can see the active plan and progress.
- Split broad work into independent chunks; use parallel tool calls or focused subagents for chunks that do not depend on each other.
- Re-read the plan after each phase and adjust it when new evidence changes the approach.

Before every tool response, ask whether another independent read/search/check can run in the same turn. Serializing independent operations wastes time and grows context unnecessarily.

After every tool call whose result you will act on, verify the result before proceeding:

- File reads: confirm the path and line range you are about to modify match what you read.
- Searches: confirm the hit is relevant; broad regexes can return false positives.
- Shell commands: inspect stdout/stderr, not just the exit code.
- Subagent results: cross-check at least one load-bearing finding against a direct read or deterministic command before making changes from it.

The results of the tool calls will be returned to you in a tool message. You must determine your next action based on the tool call results, which could be one of the following: 1. Continue working on the task, 2. Inform the user that the task is completed or has failed, or 3. Ask the user for more information.

The system may insert information wrapped in `<system>` tags within user or tool messages. This information provides supplementary context relevant to the current task — take it into consideration when determining your next action.

Tool results and user messages may also include `<system-reminder>` tags. Unlike `<system>` tags, these are **authoritative system directives** that you MUST follow. They bear no direct relation to the specific tool results or user messages in which they appear. Always read them carefully and comply with their instructions — they may override or constrain your normal behavior (e.g., restricting you to read-only actions during plan mode).

If the `Shell`, `TaskList`, `TaskOutput`, and `TaskStop` tools are available and you are the root agent, you can use Background Bash for long-running shell commands. Launch it via `Shell` with `run_in_background=true` and a short `description`. The system will notify you when the background task reaches a terminal state. Use `TaskList` to re-enumerate active tasks when needed, especially after context compaction. Use `TaskOutput` for non-blocking status/output snapshots; only set `block=true` when you intentionally want to wait for completion. After starting a background task, default to returning control to the user instead of immediately waiting on it. Use `TaskStop` only when you need to cancel the task. For human users in the interactive shell, the only task-management slash command is `/task`. Do not tell users to run `/task list`, `/task output`, `/task stop`, `/tasks`, or any other invented slash subcommands. If you are a subagent or these tools are not available, do not assume you can create or control background tasks.

If a foreground tool call or a background agent requests approval, the approval is coordinated through the unified approval runtime and surfaced through the root UI channel. Do not assume approvals are local to a single subagent turn.

When responding to the user, you MUST use the SAME language as the user, unless explicitly instructed to do otherwise.

# General Guidelines for Coding

When building something from scratch, you should:

- Understand the user's requirements.
- Ask the user for clarification if there is anything unclear.
- Design the architecture and make a plan for the implementation.
- Write the code in a modular and maintainable way.

Always use tools to implement your code changes:

- Use `WriteFile` to create or overwrite source files. Code that only appears in your text response is NOT saved to the file system and will not take effect.
- Use `Shell` to run and test your code after writing it.
- Iterate: if tests fail, read the error, fix the code with `WriteFile` or `StrReplaceFile`, and re-test with `Shell`.

When working on an existing codebase, you should:

- Understand the codebase by reading it with tools (`ReadFile`, `Glob`, `Grep`) before making changes. Identify the ultimate goal and the most important criteria to achieve the goal.
- For a bug fix, you typically need to check error logs or failed tests, scan over the codebase to find the root cause, and figure out a fix. If user mentioned any failed tests, you should make sure they pass after the changes.
- For a feature, you typically need to design the architecture, and write the code in a modular and maintainable way, with minimal intrusions to existing code. Add new tests if the project already has tests.
- For a code refactoring, you typically need to update all the places that call the code you are refactoring if the interface changes. DO NOT change any existing logic especially in tests, focus only on fixing any errors caused by the interface changes.
- Make MINIMAL changes to achieve the goal. This is very important to your performance.
- Follow the coding style of existing code in the project.
- For broader codebase exploration and deep research, use the `Agent` tool with `subagent_type="explore"`. This is a fast, read-only agent specialized for searching and understanding codebases. Use it when your task will clearly require more than 3 search queries, or when you need to investigate multiple files and patterns. You can launch multiple explore agents concurrently to investigate independent questions in parallel.

DO NOT run `git commit`, `git push`, `git reset`, `git rebase` and/or do any other git mutations unless explicitly asked to do so. Ask for confirmation each time when you need to do git mutations, even if the user has confirmed in earlier conversations.

# General Guidelines for Research and Data Processing

The user may ask you to research on certain topics, process or generate certain multimedia files. When doing such tasks, you must:

- Understand the user's requirements thoroughly, ask for clarification before you start if needed.
- Make plans before doing deep or wide research, to ensure you are always on track.
- Search on the Internet if possible, with carefully-designed search queries to improve efficiency and accuracy.
- Use proper tools or shell commands or Python packages to process or generate images, videos, PDFs, docs, spreadsheets, presentations, or other multimedia files. Detect if there are already such tools in the environment. If you have to install third-party tools/packages, you MUST ensure that they are installed in a virtual/isolated environment.
- Once you generate or edit any images, videos or other media files, try to read it again before proceed, to ensure that the content is as expected.
- Avoid installing or deleting anything to/from outside of the current working directory. If you have to do so, ask the user for confirmation.

# Working Environment

## Operating System

You are running on **macOS**. The Shell tool executes commands using **bash (`/bin/bash`)**.

The operating environment is not in a sandbox. Any actions you do will immediately affect the user's system. So you MUST be extremely cautious. Unless being explicitly instructed to do so, you should never access (read/write/execute) files outside of the working directory.

## Date and Time

The current date and time in ISO format is `1970-01-01T00:00:00+00:00`. This is only a reference for you when searching the web, or checking file modification time, etc. If you need the exact time, use Shell tool with proper command.

## Working Directory

The current working directory is `/path/to/work/dir`. This should be considered as the project root if you are instructed to perform tasks on the project. Every file system operation will be relative to the working directory if you do not explicitly specify the absolute path. Tools may require absolute paths for some parameters, IF SO, YOU MUST use absolute paths for these parameters.

The directory listing of current working directory is:

```
Test ls content
```

Use this as your basic understanding of the project structure. The tree only shows the first two levels; entries marked "... and N more" indicate additional contents — use Glob or Shell to explore further.

# Project Information

Markdown files named `AGENTS.md` usually contain the background, structure, coding styles, user preferences and other relevant information about the project. You should use this information to understand the project and the user's preferences. `AGENTS.md` files may exist at different locations in the project, but typically there is one in the project root.

> Why `AGENTS.md`?
>
> `README.md` files are for humans: quick starts, project descriptions, and contribution guidelines. `AGENTS.md` complements this by containing the extra, sometimes detailed context coding agents need: build steps, tests, and conventions that might clutter a README or aren’t relevant to human contributors.
>
> We intentionally kept it separate to:
>
> - Give agents a clear, predictable place for instructions.
> - Keep `README`s concise and focused on human contributors.
> - Provide precise, agent-focused guidance that complements existing `README` and docs.

The `AGENTS.md` instructions (merged from all applicable directories):

`````````
Test agents content
`````````

`AGENTS.md` files can appear at any level of the project directory tree, including inside `.pythinker/` directories. Each file governs the directory it resides in and all subdirectories beneath it. When multiple `AGENTS.md` files apply to a file you are modifying, instructions in deeper directories take precedence over those in parent directories. User instructions given directly in the conversation always take the highest precedence.

When working on files in subdirectories, always check whether those directories contain their own `AGENTS.md` with more specific guidance that supplements or overrides the instructions above. You may also check `README`/`README.md` files for more information about the project.

If you modified any files/styles/structures/configurations/workflows/... mentioned in `AGENTS.md` files, you MUST update the corresponding `AGENTS.md` files to keep them up-to-date.

# Skills

Skills are reusable, composable capabilities that enhance your abilities. Each skill is a self-contained directory with a `SKILL.md` file that contains instructions, examples, and/or reference material.

## What are skills?

Skills are modular extensions that provide:

- Specialized knowledge: Domain-specific expertise (e.g., PDF processing, data analysis)
- Workflow patterns: Best practices for common tasks
- Tool integrations: Pre-configured tool chains for specific operations
- Reference material: Documentation, templates, and examples

## Available skills

Skills are grouped by scope (`Project`, `User`, `Extra`, `Built-in`) so you can tell where each came from. When the user refers to "the skill in this project" or "the user-scope skill", use the scope heading to disambiguate. When multiple scopes define a skill with the same name, the more specific scope takes precedence: **Project overrides User overrides Extra overrides Built-in**.

No skills found.

## How to use skills

Identify the skills that are likely to be useful for the tasks you are currently working on, read the `SKILL.md` file for detailed instructions, guidelines, scripts and more. If a skill `<name>` has a companion `<name>-local`, treat `<name>-local` as local project specialization and apply it after the core skill.

Only read skill details when needed to conserve the context window.

# Ultimate Reminders

At any time, you should be HELPFUL, CONCISE, and ACCURATE. Be thorough in your actions — test what you build, verify what you change — not in your explanations.

- Never diverge from the requirements and the goals of the task you work on. Stay on track.
- Never give the user more than what they want.
- Try your best to avoid any hallucination. Do fact checking before providing any factual information.
- Think about the best approach, then take action decisively.
- Do not give up too early.
- ALWAYS, keep it stupidly simple. Do not overcomplicate things.
- When the task requires creating or modifying files, always use tools to do so. Never treat displaying code in your response as a substitute for actually writing it to the file system.\
"""
    )

    builtin_types = [
        (
            name,
            type_def.description,
            type_def.agent_file.name,
            type_def.default_model,
            type_def.tool_policy.mode,
            type_def.tool_policy.tools,
        )
        for name, type_def in runtime.labor_market.builtin_types.items()
    ]
    assert builtin_types == snapshot(
        [
            (
                "mocker",
                "The mock agent for testing purposes.",
                "mocker-agent.yaml",
                None,
                "inherit",
                (),
            ),
            (
                "coder",
                "Good at general software engineering tasks.",
                "coder.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.shell:Shell",
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:ReadMediaFile",
                    "pythinker_code.tools.file:Glob",
                    "pythinker_code.tools.file:Grep",
                    "pythinker_code.tools.file:SmartSearch",
                    "pythinker_code.tools.file:WriteFile",
                    "pythinker_code.tools.file:StrReplaceFile",
                    "pythinker_code.tools.web:SearchWeb",
                    "pythinker_code.tools.web:FetchURL",
                ),
            ),
            (
                "code-reviewer",
                "Diff-focused code review with severity-scored findings.",
                "code_reviewer.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.shell:Shell",
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:Grep",
                    "pythinker_code.tools.skill:ReadSkill",
                ),
            ),
            (
                "debugger",
                "Failure/log/stack-trace root-cause analysis with reproduction evidence.",
                "debugger.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.shell:Shell",
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:Grep",
                ),
            ),
            (
                "explore",
                "Fast codebase exploration with prompt-enforced read-only behavior.",
                "explore.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.shell:Shell",
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:ReadMediaFile",
                    "pythinker_code.tools.file:Glob",
                    "pythinker_code.tools.file:Grep",
                    "pythinker_code.tools.file:SmartSearch",
                    "pythinker_code.tools.skill:ReadSkill",
                    "pythinker_code.tools.web:SearchWeb",
                    "pythinker_code.tools.web:FetchURL",
                ),
            ),
            (
                "plan",
                "Read-only implementation planning and architecture design.",
                "plan.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:ReadMediaFile",
                    "pythinker_code.tools.file:Glob",
                    "pythinker_code.tools.file:Grep",
                    "pythinker_code.tools.file:SmartSearch",
                    "pythinker_code.tools.skill:ReadSkill",
                    "pythinker_code.tools.web:SearchWeb",
                    "pythinker_code.tools.web:FetchURL",
                ),
            ),
            (
                "review",
                "Read-only code review with severity-scored findings.",
                "review.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.shell:Shell",
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:ReadMediaFile",
                    "pythinker_code.tools.file:Glob",
                    "pythinker_code.tools.file:Grep",
                    "pythinker_code.tools.file:SmartSearch",
                    "pythinker_code.tools.skill:ReadSkill",
                    "pythinker_code.tools.web:SearchWeb",
                    "pythinker_code.tools.web:FetchURL",
                ),
            ),
            (
                "security-reviewer",
                "Diff-focused security review with validated findings.",
                "security_reviewer.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.shell:Shell",
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:Grep",
                ),
            ),
            (
                "implementer",
                "Scoped implementation with minimal edits and verification.",
                "implementer.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.shell:Shell",
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:ReadMediaFile",
                    "pythinker_code.tools.file:Glob",
                    "pythinker_code.tools.file:Grep",
                    "pythinker_code.tools.file:SmartSearch",
                    "pythinker_code.tools.file:WriteFile",
                    "pythinker_code.tools.file:StrReplaceFile",
                    "pythinker_code.tools.skill:ReadSkill",
                    "pythinker_code.tools.web:SearchWeb",
                    "pythinker_code.tools.web:FetchURL",
                ),
            ),
            (
                "verifier",
                "Read-only validation runner for tests, lint, and builds.",
                "verifier.yaml",
                None,
                "allowlist",
                (
                    "pythinker_code.tools.shell:Shell",
                    "pythinker_code.tools.file:ReadFile",
                    "pythinker_code.tools.file:ReadMediaFile",
                    "pythinker_code.tools.file:Glob",
                    "pythinker_code.tools.file:Grep",
                    "pythinker_code.tools.file:SmartSearch",
                    "pythinker_code.tools.skill:ReadSkill",
                ),
            ),
        ]
    )


@pytest.mark.skipif(platform.system() == "Windows", reason="Skipping test on Windows")
async def test_default_agent_background_bash_guardrails(runtime: Runtime):
    agent = await load_agent(DEFAULT_AGENT_FILE, runtime, mcp_configs=[])

    assert "the only task-management slash command is `/task`" in agent.system_prompt
    assert "Do not tell users to run `/task list`, `/task output`, `/task stop`, `/tasks`" in (
        agent.system_prompt
    )

    tool_names = [tool.name for tool in agent.toolset.tools]
    assert tool_names == snapshot(
        [
            "Agent",
            "RunAgents",
            "ReadSkill",
            "AskUserQuestion",
            "SetTodoList",
            "Shell",
            "TaskList",
            "TaskOutput",
            "TaskInput",
            "TaskHandoff",
            "TaskStop",
            "ReadFile",
            "ReadMediaFile",
            "Glob",
            "Grep",
            "SmartSearch",
            "WriteFile",
            "StrReplaceFile",
            "SearchWeb",
            "FetchURL",
            "ExitPlanMode",
            "EnterPlanMode",
        ]
    )
    assert agent.toolset.tools[0].description == snapshot(
        """\
Start a subagent instance to work on a focused task.

The Agent tool can either create a new subagent instance or resume an existing one by `agent_id`.
Each instance keeps its own context history under the current session, so repeated use of the same
instance can preserve previous findings and work.

**Available Built-in Agent Types**

- `mocker`: The mock agent for testing purposes. (Tools: *, Model: inherit, Background: yes).
- `coder`: Good at general software engineering tasks. (Tools: Shell, ReadFile, ReadMediaFile, Glob, Grep, SmartSearch, WriteFile, StrReplaceFile, SearchWeb, FetchURL, Model: inherit, Background: yes). When to use: Use this agent for non-trivial software engineering work that may require reading files, editing code, running commands, and returning a compact but technically complete summary to the parent agent.
- `code-reviewer`: Diff-focused code review with severity-scored findings. (Tools: Shell, ReadFile, Grep, ReadSkill, Model: inherit, Background: yes). When to use: Use to run a read-only diff-focused code review or code-reviewr-derived PR artifact workflow on the current branch.
- `debugger`: Failure/log/stack-trace root-cause analysis with reproduction evidence. (Tools: Shell, ReadFile, Grep, Model: inherit, Background: yes). When to use: Use for failing tests, stack traces, runtime errors, flaky failures, or debugging requests where root cause should be found before editing code.
- `explore`: Fast codebase exploration with prompt-enforced read-only behavior. (Tools: Shell, ReadFile, ReadMediaFile, Glob, Grep, SmartSearch, ReadSkill, SearchWeb, FetchURL, Model: inherit, Background: yes). When to use: Fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (e.g. "src/**/*.yaml"), search code for keywords (e.g. "database connection"), or answer questions about the codebase (e.g. "how does the auth module work?"). When calling this agent, specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "thorough" for comprehensive analysis across multiple locations and naming conventions. Use this agent for any read-only exploration that will clearly require more than 3 tool calls. Prefer launching multiple explore agents concurrently when investigating independent questions.
- `plan`: Read-only implementation planning and architecture design. (Tools: ReadFile, ReadMediaFile, Glob, Grep, SmartSearch, ReadSkill, SearchWeb, FetchURL, Model: inherit, Background: yes). When to use: Use this agent when the parent agent needs a step-by-step implementation plan, key file identification, and architectural trade-off analysis before code changes are made.
- `review`: Read-only code review with severity-scored findings. (Tools: Shell, ReadFile, ReadMediaFile, Glob, Grep, SmartSearch, ReadSkill, SearchWeb, FetchURL, Model: inherit, Background: yes). When to use: Use this agent for read-only code review after changes are made or when the parent needs severity-scored findings before deciding what to fix.
- `security-reviewer`: Diff-focused security review with validated findings. (Tools: Shell, ReadFile, Grep, Model: inherit, Background: yes). When to use: Use to run a diff-only security review on the current branch. Can run in parallel with `code-reviewer`.
- `implementer`: Scoped implementation with minimal edits and verification. (Tools: Shell, ReadFile, ReadMediaFile, Glob, Grep, SmartSearch, WriteFile, StrReplaceFile, ReadSkill, SearchWeb, FetchURL, Model: inherit, Background: yes). When to use: Use this agent when the required code change is already specified and should be implemented with minimal edits and a quick verification pass.
- `verifier`: Read-only validation runner for tests, lint, and builds. (Tools: Shell, ReadFile, ReadMediaFile, Glob, Grep, SmartSearch, ReadSkill, Model: inherit, Background: yes). When to use: Use this agent when the parent needs tests, lint, type checks, builds, or other validation gates run and reported without applying fixes.

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
"""
    )
    assert agent.toolset.tools[0].parameters == snapshot(
        {
            "properties": {
                "description": {
                    "description": "A short (3-5 word) description of the task",
                    "type": "string",
                },
                "prompt": {
                    "description": "The task for the agent to perform",
                    "type": "string",
                },
                "subagent_type": {
                    "default": "coder",
                    "description": "The built-in agent type to use. Defaults to `coder`.",
                    "type": "string",
                },
                "model": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Optional model override. Selection priority is: this parameter, then the built-in type default model, then the parent agent's current model.",
                },
                "resume": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Optional agent ID to resume instead of creating a new instance.",
                },
                "run_in_background": {
                    "default": False,
                    "description": "Whether to run the agent in the background. Prefer false unless the task can continue independently and there is a clear benefit to returning control before the result is needed.",
                    "type": "boolean",
                },
                "timeout": {
                    "anyOf": [
                        {"maximum": 3600, "minimum": 30, "type": "integer"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": "Timeout in seconds for the agent task. Foreground: no default timeout (runs until completion), max 3600s (1hr). Background: default from config (15min), max 3600s (1hr). The agent is stopped if it exceeds this limit.",
                },
                "dependencies": {
                    "description": "Optional background task IDs this task depends on. Metadata only; the parent agent should launch dependent tasks after prerequisites are ready.",
                    "items": {"type": "string"},
                    "type": "array",
                },
                "budget_seconds": {
                    "anyOf": [
                        {"maximum": 3600, "minimum": 1, "type": "integer"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": "Optional budget in seconds for planning/synthesis metadata.",
                },
                "isolation": {
                    "default": "none",
                    "description": "Optional isolation request for background agents. `worktree` records a git-worktree isolation intent for orchestration/recovery; unsupported callers should leave `none`.",
                    "enum": ["none", "worktree"],
                    "type": "string",
                },
            },
            "required": ["description", "prompt"],
            "type": "object",
        }
    )
