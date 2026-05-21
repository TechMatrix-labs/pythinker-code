from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pydantic
from jinja2 import Environment as JinjaEnvironment
from jinja2 import FileSystemLoader, StrictUndefined, TemplateError, UndefinedError
from pythinker_core.tooling import Toolset
from pythinker_host.path import HostPath

from pythinker_code.agentspec import load_agent_spec
from pythinker_code.approval_runtime import ApprovalRuntime
from pythinker_code.auth.oauth import OAuthManager
from pythinker_code.background import BackgroundTaskManager
from pythinker_code.config import Config
from pythinker_code.exception import MCPConfigError, SystemPromptTemplateError
from pythinker_code.llm import LLM
from pythinker_code.notifications import NotificationManager
from pythinker_code.prompt_templates import PromptTemplate, discover_prompt_templates
from pythinker_code.session import Session
from pythinker_code.skill import (
    Skill,
    discover_skills_from_roots,
    format_skills_for_prompt,
    index_skills,
    resolve_skills_roots,
)
from pythinker_code.soul.approval import Approval, ApprovalState
from pythinker_code.soul.denwarenji import DenwaRenji
from pythinker_code.soul.toolset import PythinkerToolset
from pythinker_code.subagents.discovery import (
    discover_markdown_agents,
    materialize_markdown_agent_specs,
    resolve_agent_roots,
)
from pythinker_code.subagents.models import AgentTypeDefinition, ToolPolicy
from pythinker_code.subagents.registry import LaborMarket
from pythinker_code.subagents.store import SubagentStore
from pythinker_code.utils.environment import Environment
from pythinker_code.utils.logging import logger
from pythinker_code.utils.path import find_project_root, is_within_directory, list_directory
from pythinker_code.wire.root_hub import RootWireHub

if TYPE_CHECKING:
    from fastmcp.mcp_config import MCPConfig


@dataclass(frozen=True, slots=True, kw_only=True)
class BuiltinSystemPromptArgs:
    """Builtin system prompt arguments."""

    PYTHINKER_NOW: str
    """The current datetime."""
    PYTHINKER_WORK_DIR: HostPath
    """The absolute path of current working directory."""
    PYTHINKER_WORK_DIR_LS: str
    """The directory listing of current working directory."""
    PYTHINKER_AGENTS_MD: str  # TODO: move to first message from system prompt
    """The merged content of AGENTS.md files (from project root to work_dir)."""
    PYTHINKER_SKILLS: str
    """Formatted information about available skills."""
    PYTHINKER_ADDITIONAL_DIRS_INFO: str
    """Formatted information about additional directories in the workspace."""
    PYTHINKER_OS: str
    """The operating system kind, e.g. 'Windows', 'macOS', 'Linux'."""
    PYTHINKER_SHELL: str
    """The shell executable used by the Shell tool, e.g. 'bash (`/bin/bash`)'."""


_AGENTS_MD_MAX_BYTES = 32 * 1024  # 32 KiB


async def _dirs_root_to_leaf(work_dir: HostPath, project_root: HostPath) -> list[HostPath]:
    """Return the list of directories from *project_root* down to *work_dir* (inclusive)."""
    dirs: list[HostPath] = []
    current = work_dir
    while True:
        dirs.append(current)
        if current == project_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    dirs.reverse()  # root → leaf
    return dirs


