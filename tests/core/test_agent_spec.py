from __future__ import annotations

import re
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from inline_snapshot import snapshot

from pythinker_code.agentspec import DEFAULT_AGENT_FILE, load_agent_spec
from pythinker_code.exception import AgentSpecError


def test_load_default_agent_spec():
    """Test loading the default agent specification."""
    spec = load_agent_spec(DEFAULT_AGENT_FILE)

    assert spec.name == snapshot("")
    assert spec.system_prompt_path == DEFAULT_AGENT_FILE.parent / "system.md"
    assert spec.system_prompt_args == snapshot({"ROLE_ADDITIONAL": ""})
    assert spec.when_to_use == snapshot("")
    assert spec.model == snapshot(None)
    assert spec.allowed_tools == snapshot(None)
    assert spec.exclude_tools == snapshot([])
    assert spec.tools == snapshot(
        [
            "pythinker_code.tools.agent:Agent",
            "pythinker_code.tools.agent:RunAgents",
            "pythinker_code.tools.skill:ReadSkill",
            "pythinker_code.tools.ask_user:AskUserQuestion",
            "pythinker_code.tools.todo:SetTodoList",
            "pythinker_code.tools.memory:Memory",
            "pythinker_code.tools.scratchpad:Scratchpad",
            "pythinker_code.tools.shell:Shell",
            "pythinker_code.tools.background:TaskList",
            "pythinker_code.tools.background:TaskOutput",
            "pythinker_code.tools.background:TaskInput",
            "pythinker_code.tools.background:TaskHandoff",
            "pythinker_code.tools.background:TaskStop",
            "pythinker_code.tools.file:ReadFile",
            "pythinker_code.tools.file:ReadMediaFile",
            "pythinker_code.tools.file:Glob",
            "pythinker_code.tools.file:Grep",
            "pythinker_code.tools.file:SmartSearch",
            "pythinker_code.tools.file:WriteFile",
            "pythinker_code.tools.file:StrReplaceFile",
            "pythinker_code.tools.web:SearchWeb",
            "pythinker_code.tools.web:FetchURL",
            "pythinker_code.tools.plan:ExitPlanMode",
            "pythinker_code.tools.plan.enter:EnterPlanMode",
        ]
    )
    subagents = {
        name: (spec.path.relative_to(DEFAULT_AGENT_FILE.parent).as_posix(), spec.description)
        for name, spec in spec.subagents.items()
    }
    assert subagents == snapshot(
        {
            "coder": ("coder.yaml", "Good at general software engineering tasks."),
            "code-reviewer": (
                "code_reviewer.yaml",
                "Diff-focused code review with severity-scored findings.",
            ),
            "debugger": (
                "debugger.yaml",
                "Failure/log/stack-trace root-cause analysis with reproduction evidence.",
            ),
            "explore": (
                "explore.yaml",
                "Fast codebase exploration with prompt-enforced read-only behavior.",
            ),
            "plan": ("plan.yaml", "Read-only implementation planning and architecture design."),
            "review": ("review.yaml", "Read-only code review with severity-scored findings."),
            "security-reviewer": (
                "security_reviewer.yaml",
                "Diff-focused security review with validated findings.",
            ),
            "implementer": (
                "implementer.yaml",
                "Scoped implementation with minimal edits and verification.",
            ),
            "verifier": (
                "verifier.yaml",
                "Read-only validation runner for tests, lint, and builds.",
            ),
        }
    )

    subagent_specs = {name: load_agent_spec(spec.path) for name, spec in spec.subagents.items()}

    assert subagent_specs["coder"].name == snapshot("")
    assert subagent_specs["coder"].system_prompt_path == DEFAULT_AGENT_FILE.parent / "system.md"
    assert subagent_specs["coder"].system_prompt_args == snapshot(
        {
            "ROLE_ADDITIONAL": """\
You are now running as a subagent. All the `user` messages are sent by the main agent. The main agent cannot see your context, it can only see your last message when you finish the task. You must treat the parent agent as your caller. Do not directly ask the end user questions. If something is unclear, explain the ambiguity in your final summary to the parent agent.

Stay tightly scoped to exactly what the parent assigned. Do not expand into adjacent cleanup or refactors. If you discover related work, surface it under RISKS or BLOCKERS rather than doing it.

Context gate before editing:
- Confirm the parent provided a clear goal, scope, constraints, and acceptance criteria. If not, inspect the code enough to infer them or report BLOCKERS.
- Read target files, nearby patterns, and relevant tests before writing. Do not edit code you cannot explain.
- Prefer the minimum implementation that satisfies the brief; no speculative abstractions or broad formatting churn.

Implementation method:
- Before editing, read the target files and confirm the line ranges/patterns you will change.
- Prefer StrReplaceFile for narrow changes; use WriteFile only for new files or intentional full rewrites.
- Add or update tests when the brief requires behavior changes and the project has relevant tests.
- After edits, inspect the diff/changed files for scope creep, TODOs/placeholders, import mistakes, and logic mismatches.
- Run the smallest relevant verification command available and report the result. If verification cannot run, explain the blocker.

Final response contract:
### SUMMARY
One paragraph with what you did and the outcome.
### EVIDENCE
Bullet list of concrete file paths, command results, diff inspection, or observed errors that support the outcome.
### CHANGES
Bullet list of every file you modified, or `None.` if read-only.
### RISKS
Bullet list of remaining risks or `None observed.`.
### BLOCKERS
Bullet list of anything that stopped completion, or `None.`.
"""  # noqa: E501
        }
    )
    assert subagent_specs["coder"].when_to_use == snapshot(
        "Use this agent for non-trivial software engineering work that may require reading files, editing code, running commands, and returning a compact but technically complete summary to the parent agent.\n"
    )
    assert subagent_specs["coder"].model == snapshot(None)
    assert subagent_specs["coder"].allowed_tools == snapshot(
        [
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
        ]
    )
    assert subagent_specs["coder"].exclude_tools == snapshot(
        [
            "pythinker_code.tools.agent:Agent",
            "pythinker_code.tools.ask_user:AskUserQuestion",
            "pythinker_code.tools.todo:SetTodoList",
            "pythinker_code.tools.plan:ExitPlanMode",
            "pythinker_code.tools.plan.enter:EnterPlanMode",
        ]
    )
    assert subagent_specs["coder"].tools == snapshot(
        [
            "pythinker_code.tools.agent:Agent",
            "pythinker_code.tools.agent:RunAgents",
            "pythinker_code.tools.skill:ReadSkill",
            "pythinker_code.tools.ask_user:AskUserQuestion",
            "pythinker_code.tools.todo:SetTodoList",
            "pythinker_code.tools.memory:Memory",
            "pythinker_code.tools.scratchpad:Scratchpad",
            "pythinker_code.tools.shell:Shell",
            "pythinker_code.tools.background:TaskList",
            "pythinker_code.tools.background:TaskOutput",
            "pythinker_code.tools.background:TaskInput",
            "pythinker_code.tools.background:TaskHandoff",
            "pythinker_code.tools.background:TaskStop",
            "pythinker_code.tools.file:ReadFile",
            "pythinker_code.tools.file:ReadMediaFile",
            "pythinker_code.tools.file:Glob",
            "pythinker_code.tools.file:Grep",
            "pythinker_code.tools.file:SmartSearch",
            "pythinker_code.tools.file:WriteFile",
            "pythinker_code.tools.file:StrReplaceFile",
            "pythinker_code.tools.web:SearchWeb",
            "pythinker_code.tools.web:FetchURL",
            "pythinker_code.tools.plan:ExitPlanMode",
            "pythinker_code.tools.plan.enter:EnterPlanMode",
        ]
    )
    sub_subagents = {
        name: (spec.path.relative_to(DEFAULT_AGENT_FILE.parent).as_posix(), spec.description)
        for name, spec in subagent_specs["coder"].subagents.items()
    }
    assert sub_subagents == snapshot({})

    assert subagent_specs["explore"].name == snapshot("")
    assert subagent_specs["explore"].system_prompt_path == DEFAULT_AGENT_FILE.parent / "system.md"
    assert subagent_specs["explore"].system_prompt_args == snapshot(
        {
            "ROLE_ADDITIONAL": """\
You are now running as a subagent. All the `user` messages are sent by the main agent. The main agent cannot see your context, it can only see your last message when you finish the task. You must treat the parent agent as your caller. Do not directly ask the end user questions. If something is unclear, explain the ambiguity in your final summary to the parent agent.

You are a codebase exploration specialist. Your role is EXCLUSIVELY to search, read, and analyze existing code and resources. You do NOT have access to file editing tools. If the task appears to require a write, stop and put the gap under BLOCKERS.

Context packet requirements:
- Collect the smallest evidence set that can support the parent's decision: relevant files, symbols, callers/callees, tests, docs, commands, config, and existing patterns.
- Do not provide architecture judgment, root-cause claims, implementation recommendations, or risk assessment unless the evidence is cited.
- Distinguish CONFIRMED facts from LIKELY inferences. Put unknowns and missing evidence under RISKS or BLOCKERS.
- Prefer path:line-range citations for load-bearing findings. Search broadly enough to avoid a false map, then stop when the parent has enough context.

Your strengths:
- Rapidly finding files using glob patterns
- Searching code and text with powerful regex patterns
- Reading and analyzing file contents
- Running read-only shell commands (git log, git diff, ls, find, etc.)

Guidelines:
- Use Glob for broad file pattern matching
- Use Grep for searching file contents with regex
- Use ReadFile when you know the specific file path
- Use Shell ONLY for read-only operations (ls, git status, git log, git diff, find)
- NEVER use Shell for any file creation or modification commands
- Adapt your search depth based on the thoroughness level specified by the caller
- Wherever possible, spawn multiple parallel tool calls for grepping and reading files to maximize speed
- When running lint or complexity checks (e.g. ruff, flake8), always run with the project's configured rule set first (no extra `--select` flags). If you run supplemental checks that add rules not in the project config (e.g. `--select C901` when C901 is absent from pyproject.toml), you MUST label those findings explicitly as "outside project lint policy — not an enforced violation" so the caller can distinguish real project violations from advisory findings.

If the prompt includes a <git-context> block, use it to orient yourself about the repository state before starting your investigation.

You are meant to be a fast agent. Complete the search request efficiently and report your findings clearly in a structured format. EVIDENCE is the load-bearing section: cite each important finding as `path:line-range` when possible, and stop once you have enough evidence rather than exhaustively reading the whole repository.

Final response contract:
### SUMMARY
One paragraph with the headline answer.
### CONTEXT PACKET
Bullets for goal, relevant files/symbols, existing patterns, tests/docs, and unknowns.
### EVIDENCE
Bullet list of concrete file paths, line ranges, search hits, and command results.
### CHANGES
Always write `None.`.
### RISKS
Bullet list of uncertainties or `None observed.`.
### BLOCKERS
Bullet list of missing context/capabilities or `None.`.
"""  # noqa: E501
        }
    )
    assert subagent_specs["explore"].when_to_use == snapshot(
        'Fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (e.g. "src/**/*.yaml"), search code for keywords (e.g. "database connection"), or answer questions about the codebase (e.g. "how does the auth module work?"). When calling this agent, specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "thorough" for comprehensive analysis across multiple locations and naming conventions. Use this agent for any read-only exploration that will clearly require more than 3 tool calls. Prefer launching multiple explore agents concurrently when investigating independent questions.\n'
    )
    assert subagent_specs["explore"].model == snapshot(None)
    assert subagent_specs["explore"].allowed_tools == snapshot(
        [
            "pythinker_code.tools.shell:Shell",
            "pythinker_code.tools.file:ReadFile",
            "pythinker_code.tools.file:ReadMediaFile",
            "pythinker_code.tools.file:Glob",
            "pythinker_code.tools.file:Grep",
            "pythinker_code.tools.file:SmartSearch",
            "pythinker_code.tools.skill:ReadSkill",
            "pythinker_code.tools.web:SearchWeb",
            "pythinker_code.tools.web:FetchURL",
        ]
    )
    assert subagent_specs["explore"].exclude_tools == snapshot(
        [
            "pythinker_code.tools.agent:Agent",
            "pythinker_code.tools.ask_user:AskUserQuestion",
            "pythinker_code.tools.todo:SetTodoList",
            "pythinker_code.tools.plan:ExitPlanMode",
            "pythinker_code.tools.plan.enter:EnterPlanMode",
            "pythinker_code.tools.file:WriteFile",
            "pythinker_code.tools.file:StrReplaceFile",
        ]
    )
    assert subagent_specs["explore"].tools == snapshot(
        [
            "pythinker_code.tools.agent:Agent",
            "pythinker_code.tools.agent:RunAgents",
            "pythinker_code.tools.skill:ReadSkill",
            "pythinker_code.tools.ask_user:AskUserQuestion",
            "pythinker_code.tools.todo:SetTodoList",
            "pythinker_code.tools.memory:Memory",
            "pythinker_code.tools.scratchpad:Scratchpad",
            "pythinker_code.tools.shell:Shell",
            "pythinker_code.tools.background:TaskList",
            "pythinker_code.tools.background:TaskOutput",
            "pythinker_code.tools.background:TaskInput",
            "pythinker_code.tools.background:TaskHandoff",
            "pythinker_code.tools.background:TaskStop",
            "pythinker_code.tools.file:ReadFile",
            "pythinker_code.tools.file:ReadMediaFile",
            "pythinker_code.tools.file:Glob",
            "pythinker_code.tools.file:Grep",
            "pythinker_code.tools.file:SmartSearch",
            "pythinker_code.tools.file:WriteFile",
            "pythinker_code.tools.file:StrReplaceFile",
            "pythinker_code.tools.web:SearchWeb",
            "pythinker_code.tools.web:FetchURL",
            "pythinker_code.tools.plan:ExitPlanMode",
            "pythinker_code.tools.plan.enter:EnterPlanMode",
        ]
    )
    sub_subagents = {
        name: (spec.path.relative_to(DEFAULT_AGENT_FILE.parent).as_posix(), spec.description)
        for name, spec in subagent_specs["explore"].subagents.items()
    }
    assert sub_subagents == snapshot({})

    assert subagent_specs["plan"].name == snapshot("")
    assert subagent_specs["plan"].system_prompt_path == DEFAULT_AGENT_FILE.parent / "system.md"
    assert subagent_specs["plan"].system_prompt_args == snapshot(
        {
            "ROLE_ADDITIONAL": """\
You are now running as a subagent. All the `user` messages are sent by the main agent. The main agent cannot see your context, it can only see your last message when you finish the task. You must treat the parent agent as your caller. Do not directly ask the end user questions. If something is unclear, explain the ambiguity in your final summary to the parent agent.

You are a read-only planning and architecture specialist. Your output must be an evidence-backed execution plan, not a guess.

Context gate:
- Before designing a plan, build a context packet from repository evidence, docs, tests, existing patterns, and the user's stated goal.
- If the relevant codebase area is not understood, do not invent a plan. Recommend concrete `explore` questions for the parent agent to run first.
- State assumptions explicitly and separate them from confirmed evidence.
- Before proposing a fix for any lint or complexity violation, verify the rule is in the project's active rule set (e.g. `select` in pyproject.toml or .ruff.toml). Findings that only appear via an explicit `--select <rule>` flag not present in the project config are NOT project violations; do not include them in the plan unless the user explicitly asked to enforce that rule.

Plan requirements:
- Include a User Request Summary and the success criteria you optimized for.
- Identify likely files/modules and why they are in scope.
- Provide a Task Dependency Graph: each task, what it depends on, and the reason.
- Provide a Parallel Execution Graph: which tasks can run together, which must be sequential, and the critical path.
- For every task, include artifacts to change, acceptance criteria, suggested specialist (`explore`, `implementer`, `review`, `security-reviewer`, `debugger`, `verifier`), and the smallest verification command/check.
- Call out risks, blockers, migration/backward-compatibility concerns, and test gaps.

Ground the plan in evidence. Read enough files to avoid guessing, name the trade-offs, and choose one path with a reason. Each step should name the artifact it changes and the verification that proves it worked. Order steps by dependency first, then by risk reduced per effort.

Final response contract:
### SUMMARY
One paragraph with the recommended plan and why.
### CONTEXT
User request summary, confirmed context, assumptions, and unknowns.
### TASK DEPENDENCY GRAPH
Table or bullets showing task dependencies and reasons.
### PARALLEL EXECUTION GRAPH
Execution waves, critical path, and what can/cannot run concurrently.
### PLAN
Numbered tasks with artifacts, acceptance criteria, specialist recommendation, and verification.
### EVIDENCE
Bullet list of concrete file paths, line ranges, docs, or search hits that shaped the plan.
### CHANGES
Always write `None.` unless you wrote a plan artifact.
### RISKS
Bullet list of trade-offs, unknowns, or rollout risks.
### BLOCKERS
Bullet list of questions that must be answered before execution, or `None.`.
"""  # noqa: E501
        }
    )
    assert subagent_specs["plan"].when_to_use == snapshot(
        "Use this agent when the parent agent needs a step-by-step implementation plan, key file identification, and architectural trade-off analysis before code changes are made.\n"
    )
    assert subagent_specs["plan"].model == snapshot(None)
    assert subagent_specs["plan"].allowed_tools == snapshot(
        [
            "pythinker_code.tools.file:ReadFile",
            "pythinker_code.tools.file:ReadMediaFile",
            "pythinker_code.tools.file:Glob",
            "pythinker_code.tools.file:Grep",
            "pythinker_code.tools.file:SmartSearch",
            "pythinker_code.tools.skill:ReadSkill",
            "pythinker_code.tools.web:SearchWeb",
            "pythinker_code.tools.web:FetchURL",
        ]
    )
    assert subagent_specs["plan"].exclude_tools == snapshot(
        [
            "pythinker_code.tools.agent:Agent",
            "pythinker_code.tools.ask_user:AskUserQuestion",
            "pythinker_code.tools.todo:SetTodoList",
            "pythinker_code.tools.plan:ExitPlanMode",
            "pythinker_code.tools.plan.enter:EnterPlanMode",
            "pythinker_code.tools.shell:Shell",
            "pythinker_code.tools.file:WriteFile",
            "pythinker_code.tools.file:StrReplaceFile",
        ]
    )
    assert subagent_specs["plan"].tools == snapshot(
        [
            "pythinker_code.tools.agent:Agent",
            "pythinker_code.tools.agent:RunAgents",
            "pythinker_code.tools.skill:ReadSkill",
            "pythinker_code.tools.ask_user:AskUserQuestion",
            "pythinker_code.tools.todo:SetTodoList",
            "pythinker_code.tools.memory:Memory",
            "pythinker_code.tools.scratchpad:Scratchpad",
            "pythinker_code.tools.shell:Shell",
            "pythinker_code.tools.background:TaskList",
            "pythinker_code.tools.background:TaskOutput",
            "pythinker_code.tools.background:TaskInput",
            "pythinker_code.tools.background:TaskHandoff",
            "pythinker_code.tools.background:TaskStop",
            "pythinker_code.tools.file:ReadFile",
            "pythinker_code.tools.file:ReadMediaFile",
            "pythinker_code.tools.file:Glob",
            "pythinker_code.tools.file:Grep",
            "pythinker_code.tools.file:SmartSearch",
            "pythinker_code.tools.file:WriteFile",
            "pythinker_code.tools.file:StrReplaceFile",
            "pythinker_code.tools.web:SearchWeb",
            "pythinker_code.tools.web:FetchURL",
            "pythinker_code.tools.plan:ExitPlanMode",
            "pythinker_code.tools.plan.enter:EnterPlanMode",
        ]
    )
    sub_subagents = {
        name: (spec.path.relative_to(DEFAULT_AGENT_FILE.parent).as_posix(), spec.description)
        for name, spec in subagent_specs["plan"].subagents.items()
    }
    assert sub_subagents == snapshot({})


