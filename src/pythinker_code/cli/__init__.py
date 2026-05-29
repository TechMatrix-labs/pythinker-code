from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import typer

if TYPE_CHECKING:
    from pythinker_code.session import Session


class Reload(Exception):
    """Reload configuration."""

    def __init__(self, session_id: str | None = None, prefill_text: str | None = None):
        super().__init__("reload")
        self.session_id = session_id
        self.prefill_text = prefill_text
        self.source_session: Session | None = None


class SwitchToWeb(Exception):
    """Switch to web interface."""

    def __init__(self, session_id: str | None = None):
        super().__init__("switch_to_web")
        self.session_id = session_id


class SwitchToVis(Exception):
    """Switch to vis (tracing visualizer) interface."""

    def __init__(self, session_id: str | None = None):
        super().__init__("switch_to_vis")
        self.session_id = session_id


def load_config() -> Any:
    from pythinker_code.config import load_config as impl

    return impl()


def login_anthropic_api_key(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.anthropic_direct import login_anthropic_api_key as impl

    return impl(*args, **kwargs)


def logout_anthropic(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.anthropic_direct import logout_anthropic as impl

    return impl(*args, **kwargs)


def login_deepseek_api_key(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.deepseek import login_deepseek_api_key as impl

    return impl(*args, **kwargs)


def logout_deepseek(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.deepseek import logout_deepseek as impl

    return impl(*args, **kwargs)


def login_lm_studio(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.lm_studio import login_lm_studio as impl

    return impl(*args, **kwargs)


def logout_lm_studio(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.lm_studio import logout_lm_studio as impl

    return impl(*args, **kwargs)


def login_ollama(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.ollama import login_ollama as impl

    return impl(*args, **kwargs)


def logout_ollama(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.ollama import logout_ollama as impl

    return impl(*args, **kwargs)


def login_minimax_api_key(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.minimax import login_minimax_api_key as impl

    return impl(*args, **kwargs)


def logout_minimax(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.minimax import logout_minimax as impl

    return impl(*args, **kwargs)


def login_openai_api_key(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.openai import login_openai_api_key as impl

    return impl(*args, **kwargs)


def login_openai_browser(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.openai import login_openai_browser as impl

    return impl(*args, **kwargs)


def login_openai_headless(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.openai import login_openai_headless as impl

    return impl(*args, **kwargs)


def logout_openai(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.openai import logout_openai as impl

    return impl(*args, **kwargs)


def login_opencode_go_api_key(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.opencode_go import login_opencode_go_api_key as impl

    return impl(*args, **kwargs)


def logout_opencode_go(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.opencode_go import logout_opencode_go as impl

    return impl(*args, **kwargs)


def login_openrouter_api_key(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.openrouter import login_openrouter_api_key as impl

    return impl(*args, **kwargs)


def logout_openrouter(*args: Any, **kwargs: Any) -> Any:
    from pythinker_code.auth.openrouter import logout_openrouter as impl

    return impl(*args, **kwargs)


LazySubcommandGroup = import_module(f"{__name__}._lazy_group").LazySubcommandGroup


cli = typer.Typer(
    cls=LazySubcommandGroup,
    epilog="""\b\
Documentation:        https://techmatrix-labs.github.io/pythinker-code/\n
LLM friendly version: https://techmatrix-labs.github.io/pythinker-code/llms.txt""",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Pythinker, your next CLI agent.",
)

UIMode = Literal["shell", "print", "acp", "wire"]


class ExitCode:
    SUCCESS = 0
    FAILURE = 1
    RETRYABLE = 75  # EX_TEMPFAIL from sysexits.h


InputFormat = Literal["text", "stream-json"]
OutputFormat = Literal["text", "stream-json"]


def _strip_session_id_suffix(title: str, session_id: str) -> str:
    """Remove the trailing `` (session_id)`` suffix from a session title, if present."""
    suffix = f" ({session_id})"
    return title.rsplit(suffix, 1)[0] if title.endswith(suffix) else title


def _version_callback(value: bool) -> None:
    if value:
        from pythinker_code.constant import get_version

        typer.echo(f"pythinker, version {get_version()}")
        raise typer.Exit()


@cli.callback(invoke_without_command=True)
def pythinker(
    ctx: typer.Context,
    # Meta
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Print verbose information. Default: no.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Log debug information. Default: no.",
        ),
    ] = False,
    # Basic configuration
    local_work_dir: Annotated[
        Path | None,
        typer.Option(
            "--work-dir",
            "-w",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            writable=True,
            help="Working directory for the agent. Default: current directory.",
        ),
    ] = None,
    local_add_dirs: Annotated[
        list[Path] | None,
        typer.Option(
            "--add-dir",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help=(
                "Add an additional directory to the workspace scope. "
                "Can be specified multiple times."
            ),
        ),
    ] = None,
    session_id: Annotated[
        str | None,
        typer.Option(
            "--session",
            "--resume",
            "-S",
            "-r",
            help=(
                "Resume a session. "
                "With ID: resume that session. "
                "Without ID: interactively pick a session."
            ),
        ),
    ] = None,
    continue_: Annotated[
        bool,
        typer.Option(
            "--continue",
            "-C",
            help="Continue the previous session for the working directory. Default: no.",
        ),
    ] = False,
    config_string: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Config TOML/JSON string to load. Default: none.",
        ),
    ] = None,
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config-file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Config TOML/JSON file to load. Default: ~/.pythinker/config.toml.",
        ),
    ] = None,
    model_name: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="LLM model to use. Default: default model set in config file.",
        ),
    ] = None,
    thinking: Annotated[
        bool | None,
        typer.Option(
            "--thinking/--no-thinking",
            help="Enable thinking mode. Default: default thinking mode set in config file.",
        ),
    ] = None,
    no_telemetry: Annotated[
        bool,
        typer.Option(
            "--no-telemetry",
            help=(
                "Disable all anonymous usage telemetry and error reporting "
                "(equivalent to setting PYTHINKER_DISABLE_TELEMETRY=1). "
                "Default: telemetry on."
            ),
        ),
    ] = False,
    # Run mode
    yolo: Annotated[
        bool,
        typer.Option(
            "--yolo",
            "--yes",
            "-y",
            "--auto-approve",
            help="Automatically approve all actions. Default: no.",
        ),
    ] = False,
    plan: Annotated[
        bool,
        typer.Option(
            "--plan",
            help="Start in plan mode. Default: no.",
        ),
    ] = False,
    auto: Annotated[
        bool,
        typer.Option(
            "--auto",
            help=(
                "Run in auto mode: no user is present, AskUserQuestion is auto-dismissed, "
                "and tool calls are auto-approved. Use when running unattended "
                "(scripts, CI, scheduled jobs). Default: no."
            ),
        ),
    ] = False,
    prompt: Annotated[
        str | None,
        typer.Option(
            "--prompt",
            "-p",
            "--command",
            "-c",
            help="User prompt to the agent. Default: prompt interactively.",
        ),
    ] = None,
    print_mode: Annotated[
        bool,
        typer.Option(
            "--print",
            help=(
                "Run in print mode (non-interactive). Print mode auto-dismisses "
                "AskUserQuestion and auto-approves tool calls for this invocation."
            ),
        ),
    ] = False,
    acp_mode: Annotated[
        bool,
        typer.Option(
            "--acp",
            help="(Deprecated, use `pythinker acp` instead) Run as ACP server.",
        ),
    ] = False,
    wire_mode: Annotated[
        bool,
        typer.Option(
            "--wire",
            help="Run as Wire server (experimental).",
        ),
    ] = False,
    input_format: Annotated[
        InputFormat | None,
        typer.Option(
            "--input-format",
            help=(
                "Input format to use. Must be used with `--print` "
                "and the input must be piped in via stdin. "
                "Default: text."
            ),
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat | None,
        typer.Option(
            "--output-format",
            help="Output format to use. Must be used with `--print`. Default: text.",
        ),
    ] = None,
    final_message_only: Annotated[
        bool,
        typer.Option(
            "--final-message-only",
            help="Only print the final assistant message (print UI).",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            help="Alias for `--print --output-format text --final-message-only`.",
        ),
    ] = False,
    # Customization
    agent: Annotated[
        Literal["default", "okabe"] | None,
        typer.Option(
            "--agent",
            help="Builtin agent specification to use. Default: builtin default agent.",
        ),
    ] = None,
    agent_file: Annotated[
        Path | None,
        typer.Option(
            "--agent-file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Custom agent specification file. Default: builtin default agent.",
        ),
    ] = None,
    mcp_config_file: Annotated[
        list[Path] | None,
        typer.Option(
            "--mcp-config-file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help=(
                "MCP config file to load. Add this option multiple times to specify multiple MCP "
                "configs. Default: none."
            ),
        ),
    ] = None,
    mcp_config: Annotated[
        list[str] | None,
        typer.Option(
            "--mcp-config",
            help=(
                "MCP config JSON to load. Add this option multiple times to specify multiple MCP "
                "configs. Default: none."
            ),
        ),
    ] = None,
    local_skills_dir: Annotated[
        list[Path] | None,
        typer.Option(
            "--skills-dir",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="Custom skills directories (repeatable). Overrides default discovery.",
        ),
    ] = None,
    # Loop control
    max_steps_per_turn: Annotated[
        int | None,
        typer.Option(
            "--max-steps-per-turn",
            min=1,
            help="Maximum number of steps in one turn. Default: from config.",
        ),
    ] = None,
    max_retries_per_step: Annotated[
        int | None,
        typer.Option(
            "--max-retries-per-step",
            min=1,
            help="Maximum number of retries in one step. Default: from config.",
        ),
    ] = None,
    max_ralph_iterations: Annotated[
        int | None,
        typer.Option(
            "--max-ralph-iterations",
            min=-1,
            help=(
                "Extra iterations after the first turn in Ralph mode. Use -1 for unlimited. "
                "Default: from config."
            ),
        ),
    ] = None,
):
    """Pythinker, your next CLI agent."""
    import asyncio
    import contextlib
    import json

    from pythinker_code.utils.proctitle import init_process_name

    init_process_name("Pythinker")

    if ctx.invoked_subcommand is not None:
        return  # skip rest if a subcommand is invoked

    del version  # handled in the callback

    from pythinker_host.path import HostPath

    from pythinker_code.agentspec import DEFAULT_AGENT_FILE, OKABE_AGENT_FILE
    from pythinker_code.app import PythinkerCLI, enable_logging
    from pythinker_code.config import Config, load_config_from_string
    from pythinker_code.exception import ConfigError
    from pythinker_code.hooks import events as hook_events
    from pythinker_code.metadata import load_metadata, save_metadata
    from pythinker_code.session import Session
    from pythinker_code.ui.shell.startup import ShellStartupProgress
    from pythinker_code.utils.logging import logger, open_original_stderr, redirect_stderr_to_logger

    from .mcp import get_global_mcp_config_file

    # Don't redirect stderr during argument parsing. Our stderr redirector
    # replaces fd=2 with a pipe, which would swallow Click/Typer startup errors.
    # Redirection is installed later, right before PythinkerCLI.create(), so that
    # MCP server stderr noise is captured into logs from the start.
    enable_logging(debug, redirect_stderr=False)

    def _emit_fatal_error(message: str) -> None:
        # Prefer writing to the original stderr fd even if we later redirect fd=2.
        # This ensures fatal errors are visible to the user.
        with open_original_stderr() as stream:
            if stream is not None:
                stream.write((message.rstrip() + "\n").encode("utf-8", errors="replace"))
                stream.flush()
                return
        typer.echo(message, err=True)

    # session_id states:
    #   None  → not provided (new session)
    #   ""    → --session/--resume without value (picker mode)
    #   "ID"  → --session ID (resume specific session)
    _picker_mode = session_id == ""
    if session_id is not None:
        session_id = session_id.strip() or None  # treat whitespace-only as picker mode
        if session_id is None:
            _picker_mode = True

    if quiet:
        if acp_mode or wire_mode:
            raise typer.BadParameter(
                "Quiet mode cannot be combined with ACP or Wire UI",
                param_hint="--quiet",
            )
        if output_format not in (None, "text"):
            raise typer.BadParameter(
                "Quiet mode implies `--output-format text`",
                param_hint="--quiet",
            )
        print_mode = True
        output_format = "text"
        final_message_only = True

    conflict_option_sets = [
        {
            "--print": print_mode,
            "--acp": acp_mode,
            "--wire": wire_mode,
        },
        {
            "--agent": agent is not None,
            "--agent-file": agent_file is not None,
        },
        {
            "--continue": continue_,
            "--session": session_id is not None or _picker_mode,
        },
        {
            "--config": config_string is not None,
            "--config-file": config_file is not None,
        },
    ]
    for option_set in conflict_option_sets:
        active_options = [flag for flag, active in option_set.items() if active]
        if len(active_options) > 1:
            raise typer.BadParameter(
                f"Cannot combine {', '.join(active_options)}.",
                param_hint=active_options[0],
            )

    if agent is not None:
        match agent:
            case "default":
                agent_file = DEFAULT_AGENT_FILE
            case "okabe":
                agent_file = OKABE_AGENT_FILE

    ui: UIMode = "shell"
    if print_mode:
        ui = "print"
    elif acp_mode:
        ui = "acp"
    elif wire_mode:
        ui = "wire"

    if prompt is not None:
        prompt = prompt.strip()
        if not prompt:
            raise typer.BadParameter("Prompt cannot be empty", param_hint="--prompt")

    if input_format is not None and ui != "print":
        raise typer.BadParameter(
            "Input format is only supported for print UI",
            param_hint="--input-format",
        )
    if output_format is not None and ui != "print":
        raise typer.BadParameter(
            "Output format is only supported for print UI",
            param_hint="--output-format",
        )
    if final_message_only and ui != "print":
        raise typer.BadParameter(
            "Final-message-only output is only supported for print UI",
            param_hint="--final-message-only",
        )
    if _picker_mode and ui != "shell":
        raise typer.BadParameter(
            "--session without a session ID is only supported for shell UI",
            param_hint="--session",
        )

    config: Config | Path | None = None
    if config_string is not None:
        config_string = config_string.strip()
        if not config_string:
            raise typer.BadParameter("Config cannot be empty", param_hint="--config")
        try:
            config = load_config_from_string(config_string)
        except ConfigError as e:
            raise typer.BadParameter(str(e), param_hint="--config") from e
    elif config_file is not None:
        config = config_file

    file_configs = list(mcp_config_file or [])
    raw_mcp_config = list(mcp_config or [])

    # Use default MCP config file if no MCP config is provided
    if not file_configs:
        default_mcp_file = get_global_mcp_config_file()
        if default_mcp_file.exists():
            file_configs.append(default_mcp_file)

    try:
        mcp_configs = [json.loads(conf.read_text(encoding="utf-8")) for conf in file_configs]
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"Invalid JSON: {e}", param_hint="--mcp-config-file") from e

    try:
        mcp_configs += [json.loads(conf) for conf in raw_mcp_config]
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"Invalid JSON: {e}", param_hint="--mcp-config") from e

    # Honor --no-telemetry by exporting the env var before any subsystem (Sentry,
    # OTel, sink) reads it during PythinkerCLI.create.
    if no_telemetry:
        os.environ["PYTHINKER_DISABLE_TELEMETRY"] = "1"

    skills_dirs: list[HostPath] | None = None
    if local_skills_dir:
        skills_dirs = [HostPath.unsafe_from_local_path(p) for p in local_skills_dir]

    work_dir = HostPath.unsafe_from_local_path(local_work_dir) if local_work_dir else HostPath.cwd()

    # Tracks the most recently created/loaded session so that _reload_loop's
    # exception handler can clean it up even when _run() fails before returning.
    _latest_created_session: Session | None = None

    async def _run(session_id: str | None, prefill_text: str | None = None) -> tuple[Session, int]:
        """
        Create/load session and run the CLI instance.

        Returns:
            The session and the exit code (0 = success, 1 = failure, 75 = retryable).
        """
        startup_progress = ShellStartupProgress(enabled=ui == "shell")
        try:
            startup_progress.update("Preparing session...")

            # Track if we're resuming an existing session (vs creating new)
            resumed = False

            if session_id is not None:
                session = await Session.find(work_dir, session_id)
                if session is None:
                    logger.info(
                        "Session {session_id} not found, creating new session",
                        session_id=session_id,
                    )
                    session = await Session.create(work_dir, session_id)
                else:
                    # Only count as "resumed" if the session has actual turns.
                    # Sessions created by /new, /undo (turn 0), /fork via Reload
                    # may have a custom_title but no wire content — treat as startup.
                    resumed = not session.wire_file.is_empty()
                logger.info("Resuming session: {session_id}", session_id=session.id)
            elif continue_:
                session = await Session.continue_(work_dir)
                if session is None:
                    raise typer.BadParameter(
                        "No previous session found for the working directory",
                        param_hint="--continue",
                    )
                resumed = True  # Continuing previous session
                logger.info("Continuing previous session: {session_id}", session_id=session.id)
            else:
                session = await Session.create(work_dir)
                logger.info("Created new session: {session_id}", session_id=session.id)

            nonlocal _latest_created_session
            _latest_created_session = session

            # Add CLI-provided additional directories to session state
            if local_add_dirs:
                from pythinker_code.utils.path import is_within_directory

                canonical_work_dir = work_dir.canonical()
                changed = False
                for d in local_add_dirs:
                    dir_path = HostPath.unsafe_from_local_path(d).canonical()
                    dir_str = str(dir_path)
                    # Skip dirs within work_dir (already accessible)
                    if is_within_directory(dir_path, canonical_work_dir):
                        logger.info(
                            "Skipping --add-dir {dir}: already within working directory",
                            dir=dir_str,
                        )
                        continue
                    if dir_str not in session.state.additional_dirs:
                        session.state.additional_dirs.append(dir_str)
                        changed = True
                if changed:
                    session.save_state()

            # Redirect stderr *before* PythinkerCLI.create() so that MCP server
            # subprocesses (e.g. mcp-remote OAuth debug logs) write to the log
            # file instead of polluting the user's terminal.  CLI argument
            # parsing has already succeeded at this point, so Typer/Click
            # startup errors are no longer a concern.  Fatal errors from
            # create() are still visible because _emit_fatal_error() writes to
            # the saved original stderr fd.
            redirect_stderr_to_logger()

            from pythinker_code.scratchpad import (
                append_scratch_event_sync,
                ensure_git_excluded,
                render_scratchpad_section,
                scratch_file_exists,
            )

            scratchpad_status = await ensure_git_excluded(work_dir)
            scratch_exists_before_start = scratch_file_exists(work_dir)
            if scratchpad_status.available:
                session_source = "resume" if resumed else "startup"
                workspace_label = Path(str(work_dir)).name or "workspace"
                await asyncio.to_thread(
                    append_scratch_event_sync,
                    work_dir,
                    session_id=session.id,
                    session_title=session.title,
                    labels=[
                        f"workspace:{workspace_label}",
                        f"ui:{ui}",
                        f"source:{session_source}",
                    ],
                    title="session start",
                    details=[
                        f"source: {session_source}",
                        f"ui: {ui}",
                        "scratch: named per-session history retained",
                    ],
                    create=True,
                    # Idempotent: relaunching the same session must not append a
                    # second identical "session start" milestone (a genuine
                    # startup→resume transition has a different source/signature).
                    dedup_signature=f"source: {session_source}",
                )
            scratchpad_section = render_scratchpad_section(
                scratchpad_status,
                scratch_exists=scratch_exists_before_start,
            )

            instance = await PythinkerCLI.create(
                session,
                config=config,
                model_name=model_name,
                thinking=thinking,
                yolo=yolo,
                auto=auto,
                runtime_auto=ui == "print",
                plan_mode=plan,
                resumed=resumed,
                agent_file=agent_file,
                mcp_configs=mcp_configs,
                skills_dirs=skills_dirs,
                max_steps_per_turn=max_steps_per_turn,
                max_retries_per_step=max_retries_per_step,
                max_ralph_iterations=max_ralph_iterations,
                startup_progress=startup_progress.update if ui == "shell" else None,
                defer_mcp_loading=ui == "shell" and prompt is None,
                ui_mode=ui,
                scratchpad_section=scratchpad_section,
            )
            startup_progress.stop()

            # --- SessionStart hook ---
            _session_source = "resume" if resumed else "startup"
            await instance.soul.hook_engine.trigger(
                "SessionStart",
                matcher_value=_session_source,
                input_data=hook_events.session_start(
                    session_id=session.id,
                    cwd=str(work_dir),
                    source=_session_source,
                ),
            )

            # Install stderr redirection only after initialization succeeded, so runtime
            # stderr noise is captured into logs without hiding startup failures.
            redirect_stderr_to_logger()
            preserve_background_tasks = False
            try:
                match ui:
                    case "shell":
                        shell_ok = await instance.run_shell(prompt, prefill_text=prefill_text)
                        exit_code = ExitCode.SUCCESS if shell_ok else ExitCode.FAILURE
                    case "print":
                        exit_code = await instance.run_print(
                            input_format or "text",
                            output_format or "text",
                            prompt,
                            final_only=final_message_only,
                        )
                    case "acp":
                        if prompt is not None:
                            logger.warning("ACP server ignores prompt argument")
                        await instance.run_acp()
                        exit_code = ExitCode.SUCCESS
                    case "wire":
                        if prompt is not None:
                            logger.warning("Wire server ignores prompt argument")
                        await instance.run_wire_stdio()
                        exit_code = ExitCode.SUCCESS
            except Reload as e:
                preserve_background_tasks = True
                if e.session_id is None:
                    r = Reload(session_id=session.id, prefill_text=e.prefill_text)
                    r.source_session = session
                    raise r from e
                e.source_session = session
                raise
            except SwitchToWeb:
                preserve_background_tasks = True
                raise
            except SwitchToVis:
                preserve_background_tasks = True
                raise
            finally:
                # --- SessionEnd hook ---
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        instance.soul.hook_engine.trigger(
                            "SessionEnd",
                            matcher_value="exit",
                            input_data=hook_events.session_end(
                                session_id=session.id,
                                cwd=str(work_dir),
                                reason="exit",
                            ),
                        ),
                        timeout=5,
                    )

                if not preserve_background_tasks:
                    await instance.shutdown_background_tasks()
                    await instance.await_bg_tasks_shutdown()

            return session, exit_code
        finally:
            startup_progress.stop()

    async def _delete_empty_session(session: Session) -> None:
        """Delete an empty session directory and clear last_session_id if it pointed to it."""
        logger.info(
            "Session {session_id} has empty context, removing it",
            session_id=session.id,
        )
        await session.delete()
        meta = load_metadata()
        wdm = meta.get_work_dir_meta(session.work_dir)
        if wdm is not None and wdm.last_session_id == session.id:
            wdm.last_session_id = None
            save_metadata(meta)

    def _print_resume_hint(session: Session) -> None:
        """Print a hint for resuming the session after exit."""
        if not session.is_empty():
            _emit_fatal_error(f"\nTo resume this session: pythinker -r {session.id}")

    async def _post_run(
        last_session: Session, exit_code: int, *, cleanup_scratchpad: bool = False
    ) -> None:
        # Session scratchpads are retained as compact history for future recall.
        # ``cleanup_scratchpad`` is kept for call-site compatibility but no longer
        # triggers automatic deletion after a successful run.
        _ = cleanup_scratchpad
        if exit_code == ExitCode.SUCCESS and getattr(
            getattr(config, "memory", None), "journal_recaps", False
        ):
            with contextlib.suppress(Exception):
                from pythinker_code.memory.recap import build_session_recap
                from pythinker_code.project_memory import ProjectMemoryStore

                recap = build_session_recap(
                    state=last_session.state,
                    session_id=last_session.id,
                    request=last_session.title,
                )
                await ProjectMemoryStore(last_session.work_dir).append_journal(recap)
        _print_resume_hint(last_session)
        if last_session.is_empty():
            # Always clean up empty sessions regardless of exit code
            await _delete_empty_session(last_session)
        elif exit_code == ExitCode.SUCCESS:
            metadata = load_metadata()
            work_dir_meta = metadata.get_work_dir_meta(last_session.work_dir)
            if work_dir_meta is None:
                logger.warning(
                    "Work dir metadata missing when marking last session, recreating: {work_dir}",
                    work_dir=last_session.work_dir,
                )
                work_dir_meta = metadata.new_work_dir_meta(last_session.work_dir)
            work_dir_meta.last_session_id = last_session.id
            save_metadata(metadata)

    async def _reload_loop(session_id: str | None) -> tuple[str | None, int]:
        """Run the main loop, handling Reload/SwitchToWeb/SwitchToVis.

        Returns:
            (switch_target, exit_code) where switch_target is "web", "vis",
            or None if the session ended normally.
        """
        last_session: Session | None = None
        prefill_text: str | None = None
        try:
            while True:
                try:
                    last_session, exit_code = await _run(session_id, prefill_text=prefill_text)
                    break
                except Reload as e:
                    # Clean up old empty session when switching to a different session
                    old = e.source_session
                    if old is not None and old.id != e.session_id and old.is_empty():
                        await _delete_empty_session(old)
                        last_session = None
                    else:
                        last_session = e.source_session
                        # Only print resume hint when switching to a different session
                        # (not for same-session reloads like /model, /theme, /reload)
                        if old is not None and e.session_id is not None and old.id != e.session_id:
                            _print_resume_hint(old)
                    session_id = e.session_id
                    prefill_text = e.prefill_text
                    continue
                except SwitchToWeb as e:
                    if e.session_id is not None:
                        session = await Session.find(work_dir, e.session_id)
                        if session is not None:
                            await _post_run(session, ExitCode.SUCCESS)
                    return "web", ExitCode.SUCCESS
                except SwitchToVis as e:
                    if e.session_id is not None:
                        session = await Session.find(work_dir, e.session_id)
                        if session is not None:
                            await _post_run(session, ExitCode.SUCCESS)
                    return "vis", ExitCode.SUCCESS
            assert last_session is not None
            await _post_run(
                last_session,
                exit_code,
                cleanup_scratchpad=(ui == "print" and prompt is not None),
            )
            return None, exit_code
        except (SwitchToWeb, SwitchToVis):
            # Currently handled inside the loop (return), but re-raise explicitly
            # so the generic except below never treats them as unexpected errors.
            raise
        except Exception:
            # Best-effort cleanup: _latest_created_session is the session from
            # the most recent _run() call, which may have failed before returning.
            # last_session is from a *previous* iteration and must not be touched.
            if _latest_created_session is not None:
                _print_resume_hint(_latest_created_session)
                if _latest_created_session.is_empty():
                    with contextlib.suppress(Exception):
                        await _delete_empty_session(_latest_created_session)
            raise

    if _picker_mode:
        from prompt_toolkit.shortcuts.choice_input import ChoiceInput
        from rich.console import Console

        from pythinker_code.utils.datetime import format_relative_time

        async def _pick_session() -> str:
            all_sessions = await Session.list(work_dir)
            if not all_sessions:
                Console().print("[yellow]No sessions found for the working directory.[/yellow]")
                raise typer.Exit(0)

            choices: list[tuple[str, str]] = []
            for s in all_sessions:
                time_str = format_relative_time(s.updated_at)
                short_id = s.id[:8]
                name = _strip_session_id_suffix(s.title, s.id)
                label = f"{name} ({short_id}), {time_str}"
                choices.append((s.id, label))

            try:
                selection = await ChoiceInput(
                    message="Select a session to resume"
                    " (↑↓ navigate, Enter select, Ctrl+C cancel):",
                    options=choices,
                    default=choices[0][0],
                ).prompt_async()
            except (EOFError, KeyboardInterrupt):
                raise typer.Exit(0) from None

            if not selection:
                raise typer.Exit(0)

            return selection

        session_id = asyncio.run(_pick_session())

    # Ensure the terminal is restored to a sane state if the process is killed
    # by SIGTERM or SIGQUIT while the keyboard listener has raw mode active.
    # atexit covers SystemExit/normal exits; the signal handlers cover signals
    # whose default action would bypass atexit entirely.
    import atexit
    import signal as _signal

    from pythinker_code.utils.term import ensure_tty_sane

    atexit.register(ensure_tty_sane)

    def _restore_term_and_exit(signum: int, frame: object) -> None:
        ensure_tty_sane()
        _signal.signal(signum, _signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    # SIGQUIT is POSIX-only; the signal module does not expose it on Windows.
    _signals_to_trap = [_signal.SIGTERM]
    if hasattr(_signal, "SIGQUIT"):
        _signals_to_trap.append(_signal.SIGQUIT)

    for _sig in _signals_to_trap:
        with contextlib.suppress(OSError, ValueError):
            _signal.signal(_sig, _restore_term_and_exit)

    try:
        switch_target, exit_code = asyncio.run(_reload_loop(session_id))
    except (typer.BadParameter, typer.Exit):
        # Let Typer/Click format these errors (rich panel + correct exit code).
        raise
    except Exception as exc:
        import click

        if isinstance(exc, click.ClickException):
            # ClickException includes the errors Typer knows how to render; don't
            # wrap them, or we'd lose the standard error UI and exit codes.
            raise
        logger.exception("Fatal error when running CLI")
        if debug:
            import traceback

            # In debug mode, show full traceback for quick diagnosis.
            _emit_fatal_error(traceback.format_exc())
        else:
            from pythinker_code.share import get_share_dir

            log_path = get_share_dir() / "logs" / "pythinker.log"
            # In non-debug mode, print a concise error and point users to logs.
            _emit_fatal_error(
                f"{exc}\n"
                f"See logs: {log_path}\n"
                "Run with --debug for full traceback, or run pythinker export to share diagnostics."
            )
        raise typer.Exit(code=1) from exc
    if switch_target in ("web", "vis"):
        from pythinker_code.utils.logging import restore_stderr

        restore_stderr()

        # Restore default SIGINT handler and terminal state after the shell's
        # asyncio.run() to ensure Ctrl+C works in the uvicorn web server.
        import signal

        signal.signal(signal.SIGINT, signal.default_int_handler)

        from pythinker_code.utils.term import ensure_tty_sane

        ensure_tty_sane()

        if switch_target == "web":
            from pythinker_code.web.app import run_web_server

            run_web_server(open_browser=True)
        else:
            from pythinker_code.vis.app import run_vis_server

            run_vis_server(open_browser=True)
    elif exit_code != ExitCode.SUCCESS:
        raise typer.Exit(code=exit_code)


@cli.command()
def login(
    json: bool = typer.Option(
        False,
        "--json",
        help="Emit OAuth events as JSON lines.",
    ),
    browser: bool = typer.Option(False, "--browser", help="Use OpenAI ChatGPT browser login."),
    headless: bool = typer.Option(
        False, "--headless", help="Use OpenAI ChatGPT device-code login."
    ),
    api_key: bool = typer.Option(False, "--api-key", help="Configure OpenAI with an API key."),
    opencode_go: bool = typer.Option(
        False, "--opencode-go", help="Configure OpenCode Go with an API key."
    ),
    minimax: bool = typer.Option(False, "--minimax", help="Configure MiniMax with an API key."),
    deepseek: bool = typer.Option(False, "--deepseek", help="Configure DeepSeek with an API key."),
    anthropic: bool = typer.Option(
        False, "--anthropic", help="Configure Anthropic with an API key."
    ),
    openrouter: bool = typer.Option(
        False, "--openrouter", help="Configure OpenRouter with an API key."
    ),
    lm_studio: bool = typer.Option(
        False, "--lm-studio", "--lmstudio", help="Configure LM Studio as a local provider."
    ),
    ollama: bool = typer.Option(False, "--ollama", help="Configure Ollama as a local provider."),
    base_url: str = typer.Option(
        "",
        "--base-url",
        help="Override the default base URL for --lm-studio or --ollama.",
    ),
) -> None:
    """Login with OpenAI, OpenCode Go, MiniMax, DeepSeek, Anthropic, or local providers."""
    import asyncio

    from rich.console import Console
    from rich.status import Status

    async def _run() -> bool:
        selected_modes = sum(
            bool(value)
            for value in (
                browser,
                headless,
                api_key,
                opencode_go,
                minimax,
                deepseek,
                anthropic,
                openrouter,
                lm_studio,
                ollama,
            )
        )
        if selected_modes > 1:
            typer.echo(
                "Choose only one of --browser, --headless, --api-key, "
                "--opencode-go, --minimax, --deepseek, --anthropic, --openrouter, "
                "--lm-studio, or --ollama.",
                err=True,
            )
            return False

        config = load_config()
        if openrouter:
            key = typer.prompt("OpenRouter API key", hide_input=True).strip()
            events = login_openrouter_api_key(config, key)
        elif anthropic:
            key = typer.prompt("Anthropic API key", hide_input=True).strip()
            events = login_anthropic_api_key(config, key)
        elif deepseek:
            key = typer.prompt("DeepSeek API key", hide_input=True).strip()
            events = login_deepseek_api_key(config, key)
        elif minimax:
            key = typer.prompt("MiniMax API key", hide_input=True).strip()
            events = login_minimax_api_key(config, key)
        elif opencode_go:
            key = typer.prompt("OpenCode Go API key", hide_input=True).strip()
            events = login_opencode_go_api_key(config, key)
        elif api_key:
            key = typer.prompt("OpenAI API key", hide_input=True).strip()
            events = login_openai_api_key(config, key)
        elif lm_studio:
            events = login_lm_studio(
                config,
                base_url=(base_url.strip() or None),
            )
        elif ollama:
            events = login_ollama(
                config,
                base_url=(base_url.strip() or None),
            )
        elif headless:
            events = login_openai_headless(config)
        else:
            events = login_openai_browser(config, open_browser=True)

        if json:
            ok = True
            async for event in events:
                typer.echo(event.json)
                if event.type == "error":
                    ok = False
            return ok

        console = Console()
        ok = True
        status: Status | None = None
        try:
            async for event in events:
                if event.type == "waiting":
                    if status is None:
                        status = console.status("Waiting for OpenAI authorization.")
                        status.start()
                    continue
                if status is not None:
                    status.stop()
                    status = None
                match event.type:
                    case "error":
                        style = "red"
                    case "success":
                        style = "green"
                    case _:
                        style = None
                console.print(event.message, markup=False, style=style)
                if event.type == "error":
                    ok = False
        finally:
            if status is not None:
                status.stop()
        return ok

    ok = asyncio.run(_run())
    if not ok:
        raise typer.Exit(code=1)


@cli.command()
def logout(
    json: bool = typer.Option(
        False,
        "--json",
        help="Emit OAuth events as JSON lines.",
    ),
    opencode_go: bool = typer.Option(False, "--opencode-go", help="Logout from OpenCode Go."),
    minimax: bool = typer.Option(False, "--minimax", help="Logout from MiniMax."),
    deepseek: bool = typer.Option(False, "--deepseek", help="Logout from DeepSeek."),
    anthropic: bool = typer.Option(False, "--anthropic", help="Logout from Anthropic."),
    openrouter: bool = typer.Option(False, "--openrouter", help="Logout from OpenRouter."),
    lm_studio: bool = typer.Option(
        False, "--lm-studio", "--lmstudio", help="Logout from LM Studio."
    ),
    ollama: bool = typer.Option(False, "--ollama", help="Logout from Ollama."),
) -> None:
    """Logout from OpenAI, OpenCode Go, MiniMax, DeepSeek, Anthropic, or local providers."""
    import asyncio

    from rich.console import Console

    async def _run() -> bool:
        ok = True
        selected_modes = (opencode_go, minimax, deepseek, anthropic, openrouter, lm_studio, ollama)
        if sum(bool(v) for v in selected_modes) > 1:
            typer.echo(
                "Choose only one of --opencode-go, --minimax, --deepseek, "
                "--anthropic, --openrouter, --lm-studio, or --ollama.",
                err=True,
            )
            return False

        config = load_config()
        if openrouter:
            events = logout_openrouter(config)
        elif anthropic:
            events = logout_anthropic(config)
        elif deepseek:
            events = logout_deepseek(config)
        elif minimax:
            events = logout_minimax(config)
        elif opencode_go:
            events = logout_opencode_go(config)
        elif lm_studio:
            events = logout_lm_studio(config)
        elif ollama:
            events = logout_ollama(config)
        else:
            events = logout_openai(config)
        if json:
            async for event in events:
                typer.echo(event.json)
                if event.type == "error":
                    ok = False
            return ok

        console = Console()
        async for event in events:
            match event.type:
                case "error":
                    style = "red"
                case "success":
                    style = "green"
                case _:
                    style = None
            console.print(event.message, markup=False, style=style)
            if event.type == "error":
                ok = False
        return ok

    ok = asyncio.run(_run())
    if not ok:
        raise typer.Exit(code=1)


@cli.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def term(
    ctx: typer.Context,
) -> None:
    """Run Toad TUI backed by Pythinker CLI ACP server."""
    from .toad import run_term

    run_term(ctx)


@cli.command()
def acp():
    """Run Pythinker CLI ACP server."""
    from pythinker_code.acp import acp_main

    acp_main()


@cli.command(name="__background-task-worker", hidden=True)
def background_task_worker(
    task_dir: Annotated[Path, typer.Option("--task-dir")],
    heartbeat_interval_ms: Annotated[int, typer.Option("--heartbeat-interval-ms")] = 5000,
    control_poll_interval_ms: Annotated[int, typer.Option("--control-poll-interval-ms")] = 500,
    kill_grace_period_ms: Annotated[int, typer.Option("--kill-grace-period-ms")] = 2000,
    max_output_bytes: Annotated[int, typer.Option("--max-output-bytes")] = 0,
) -> None:
    """Run background task worker subprocess (internal)."""
    import asyncio

    from pythinker_code.background import run_background_task_worker
    from pythinker_code.utils.proctitle import set_process_title

    set_process_title("pythinker-code-bg-worker")

    from pythinker_code.app import enable_logging

    enable_logging(debug=False)
    asyncio.run(
        run_background_task_worker(
            task_dir,
            heartbeat_interval_ms=heartbeat_interval_ms,
            control_poll_interval_ms=control_poll_interval_ms,
            kill_grace_period_ms=kill_grace_period_ms,
            max_output_bytes=max_output_bytes,
        )
    )


@cli.command(name="__web-worker", hidden=True)
def web_worker(session_id: str) -> None:
    """Run web worker subprocess (internal)."""
    import asyncio
    from uuid import UUID

    from pythinker_code.utils.proctitle import set_process_title

    set_process_title("pythinker-code-worker")

    from pythinker_code.app import enable_logging
    from pythinker_code.web.runner.worker import run_worker

    try:
        parsed_session_id = UUID(session_id)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid session ID: {session_id}") from exc

    enable_logging(debug=False)
    asyncio.run(run_worker(parsed_session_id))


if __name__ == "__main__":
    import sys

    if "pythinker_code.cli" not in sys.modules:
        sys.modules["pythinker_code.cli"] = sys.modules[__name__]

    sys.exit(cli())