async def load_agents_md(work_dir: HostPath) -> str | None:
    """Discover and merge ``AGENTS.md`` files from the project root down to *work_dir*.

    For each directory on the path, the following candidates are checked in order:

    1. ``.pythinker/AGENTS.md``  — project-local pythinker config (highest priority)
    2. ``AGENTS.md``        — standard location
    3. ``agents.md``        — lowercase variant (mutually exclusive with 2)

    Within a single directory, ``.pythinker/AGENTS.md`` and ``AGENTS.md``/``agents.md``
    are **both** loaded (with ``.pythinker/`` first), but ``AGENTS.md`` and ``agents.md``
    are mutually exclusive (uppercase wins).

    All discovered files are concatenated root→leaf, separated by ``\\n\\n``, with
    source annotations.  Total size is capped at :data:`_AGENTS_MD_MAX_BYTES`.
    Budget is allocated leaf-first so deeper (more specific) files are never
    truncated in favour of shallower ones.
    """
    project_root = await find_project_root(work_dir)
    dirs = await _dirs_root_to_leaf(work_dir, project_root)

    # Phase 1: collect all candidate files (root → leaf order)
    discovered: list[tuple[HostPath, str]] = []  # (path, content)
    for d in dirs:
        # .pythinker/AGENTS.md is always checked independently (can coexist with root-level file)
        pythinker_path = d / ".pythinker" / "AGENTS.md"
        # AGENTS.md and agents.md are mutually exclusive (uppercase wins)
        root_candidates = [d / "AGENTS.md", d / "agents.md"]

        candidates: list[HostPath] = []
        if await pythinker_path.is_file():
            candidates.append(pythinker_path)
        for rc in root_candidates:
            if await rc.is_file():
                candidates.append(rc)
                break

        for path in candidates:
            content = (await path.read_text(encoding="utf-8", errors="replace")).strip()
            if content:
                discovered.append((path, content))
                logger.info("Loaded agents.md: {path}", path=path)

    if not discovered:
        logger.info(
            "No AGENTS.md found from {root} to {cwd}",
            root=project_root,
            cwd=work_dir,
        )
        return None

    # Phase 2: allocate budget leaf-first so deeper (more specific) files
    # are never truncated in favour of shallower ones.
    # The annotation overhead (<!-- From: ... -->\n and \n\n separators)
    # is included in the budget so the final output never exceeds the limit.
    remaining = _AGENTS_MD_MAX_BYTES
    budgeted: list[tuple[HostPath, str] | None] = [None] * len(discovered)
    for i in reversed(range(len(discovered))):
        path, content = discovered[i]
        annotation = f"<!-- From: {path} -->\n"
        # Reserve space for the annotation and the \n\n separator between parts
        separator_cost = len(b"\n\n") if i < len(discovered) - 1 else 0
        overhead = len(annotation.encode("utf-8")) + separator_cost
        remaining -= overhead
        if remaining <= 0:
            budgeted[i] = (path, "")
            remaining = 0
            continue
        encoded = content.encode("utf-8")
        if len(encoded) > remaining:
            content = encoded[:remaining].decode("utf-8", errors="ignore").strip()
            logger.warning("AGENTS.md truncated due to size limit: {path}", path=path)
        remaining -= len(content.encode("utf-8"))
        budgeted[i] = (path, content)

    # Phase 3: assemble in root → leaf order, skipping entries emptied by truncation
    parts: list[str] = []
    for path, content in budgeted:
        if content:
            parts.append(f"<!-- From: {path} -->\n{content}")

    return "\n\n".join(parts) if parts else None