def test_load_agent_spec_basic(agent_file: Path):
    """Test loading a basic agent specification."""
    spec = load_agent_spec(agent_file)

    assert spec.name == snapshot("Test Agent")
    assert spec.system_prompt_path == agent_file.parent / "system.md"
    assert spec.tools == snapshot(["pythinker_code.tools.think:Think"])


def test_load_agent_spec_missing_name(agent_file_no_name: Path):
    """Test missing agent name raises AgentSpecError."""
    with pytest.raises(AgentSpecError, match="Agent name is required"):
        load_agent_spec(agent_file_no_name)


def test_load_agent_spec_missing_system_prompt(agent_file_no_prompt: Path):
    """Test missing system prompt path raises AgentSpecError."""
    with pytest.raises(AgentSpecError, match="System prompt path is required"):
        load_agent_spec(agent_file_no_prompt)


def test_load_agent_spec_missing_tools(agent_file_no_tools: Path):
    """Test missing tools raises AgentSpecError."""
    with pytest.raises(AgentSpecError, match="Tools are required"):
        load_agent_spec(agent_file_no_tools)


def test_load_agent_spec_with_exclude_tools(agent_file_with_tools: Path):
    """Test loading agent spec with excluded tools."""
    spec = load_agent_spec(agent_file_with_tools)

    assert spec.tools == snapshot(
        ["pythinker_code.tools.think:Think", "pythinker_code.tools.shell:Shell"]
    )
    assert spec.exclude_tools == snapshot(["pythinker_code.tools.shell:Shell"])


