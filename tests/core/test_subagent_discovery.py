from __future__ import annotations

from pathlib import Path

import pytest
from pythinker_host.path import HostPath

from pythinker_code.agentspec import DEFAULT_AGENT_FILE
from pythinker_code.soul.agent import load_agent
from pythinker_code.subagents.discovery import (
    discover_markdown_agents,
    materialize_markdown_agent_specs,
    parse_markdown_agent,
    resolve_agent_roots,
)


def _write_agent(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.asyncio
async def test_parse_markdown_agent_maps_claude_tools(tmp_path: Path) -> None:
    path = tmp_path / "planner.md"
    spec = parse_markdown_agent(
        """---
name: planner
description: Planning helper
tools: ["Read", "Grep", "Glob", "Bash", "UnknownThing"]
model: opus
---
Body prompt
""",
        prompt_file=HostPath.unsafe_from_local_path(path),
        scope="project",
    )

    assert spec.name == "planner"
    assert spec.description == "Planning helper"
    assert spec.model == "opus"
    assert spec.tools == (
        "pythinker_code.tools.file:ReadFile",
        "pythinker_code.tools.file:Grep",
        "pythinker_code.tools.file:Glob",
        "pythinker_code.tools.shell:Shell",
    )


@pytest.mark.asyncio
async def test_discover_project_claude_agents_from_repo_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "pkg" / "src"
    (repo / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)
    _write_agent(
        repo / ".claude" / "agents" / "observer.md",
        "---\nname: observer\ndescription: Observe code\n---\nPrompt",
    )

    roots = await resolve_agent_roots(HostPath.unsafe_from_local_path(nested))
    agents = await discover_markdown_agents(roots)

    assert [agent.name for agent in agents] == ["observer"]
    assert agents[0].scope == "project"


@pytest.mark.asyncio
async def test_project_markdown_agent_root_priority_same_name(tmp_path: Path) -> None:
    work = tmp_path / "repo"
    (work / ".git").mkdir(parents=True)
    _write_agent(
        work / ".agents" / "agents" / "helper.md",
        "---\nname: helper\ndescription: generic helper\n---\nGeneric",
    )
    _write_agent(
        work / ".claude" / "agents" / "helper.md",
        "---\nname: helper\ndescription: claude helper\n---\nClaude",
    )

    agents = await discover_markdown_agents(
        await resolve_agent_roots(HostPath.unsafe_from_local_path(work))
    )

    assert len(agents) == 1
    assert agents[0].description == "claude helper"
    assert agents[0].scope == "project"


@pytest.mark.asyncio
async def test_materialize_markdown_agent_specs_creates_agent_type(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    _write_agent(prompt, "---\nname: local-plan\ndescription: plan things\n---\nPrompt")
    spec = parse_markdown_agent(
        prompt.read_text(encoding="utf-8"),
        prompt_file=HostPath.unsafe_from_local_path(prompt),
        scope="project",
    )

    [type_def] = materialize_markdown_agent_specs([spec], output_dir=tmp_path / "out")

    assert type_def.name == "local-plan"
    assert type_def.description == "plan things"
    assert type_def.agent_file.is_file()
    wrapper = type_def.agent_file.read_text(encoding="utf-8")
    assert "system_prompt_path" in wrapper
    assert (tmp_path / "out" / "local-plan.system.md").read_text(encoding="utf-8") == "Prompt"


@pytest.mark.asyncio
async def test_load_agent_registers_project_markdown_agents(runtime) -> None:
    work = Path(str(runtime.session.work_dir))
    _write_agent(
        work / ".claude" / "agents" / "planner.md",
        '---\nname: markdown-planner\ndescription: Markdown planner\ntools: ["Read", "Grep"]\n---\nPlan carefully.',
    )

    agent = await load_agent(DEFAULT_AGENT_FILE, runtime, mcp_configs=[])
    type_def = runtime.labor_market.require_builtin_type("markdown-planner")
    agent_tool = next(tool for tool in agent.toolset.tools if tool.name == "Agent")

    assert "`markdown-planner`: Markdown planner" in agent_tool.description
    assert type_def.description == "Markdown planner"
    assert type_def.tool_policy.mode == "allowlist"
    assert type_def.tool_policy.tools == (
        "pythinker_code.tools.file:ReadFile",
        "pythinker_code.tools.file:Grep",
    )