@dataclass(slots=True, kw_only=True)
class Runtime:
    """Agent runtime."""

    config: Config
    oauth: OAuthManager
    llm: LLM | None  # we do not freeze the `Runtime` dataclass because LLM can be changed
    session: Session
    builtin_args: BuiltinSystemPromptArgs
    denwa_renji: DenwaRenji
    approval: Approval
    labor_market: LaborMarket
    environment: Environment
    notifications: NotificationManager
    background_tasks: BackgroundTaskManager
    skills: dict[str, Skill]
    additional_dirs: list[HostPath]
    skills_dirs: list[HostPath]
    prompt_templates: dict[str, PromptTemplate] = field(default_factory=dict[str, PromptTemplate])
    subagent_store: SubagentStore | None = None
    approval_runtime: ApprovalRuntime | None = None
    root_wire_hub: RootWireHub | None = None
    subagent_id: str | None = None
    subagent_type: str | None = None
    role: Literal["root", "subagent"] = "root"
    ui_mode: str = "shell"
    resumed: bool = False
    hook_engine: Any = None
    """HookEngine instance, set by PythinkerCLI after soul creation."""

    def __post_init__(self) -> None:
        if self.subagent_store is None:
            self.subagent_store = SubagentStore(self.session)
        if self.root_wire_hub is None:
            self.root_wire_hub = RootWireHub()
        if self.approval_runtime is None:
            self.approval_runtime = ApprovalRuntime()
        self.approval_runtime.bind_root_wire_hub(self.root_wire_hub)
        self.approval.set_runtime(self.approval_runtime)
        self.background_tasks.bind_runtime(self)

    @staticmethod
    async def create(
        config: Config,
        oauth: OAuthManager,
        llm: LLM | None,
        session: Session,
        yolo: bool,
        auto: bool = False,
        runtime_auto: bool = False,
        skills_dirs: list[HostPath] | None = None,
    ) -> Runtime:
        ls_output, agents_md, environment = await asyncio.gather(
            list_directory(session.work_dir),
            load_agents_md(session.work_dir),
            Environment.detect(),
        )

        # Discover and format skills (grouped by scope for the system prompt).
        scoped_roots = await resolve_skills_roots(
            session.work_dir,
            skills_dirs=skills_dirs,
            merge_brands=config.merge_all_available_skills,
            extra_skill_dirs=config.extra_skill_dirs or None,
        )
        # Canonicalize so symlinked skill directories match resolved paths
        skills_roots_canonical = [s.root.canonical() for s in scoped_roots]
        skills = await discover_skills_from_roots(scoped_roots)
        skills_by_name = index_skills(skills)
        logger.info("Discovered {count} skill(s)", count=len(skills))
        skills_formatted = format_skills_for_prompt(skills)

        prompt_templates = await discover_prompt_templates(session.work_dir)
        logger.info("Discovered {count} prompt template(s)", count=len(prompt_templates))

        # Restore additional directories from session state, pruning stale entries
        additional_dirs: list[HostPath] = []
        pruned = False
        valid_dir_strs: list[str] = []
        for dir_str in session.state.additional_dirs:
            d = HostPath(dir_str).canonical()
            if await d.is_dir():
                additional_dirs.append(d)
                valid_dir_strs.append(dir_str)
            else:
                logger.warning(
                    "Additional directory no longer exists, removing from state: {dir}",
                    dir=dir_str,
                )
                pruned = True
        if pruned:
            session.state.additional_dirs = valid_dir_strs
            session.save_state()

        # Format additional dirs info for system prompt
        additional_dirs_info = ""
        if additional_dirs:
            parts: list[str] = []
            for d in additional_dirs:
                try:
                    dir_ls = await list_directory(d)
                except OSError:
                    logger.warning(
                        "Cannot list additional directory, skipping listing: {dir}", dir=d
                    )
                    dir_ls = "[directory not readable]"
                parts.append(f"### `{d}`\n\n```\n{dir_ls}\n```")
            additional_dirs_info = "\n\n".join(parts)

        # Merge invocation flags with persisted session state.
        effective_yolo = yolo or session.state.approval.yolo
        if auto and not session.state.approval.auto:
            session.state.approval.auto = True
            session.save_state()
        saved_actions = set(session.state.approval.auto_approve_actions)

        def _on_approval_change() -> None:
            session.state.approval.yolo = approval_state.yolo
            session.state.approval.auto = approval_state.auto
            session.state.approval.auto_approve_actions = set(approval_state.auto_approve_actions)
            session.save_state()

        approval_state = ApprovalState(
            yolo=effective_yolo,
            auto=session.state.approval.auto,
            runtime_auto=runtime_auto,
            auto_approve_actions=saved_actions,
            on_change=_on_approval_change,
        )
        notifications = NotificationManager(
            session.context_file.parent / "notifications",
            config.notifications,
        )

        return Runtime(
            config=config,
            oauth=oauth,
            llm=llm,
            session=session,
            builtin_args=BuiltinSystemPromptArgs(
                PYTHINKER_NOW=datetime.now().astimezone().isoformat(),
                PYTHINKER_WORK_DIR=session.work_dir,
                PYTHINKER_WORK_DIR_LS=ls_output,
                PYTHINKER_AGENTS_MD=agents_md or "",
                PYTHINKER_SKILLS=skills_formatted or "No skills found.",
                PYTHINKER_ADDITIONAL_DIRS_INFO=additional_dirs_info,
                PYTHINKER_OS=environment.os_kind,
                PYTHINKER_SHELL=f"{environment.shell_name} (`{environment.shell_path}`)",
            ),
            denwa_renji=DenwaRenji(),
            approval=Approval(state=approval_state),
            labor_market=LaborMarket(),
            environment=environment,
            notifications=notifications,
            background_tasks=BackgroundTaskManager(
                session,
                config.background,
                notifications=notifications,
            ),
            skills=skills_by_name,
            prompt_templates=prompt_templates,
            additional_dirs=additional_dirs,
            # Only expose skills roots outside the workspace for Glob access;
            # project-level roots are already within work_dir.
            skills_dirs=[
                r for r in skills_roots_canonical if not is_within_directory(r, session.work_dir)
            ],
            subagent_store=SubagentStore(session),
            approval_runtime=ApprovalRuntime(),
            root_wire_hub=RootWireHub(),
            role="root",
        )

    def copy_for_subagent(
        self,
        *,
        agent_id: str,
        subagent_type: str,
        llm_override: LLM | None = None,
    ) -> Runtime:
        """Clone runtime for a subagent."""
        return Runtime(
            config=self.config,
            oauth=self.oauth,
            llm=llm_override if llm_override is not None else self.llm,
            session=self.session,
            builtin_args=self.builtin_args,
            denwa_renji=DenwaRenji(),  # subagent must have its own DenwaRenji
            approval=self.approval.share(),
            labor_market=self.labor_market,
            environment=self.environment,
            notifications=self.notifications,
            background_tasks=self.background_tasks.copy_for_role("subagent"),
            skills=self.skills,
            prompt_templates=self.prompt_templates,
            # Share the same list reference so /add-dir mutations propagate to all agents
            additional_dirs=self.additional_dirs,
            skills_dirs=self.skills_dirs,
            subagent_store=self.subagent_store,
            approval_runtime=self.approval_runtime,
            root_wire_hub=self.root_wire_hub,
            subagent_id=agent_id,
            subagent_type=subagent_type,
            role="subagent",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Agent:
    """The loaded agent."""

    name: str
    system_prompt: str
    toolset: Toolset
    runtime: Runtime
    """Each agent has its own runtime, which should be derived from its main agent."""


async def load_agent(
    agent_file: Path,
    runtime: Runtime,
    *,
    mcp_configs: list[MCPConfig] | list[dict[str, Any]],
    start_mcp_loading: bool = True,
) -> Agent:
    """
    Load agent from specification file.

    Raises:
        FileNotFoundError: When the agent file is not found.
        AgentSpecError(PythinkerCLIException, ValueError): When the agent specification is invalid.
        SystemPromptTemplateError(PythinkerCLIException, ValueError): When the system prompt
            template is invalid.
        InvalidToolError(PythinkerCLIException, ValueError): When any tool cannot be loaded.
        MCPConfigError(PythinkerCLIException, ValueError): When any MCP configuration is invalid.
        MCPRuntimeError(PythinkerCLIException, RuntimeError): When any MCP server cannot be
            connected.
    """
    logger.info("Loading agent: {agent_file}", agent_file=agent_file)
    agent_spec = load_agent_spec(agent_file)

    system_prompt = _load_system_prompt(
        agent_spec.system_prompt_path,
        agent_spec.system_prompt_args,
        runtime.builtin_args,
    )

    # Register built-in subagent types before loading tools because some tools render
    # descriptions from the labor market on initialization.
    for subagent_name, subagent_spec in agent_spec.subagents.items():
        logger.debug(
            "Registering builtin subagent type: {subagent_name}", subagent_name=subagent_name
        )
        builtin_spec = load_agent_spec(subagent_spec.path)
        tool_policy = (
            ToolPolicy(mode="allowlist", tools=tuple(builtin_spec.allowed_tools))
            if builtin_spec.allowed_tools is not None
            else ToolPolicy(mode="inherit")
        )
        runtime.labor_market.add_builtin_type(
            AgentTypeDefinition(
                name=subagent_name,
                description=subagent_spec.description,
                agent_file=subagent_spec.path,
                when_to_use=builtin_spec.when_to_use,
                default_model=builtin_spec.model,
                tool_policy=tool_policy,
            )
        )

    external_agents = await discover_markdown_agents(
        await resolve_agent_roots(runtime.session.work_dir)
    )
    for type_def in materialize_markdown_agent_specs(
        external_agents,
        output_dir=runtime.session.dir / "external_agents",
        available_models=set(runtime.config.models),
    ):
        if runtime.labor_market.get_builtin_type(type_def.name) is not None:
            logger.warning(
                "Skipping external markdown agent {name}: would override a built-in subagent type",
                name=type_def.name,
            )
            continue
        logger.debug("Registering external markdown agent type: {name}", name=type_def.name)
        runtime.labor_market.add_builtin_type(type_def)

    toolset = PythinkerToolset(runtime)
    tool_deps = {
        PythinkerToolset: toolset,
        Runtime: runtime,
        # TODO: remove all the following dependencies and use Runtime instead
        Config: runtime.config,
        BuiltinSystemPromptArgs: runtime.builtin_args,
        Session: runtime.session,
        DenwaRenji: runtime.denwa_renji,
        Approval: runtime.approval,
        LaborMarket: runtime.labor_market,
        Environment: runtime.environment,
    }
    tools = agent_spec.allowed_tools if agent_spec.allowed_tools is not None else agent_spec.tools
    if agent_spec.exclude_tools:
        logger.debug("Excluding tools: {tools}", tools=agent_spec.exclude_tools)
        tools = [tool for tool in tools if tool not in agent_spec.exclude_tools]
    toolset.load_tools(tools, tool_deps)

    # Load plugin tools
    from pythinker_code.plugin.manager import get_plugins_dir
    from pythinker_code.plugin.tool import load_plugin_tools

    plugin_tools = load_plugin_tools(get_plugins_dir(), runtime.config, approval=runtime.approval)
    for plugin_tool in plugin_tools:
        if toolset.find(plugin_tool.name) is not None:
            logger.warning(
                "Plugin tool '{name}' conflicts with an existing tool, skipping",
                name=plugin_tool.name,
            )
            continue
        toolset.add(plugin_tool)

    if mcp_configs:
        validated_mcp_configs: list[MCPConfig] = []
        if mcp_configs:
            from fastmcp.mcp_config import MCPConfig

            for mcp_config in mcp_configs:
                try:
                    validated_mcp_configs.append(
                        mcp_config
                        if isinstance(mcp_config, MCPConfig)
                        else MCPConfig.model_validate(mcp_config)
                    )
                except pydantic.ValidationError as e:
                    raise MCPConfigError(f"Invalid MCP config: {e}") from e
        if start_mcp_loading:
            await toolset.load_mcp_tools(validated_mcp_configs, runtime, in_background=True)
        else:
            toolset.defer_mcp_tool_loading(validated_mcp_configs, runtime)

    return Agent(
        name=agent_spec.name,
        system_prompt=system_prompt,
        toolset=toolset,
        runtime=runtime,
    )


def _load_system_prompt(
    path: Path, args: dict[str, str], builtin_args: BuiltinSystemPromptArgs
) -> str:
    logger.info("Loading system prompt: {path}", path=path)
    system_prompt = path.read_text(encoding="utf-8").strip()
    logger.debug(
        "Substituting system prompt with builtin args: {builtin_args}, spec args: {spec_args}",
        builtin_args=builtin_args,
        spec_args=args,
    )
    env = JinjaEnvironment(
        loader=FileSystemLoader(path.parent),
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
        variable_start_string="${",
        variable_end_string="}",
        undefined=StrictUndefined,
    )
    try:
        template = env.from_string(system_prompt)
        return template.render(asdict(builtin_args), **args)
    except UndefinedError as exc:
        raise SystemPromptTemplateError(f"Missing system prompt arg in {path}: {exc}") from exc
    except TemplateError as exc:
        raise SystemPromptTemplateError(f"Invalid system prompt template: {path}: {exc}") from exc