def test_load_agent_spec_extension(agent_file_extending: Path):
    """Test loading agent spec with extension."""
    spec = load_agent_spec(agent_file_extending)

    assert spec.name == snapshot("Extended Agent")
    assert spec.tools == snapshot(["pythinker_code.tools.think:Think"])


def test_load_agent_spec_default_extension():
    """Test loading agent spec with default extension."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create extending agent
        extending_agent = tmpdir / "extending.yaml"
        extending_agent.write_text("""
version: 1
agent:
  extend: default
  system_prompt_args:
    CUSTOM_ARG: "custom_value"
  exclude_tools:
    - "pythinker_code.tools.web:SearchWeb"
    - "pythinker_code.tools.web:FetchURL"
""")

        spec = load_agent_spec(extending_agent)

        assert spec.name == snapshot("")
        assert spec.system_prompt_path == DEFAULT_AGENT_FILE.parent / "system.md"
        assert spec.system_prompt_args == snapshot(
            {"ROLE_ADDITIONAL": "", "CUSTOM_ARG": "custom_value"}
        )
        assert spec.tools == snapshot(
            [
                "pythinker_code.tools.agent:Agent",
                "pythinker_code.tools.agent:RunAgents",
                "pythinker_code.tools.skill:ReadSkill",
                "pythinker_code.tools.ask_user:AskUserQuestion",
                "pythinker_code.tools.todo:SetTodoList",
                "pythinker_code.tools.memory:Memory",
                "pythinker_code.tools.scratchpad:Scratchpad",
                "pythinker_code.tools.shell:Shell",
                "pythinker_code.tools.background:TaskList",
                "pythinker_code.tools.background:TaskOutput",
                "pythinker_code.tools.background:TaskInput",
                "pythinker_code.tools.background:TaskHandoff",
                "pythinker_code.tools.background:TaskStop",
                "pythinker_code.tools.file:ReadFile",
                "pythinker_code.tools.file:ReadMediaFile",
                "pythinker_code.tools.file:Glob",
                "pythinker_code.tools.file:Grep",
                "pythinker_code.tools.file:SmartSearch",
                "pythinker_code.tools.file:WriteFile",
                "pythinker_code.tools.file:StrReplaceFile",
                "pythinker_code.tools.web:SearchWeb",
                "pythinker_code.tools.web:FetchURL",
                "pythinker_code.tools.plan:ExitPlanMode",
                "pythinker_code.tools.plan.enter:EnterPlanMode",
            ]
        )
        assert spec.exclude_tools == snapshot(
            ["pythinker_code.tools.web:SearchWeb", "pythinker_code.tools.web:FetchURL"]
        )
        assert "coder" in spec.subagents


def test_load_agent_spec_unsupported_version():
    """Test loading agent spec with unsupported version raises ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        agent_yaml = tmpdir / "agent.yaml"
        agent_yaml.write_text("""
version: 2
agent:
  name: "Test Agent"
  system_prompt_path: ./system.md
  tools: ["pythinker_code.tools.think:Think"]
""")

        with pytest.raises(AgentSpecError, match="Unsupported agent spec version: 2"):
            load_agent_spec(agent_yaml)


def test_load_agent_spec_nonexistent_file():
    """Test loading nonexistent agent spec file raises AssertionError."""
    nonexistent = Path("/nonexistent/agent.yaml")
    with pytest.raises(
        AgentSpecError,
        match=re.compile(r"Agent spec file not found: [\\/]nonexistent[\\/]agent.yaml"),
    ):
        load_agent_spec(nonexistent)


def test_load_agent_spec_empty_yaml_raises_agent_spec_error(tmp_path: Path):
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text("")

    with pytest.raises(AgentSpecError, match="Agent spec file must contain a mapping"):
        load_agent_spec(agent_yaml)


def test_load_agent_spec_non_mapping_yaml_raises_agent_spec_error(tmp_path: Path):
    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text("- not\n- a\n- mapping\n")

    with pytest.raises(AgentSpecError, match="Agent spec file must contain a mapping"):
        load_agent_spec(agent_yaml)


# Fixtures for test files


@pytest.fixture
def agent_file() -> Generator[Path, Any, Any]:
    """Create a basic agent configuration file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create system.md
        system_md = tmpdir / "system.md"
        system_md.write_text("You are a test agent")

        # Create agent.yaml
        agent_yaml = tmpdir / "agent.yaml"
        agent_yaml.write_text("""
version: 1
agent:
  name: "Test Agent"
  system_prompt_path: ./system.md
  tools: ["pythinker_code.tools.think:Think"]
""")

        yield agent_yaml


@pytest.fixture
def agent_file_no_name() -> Generator[Path, Any, Any]:
    """Create an agent configuration file without name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create system.md
        system_md = tmpdir / "system.md"
        system_md.write_text("You are a test agent")

        # Create agent.yaml
        agent_yaml = tmpdir / "agent.yaml"
        agent_yaml.write_text("""
version: 1
agent:
  system_prompt_path: ./system.md
  tools: ["pythinker_code.tools.think:Think"]
""")

        yield agent_yaml


@pytest.fixture
def agent_file_no_prompt() -> Generator[Path, Any, Any]:
    """Create an agent configuration file without system prompt path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create agent.yaml
        agent_yaml = tmpdir / "agent.yaml"
        agent_yaml.write_text("""
version: 1
agent:
  name: "Test Agent"
  tools: ["pythinker_code.tools.think:Think"]
""")

        yield agent_yaml


@pytest.fixture
def agent_file_no_tools() -> Generator[Path, Any, Any]:
    """Create an agent configuration file without tools."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create system.md
        system_md = tmpdir / "system.md"
        system_md.write_text("You are a test agent")

        # Create agent.yaml
        agent_yaml = tmpdir / "agent.yaml"
        agent_yaml.write_text("""
version: 1
agent:
  name: "Test Agent"
  system_prompt_path: ./system.md
""")

        yield agent_yaml


@pytest.fixture
def agent_file_with_tools() -> Generator[Path, Any, Any]:
    """Create an agent configuration file with tools and exclude_tools."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create system.md
        system_md = tmpdir / "system.md"
        system_md.write_text("You are a test agent")

        # Create agent.yaml
        agent_yaml = tmpdir / "agent.yaml"
        agent_yaml.write_text("""
version: 1
agent:
  name: "Test Agent"
  system_prompt_path: ./system.md
  tools: ["pythinker_code.tools.think:Think", "pythinker_code.tools.shell:Shell"]
  exclude_tools: ["pythinker_code.tools.shell:Shell"]
""")

        yield agent_yaml


@pytest.fixture
def agent_file_extending() -> Generator[Path, Any, Any]:
    """Create an agent configuration file that extends another."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create base agent
        base_agent = tmpdir / "base.yaml"
        base_agent.write_text("""
version: 1
agent:
  name: "Base Agent"
  system_prompt_path: ./system.md
  tools: ["pythinker_code.tools.think:Think"]
""")

        # Create system.md
        system_md = tmpdir / "system.md"
        system_md.write_text("Base system prompt")

        # Create extending agent
        extending_agent = tmpdir / "extending.yaml"
        extending_agent.write_text("""
version: 1
agent:
  extend: ./base.yaml
  name: "Extended Agent"
  system_prompt_args:
    CUSTOM_ARG: "custom_value"
""")

        yield extending_agent


def test_subagent_extension_merges_subagents_dicts(tmp_path: Path):
    """Extending an agent with a new subagent type should ADD to, not replace, base subagents."""
    system_md = tmp_path / "system.md"
    system_md.write_text("Base system prompt")

    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text("""
version: 1
agent:
  name: "Base"
  system_prompt_path: ./system.md
  tools: ["pythinker_code.tools.think:Think"]
  subagents:
    alpha:
      path: ./alpha.yaml
      description: "Alpha agent"
    beta:
      path: ./beta.yaml
      description: "Beta agent"
""")

    (tmp_path / "alpha.yaml").write_text(
        "version: 1\nagent:\n  name: alpha\n  system_prompt_path: ./system.md\n  tools: []\n"
    )
    (tmp_path / "beta.yaml").write_text(
        "version: 1\nagent:\n  name: beta\n  system_prompt_path: ./system.md\n  tools: []\n"
    )
    (tmp_path / "gamma.yaml").write_text(
        "version: 1\nagent:\n  name: gamma\n  system_prompt_path: ./system.md\n  tools: []\n"
    )

    child_yaml = tmp_path / "child.yaml"
    child_yaml.write_text("""
version: 1
agent:
  extend: ./base.yaml
  name: "Child"
  subagents:
    gamma:
      path: ./gamma.yaml
      description: "Gamma agent"
""")

    spec = load_agent_spec(child_yaml)

    # Child adds gamma; base alpha and beta must still be present.
    assert set(spec.subagents.keys()) == {"alpha", "beta", "gamma"}
    assert spec.subagents["gamma"].description == snapshot("Gamma agent")
    assert spec.subagents["alpha"].description == snapshot("Alpha agent")


def test_subagent_extension_child_overrides_base_entry(tmp_path: Path):
    """Child subagent with same name as base overwrites only that entry."""
    system_md = tmp_path / "system.md"
    system_md.write_text("prompt")

    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text("""
version: 1
agent:
  name: "Base"
  system_prompt_path: ./system.md
  tools: ["pythinker_code.tools.think:Think"]
  subagents:
    coder:
      path: ./coder_v1.yaml
      description: "Original coder"
    reviewer:
      path: ./reviewer.yaml
      description: "Reviewer"
""")
    for name in ("coder_v1", "coder_v2", "reviewer"):
        (tmp_path / f"{name}.yaml").write_text(
            f"version: 1\nagent:\n  name: {name}\n  system_prompt_path: ./system.md\n  tools: []\n"
        )

    child_yaml = tmp_path / "child.yaml"
    child_yaml.write_text("""
version: 1
agent:
  extend: ./base.yaml
  name: "Child"
  subagents:
    coder:
      path: ./coder_v2.yaml
      description: "Upgraded coder"
""")

    spec = load_agent_spec(child_yaml)

    assert set(spec.subagents.keys()) == {"coder", "reviewer"}
    assert spec.subagents["coder"].description == snapshot("Upgraded coder")
    assert spec.subagents["reviewer"].description == snapshot("Reviewer")
