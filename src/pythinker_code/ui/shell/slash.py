from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from prompt_toolkit.shortcuts.choice_input import ChoiceInput
from rich.markup import escape

from pythinker_code.auth.platforms import get_platform_name_for_provider, refresh_managed_models
from pythinker_code.cli import Reload, SwitchToVis, SwitchToWeb
from pythinker_code.config import load_config, save_config
from pythinker_code.exception import ConfigError
from pythinker_code.session import Session
from pythinker_code.soul.pythinkersoul import PythinkerSoul
from pythinker_code.ui.shell.console import console
from pythinker_code.ui.shell.mcp_status import render_mcp_console
from pythinker_code.ui.shell.task_browser import TaskBrowserApp
from pythinker_code.utils.changelog import CHANGELOG
from pythinker_code.utils.logging import logger
from pythinker_code.utils.slashcmd import SlashCommand, SlashCommandRegistry

if TYPE_CHECKING:
    from pythinker_code.ui.shell import Shell
    from pythinker_code.wire.types import MCPStatusSnapshot

type ShellSlashCmdFunc = Callable[[Shell, str], None | Awaitable[None]]
"""
A function that runs as a Shell-level slash command.

Raises:
    Reload: When the configuration should be reloaded.
"""


registry = SlashCommandRegistry[ShellSlashCmdFunc]()
shell_mode_registry = SlashCommandRegistry[ShellSlashCmdFunc]()


def _rich_escape(value: object) -> str:
    return escape(str(value))


def ensure_pythinker_soul(app: Shell) -> PythinkerSoul | None:
    if not isinstance(app.soul, PythinkerSoul):
        from pythinker_code.ui.theme import get_tui_tokens as _get_tui_tokens_local

        _t = _get_tui_tokens_local()
        console.print(f"[{_t.error}]PythinkerSoul required[/]")
        return None
    return app.soul


@registry.command(aliases=["quit"])
@shell_mode_registry.command(aliases=["quit"])
def exit(app: Shell, args: str):
    """Exit the application"""
    # should be handled by `Shell`
    raise NotImplementedError


SKILL_COMMAND_PREFIX = "skill:"

_KEYBOARD_SHORTCUTS = [
    ("Ctrl-X", "Toggle agent/shell mode"),
    ("Shift-Tab", "Toggle plan mode (read-only research)"),
    ("Ctrl-O", "Edit in external editor ($VISUAL/$EDITOR)"),
    ("Ctrl-J / Alt-Enter", "Insert newline"),
    ("Ctrl-V", "Paste (supports images)"),
    ("Ctrl-D", "Exit"),
    ("Ctrl-C", "Interrupt"),
]


@registry.command(aliases=["h", "?"])
@shell_mode_registry.command(aliases=["h", "?"])
def help(app: Shell, args: str):
    """Show help information"""
    from rich.console import Group, RenderableType
    from rich.text import Text

    from pythinker_code.ui.theme import get_tui_tokens, tui_rich_style
    from pythinker_code.utils.rich.columns import BulletColumns

    _tok = get_tui_tokens()

    def section(title: str, items: list[tuple[str, str]], color: str) -> BulletColumns:
        lines: list[RenderableType] = [Text.from_markup(f"[bold]{_rich_escape(title)}:[/bold]")]
        for name, desc in items:
            lines.append(
                BulletColumns(
                    Text.from_markup(
                        f"[{color}]{_rich_escape(name)}[/]: [{_tok.muted}]{_rich_escape(desc)}[/]"
                    ),
                    bullet_style=color,
                )
            )
        return BulletColumns(Group(*lines))

    renderables: list[RenderableType] = []
    renderables.append(
        BulletColumns(
            Group(
                Text.from_markup(
                    f"[{_tok.muted}]Help! I need somebody. Help! Not just anybody.[/]"
                ),
                Text.from_markup(f"[{_tok.muted}]Help! You know I need someone. Help![/]"),
                Text.from_markup(f"[{_tok.muted}]\u2015 The Beatles, [italic]Help![/italic][/]"),
            ),
            bullet_style=tui_rich_style("muted"),
        )
    )
    renderables.append(
        BulletColumns(
            Text(
                "Sure, Pythinker is ready to help! "
                "Just send me messages and I will help you get things done!"
            ),
        )
    )

    commands: list[SlashCommand[Any]] = []
    skills: list[SlashCommand[Any]] = []
    for cmd in app.available_slash_commands.values():
        if cmd.name.startswith(SKILL_COMMAND_PREFIX):
            skills.append(cmd)
        else:
            commands.append(cmd)

    renderables.append(section("Keyboard shortcuts", _KEYBOARD_SHORTCUTS, _tok.warning))
    renderables.append(
        section(
            "Slash commands",
            [(c.slash_name(), c.description) for c in sorted(commands, key=lambda c: c.name)],
            "blue",  # needs-human: blue has no exact brand token equivalent
        )
    )
    if skills:
        renderables.append(
            section(
                "Skills",
                [(c.slash_name(), c.description) for c in sorted(skills, key=lambda c: c.name)],
                _tok.info,
            )
        )

    with console.pager(styles=True):
        console.print(Group(*renderables))


@registry.command
@shell_mode_registry.command
def version(app: Shell, args: str):
    """Show version information"""
    from pythinker_code.constant import VERSION

    console.print(f"pythinker, version {VERSION}")


@registry.command
@shell_mode_registry.command
def agents(app: Shell, args: str):
    """List available subagent types"""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    labor_market = getattr(soul.runtime, "labor_market", None)
    builtin_types = getattr(labor_market, "builtin_types", {}) or {}
    type_defs = sorted(builtin_types.values(), key=lambda item: item.name)
    from pythinker_code.ui.theme import get_tui_tokens, tui_rich_style

    _tok = get_tui_tokens()

    if not type_defs:
        console.print(f"[{_tok.warning}]No subagents are registered for this agent.[/]")
        return

    table = Table.grid(expand=True)
    table.add_column(ratio=1, no_wrap=True)
    table.add_column(ratio=4)
    table.add_column(ratio=1, no_wrap=True)
    table.add_column(ratio=2, no_wrap=True)
    from rich.style import Style as _RichStyle

    table.add_row(
        Text("agent", style=tui_rich_style("info") + _RichStyle(bold=True)),
        Text("when to use", style="bold"),
        Text("model", style="bold"),
        Text("tools", style="bold"),
    )
    for type_def in type_defs:
        tool_policy = getattr(type_def, "tool_policy", None)
        tool_label = (
            f"allow {len(tool_policy.tools)}"
            if tool_policy is not None and tool_policy.mode == "allowlist"
            else "inherit"
        )
        table.add_row(
            Text(type_def.name, style=tui_rich_style("info")),
            Text(
                type_def.when_to_use or type_def.description or "—", style=tui_rich_style("muted")
            ),
            Text(type_def.default_model or "inherit", style=tui_rich_style("dim")),
            Text(tool_label, style=tui_rich_style("dim")),
        )

    footer = Text("Use the Agent tool with subagent_type=<agent>, or ask Pythinker to delegate.")
    footer.stylize(tui_rich_style("dim"))
    console.print(
        Panel(
            table,
            title=f"[bold {_tok.info}]Agents[/]",
            subtitle=footer,
            border_style=tui_rich_style("border"),
            box=box.ROUNDED,
        )
    )


@registry.command
async def model(app: Shell, args: str):
    """Switch LLM model or thinking mode"""
    from pythinker_code.llm import derive_model_capabilities
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok

    _t = _get_tok()

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    config = soul.runtime.config

    await refresh_managed_models(config)

    if not config.models:
        console.print(f'[{_t.warning}]No models configured, send "/login" to login.[/]')
        return

    if not config.is_from_default_location:
        console.print(
            f"[{_t.warning}]Model switching requires the default config file; "
            f"restart without --config/--config-file.[/]"
        )
        return

    # Find current model/thinking from runtime (may be overridden by --model/--thinking)
    curr_model_cfg = soul.runtime.llm.model_config if soul.runtime.llm else None
    curr_model_name: str | None = None
    if curr_model_cfg is not None:
        for name, model_cfg in config.models.items():
            if model_cfg == curr_model_cfg:
                curr_model_name = name
                break
    curr_thinking = soul.thinking

    # Step 1: Pick a model — single grouped picker with type-to-filter.
    from pythinker_code.ui.shell.model_picker import ModelPickerApp, build_provider_groups

    groups = build_provider_groups(
        config_models=config.models,
        label_for=_provider_label,
    )
    selected_model_name = await ModelPickerApp(
        groups=groups,
        current_model_name=curr_model_name,
    ).run()
    if not selected_model_name:
        return

    selected_model_cfg = config.models[selected_model_name]
    selected_provider = config.providers.get(selected_model_cfg.provider)
    if selected_provider is None:
        console.print(
            f"[{_t.error}]Provider not found: {_rich_escape(selected_model_cfg.provider)}[/]"
        )
        return

    # Step 2: Determine thinking mode
    capabilities = derive_model_capabilities(selected_model_cfg)
    new_thinking: bool

    if "always_thinking" in capabilities:
        new_thinking = True
    elif "thinking" in capabilities:
        from pythinker_code.ui.shell.selectors.thinking import ThinkingLevel, run_thinking_selector

        _curr_level: ThinkingLevel = "high" if curr_thinking else "off"
        _level = await run_thinking_selector(
            current_level=_curr_level,
            available_levels=["off", "minimal", "low", "medium", "high", "xhigh"],
        )
        if _level is None:
            return

        new_thinking = _level != "off"
    else:
        new_thinking = False

    # Check if anything changed
    model_changed = curr_model_name != selected_model_name
    thinking_changed = curr_thinking != new_thinking
    selected_display = selected_model_cfg.display_name or selected_model_cfg.model

    if not model_changed and not thinking_changed:
        console.print(
            f"[{_t.warning}]Already using {_rich_escape(selected_display)} "
            f"with thinking {'on' if new_thinking else 'off'}.[/]"
        )
        return

    # Save and reload
    prev_model = config.default_model
    prev_thinking = config.default_thinking
    config.default_model = selected_model_name
    config.default_thinking = new_thinking
    try:
        config_for_save = load_config()
        config_for_save.default_model = selected_model_name
        config_for_save.default_thinking = new_thinking
        save_config(config_for_save)
    except (ConfigError, OSError) as exc:
        config.default_model = prev_model
        config.default_thinking = prev_thinking
        console.print(f"[{_t.error}]Failed to save config: {_rich_escape(exc)}[/]")
        return

    from pythinker_code.telemetry import track

    if model_changed:
        track("model_switch", model=selected_model_name)
    if thinking_changed:
        track("thinking_toggle", enabled=new_thinking)
    console.print(
        f"[{_t.success}]Switched to {selected_display} "
        f"with thinking {'on' if new_thinking else 'off'}. "
        "Reloading...[/]"
    )

    # Pre-load LM Studio models so the user doesn't hit a 10-60s wait on
    # the first message. Fire-and-forget on error — Reload still proceeds.
    if model_changed and selected_model_cfg.provider == "managed:lm-studio":
        await _preload_lm_studio_model(selected_provider, selected_model_cfg.model)

    raise Reload(session_id=soul.runtime.session.id)


_PROVIDER_LABEL_OVERRIDES = {
    "managed:minimax-anthropic": "MiniMax",
    "managed:opencode-go-openai": "OpenCode Go (OpenAI)",
    "managed:opencode-go-anthropic": "OpenCode Go (Anthropic)",
    "managed:deepseek": "DeepSeek",
    "managed:anthropic": "Anthropic",
    "managed:openrouter": "OpenRouter",
}


def _provider_label(provider_key: str) -> str:
    if name := get_platform_name_for_provider(provider_key):
        return name
    if name := _PROVIDER_LABEL_OVERRIDES.get(provider_key):
        return name
    # Fall back: strip "managed:" prefix and humanize.
    raw = provider_key.removeprefix("managed:")
    return raw.replace("-", " ").title() if raw else provider_key


async def _preload_lm_studio_model(provider: Any, model_id: str) -> None:
    """Best-effort: ask LM Studio to load the model now."""
    from rich.status import Status

    from pythinker_code.auth.lm_studio import request_lm_studio_load
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_lms

    _t_lms = _get_tok_lms()

    base_url = provider.base_url
    api_key = provider.api_key.get_secret_value()
    status_msg = f"Pre-loading {model_id} in LM Studio (this may take a moment)..."
    status = Status(status_msg, console=console)
    status.start()
    try:
        result = await request_lm_studio_load(base_url=base_url, model_id=model_id, api_key=api_key)
        status.stop()
        console.print(
            f"[dim]LM Studio loaded {model_id} in "
            f"{result.load_time_seconds:.1f}s (status={result.status}).[/dim]"
        )
    except Exception as exc:
        status.stop()
        console.print(
            f"[{_t_lms.warning}]LM Studio pre-load failed for {model_id}: {exc}[/]\n"
            "[dim]The chat will still try the model on first message.[/dim]"
        )


@registry.command
@shell_mode_registry.command
async def editor(app: Shell, args: str):
    """Set default external editor for Ctrl-O"""
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_editor
    from pythinker_code.utils.editor import get_editor_command

    _t_ed = _get_tok_editor()

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    config = soul.runtime.config
    config_file = config.source_file
    if config_file is None:
        console.print(
            f"[{_t_ed.warning}]Editor switching is unavailable with inline --config; "
            f"use --config-file to persist this setting.[/]"
        )
        return

    current_editor = config.default_editor

    # If args provided directly, use as editor command
    if args.strip():
        new_editor = args.strip()
    else:
        options: list[tuple[str, str]] = [
            ("code --wait", "VS Code (code --wait)"),
            ("vim", "Vim"),
            ("nano", "Nano"),
            ("", "Auto-detect (use $VISUAL/$EDITOR)"),
        ]
        # Mark current selection
        options = [
            (val, label + (" ← current" if val == current_editor else "")) for val, label in options
        ]

        try:
            choice = cast(
                str | None,
                await ChoiceInput(
                    message="Select an editor (↑↓ navigate, Enter select, Ctrl+C cancel):",
                    options=options,
                    default=(
                        current_editor
                        if current_editor in {v for v, _ in options}
                        else "code --wait"
                    ),
                ).prompt_async(),
            )
        except (EOFError, KeyboardInterrupt):
            return

        if choice is None:
            return
        new_editor = choice

    # Validate the editor binary is available
    if new_editor:
        import shlex
        import shutil

        try:
            parts = shlex.split(new_editor)
        except ValueError:
            console.print(f"[{_t_ed.error}]Invalid editor command: {_rich_escape(new_editor)}[/]")
            return

        binary = parts[0]
        if not shutil.which(binary):
            console.print(
                f"[{_t_ed.warning}]Warning: '{_rich_escape(binary)}' not found in PATH. "
                f"Saving anyway — make sure it's installed before using Ctrl-O.[/]"
            )

    if new_editor == current_editor:
        editor_label = _rich_escape(new_editor or "auto-detect")
        console.print(f"[{_t_ed.warning}]Editor is already set to: {editor_label}[/]")
        return

    # Save to disk
    try:
        config_for_save = load_config(config_file)
        config_for_save.default_editor = new_editor
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[{_t_ed.error}]Failed to save config: {_rich_escape(exc)}[/]")
        return

    # Sync in-memory config so Ctrl-O picks it up immediately
    config.default_editor = new_editor

    if new_editor:
        console.print(f"[{_t_ed.success}]Editor set to: {_rich_escape(new_editor)}[/]")
    else:
        resolved = get_editor_command()
        label = " ".join(resolved) if resolved else "none"
        console.print(
            f"[{_t_ed.success}]Editor set to auto-detect (resolved: {_rich_escape(label)})[/]"
        )


@registry.command(aliases=["release-notes"])
@shell_mode_registry.command(aliases=["release-notes"])
def changelog(app: Shell, args: str):
    """Show release notes"""
    from rich.console import Group, RenderableType
    from rich.text import Text

    from pythinker_code.ui.theme import get_tui_tokens, tui_rich_style
    from pythinker_code.utils.rich.columns import BulletColumns

    _tok = get_tui_tokens()
    renderables: list[RenderableType] = []
    for ver, entry in CHANGELOG.items():
        title = f"[bold]{_rich_escape(ver)}[/bold]"
        if entry.description:
            title += f": {_rich_escape(entry.description)}"

        lines: list[RenderableType] = [Text.from_markup(title)]
        for item in entry.entries:
            if item.lower().startswith("lib:"):
                continue
            lines.append(
                BulletColumns(
                    Text.from_markup(f"[{_tok.muted}]{_rich_escape(item)}[/]"),
                    bullet_style=tui_rich_style("muted"),
                ),
            )
        renderables.append(BulletColumns(Group(*lines)))

    with console.pager(styles=True):
        console.print(Group(*renderables))


def _feedback_destination(soul: PythinkerSoul) -> tuple[str, dict[str, str]] | None:
    """Resolve the endpoint and headers for explicit user feedback submissions."""
    import os

    from pythinker_code.auth import PYTHINKER_CODE_PLATFORM_ID
    from pythinker_code.auth.platforms import get_platform_by_id, managed_provider_key

    headers: dict[str, str] = {}
    feedback_config = soul.runtime.config.feedback

    endpoint_url = os.getenv("PYTHINKER_FEEDBACK_URL", "").strip()
    if not endpoint_url:
        endpoint_url = feedback_config.endpoint_url.strip()

    if endpoint_url:
        if feedback_config.custom_headers:
            headers.update(feedback_config.custom_headers)
        api_key = os.getenv("PYTHINKER_FEEDBACK_API_KEY", "").strip()
        if not api_key and feedback_config.api_key is not None:
            api_key = feedback_config.api_key.get_secret_value()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return endpoint_url, headers

    pythinker_platform = get_platform_by_id(PYTHINKER_CODE_PLATFORM_ID)
    if pythinker_platform is None:
        return None

    provider = soul.runtime.config.providers.get(managed_provider_key(PYTHINKER_CODE_PLATFORM_ID))
    if provider is not None:
        if provider.custom_headers:
            headers.update(provider.custom_headers)
        api_key = provider.api_key.get_secret_value()
        if provider.oauth is not None:
            api_key = soul.runtime.oauth.resolve_api_key(provider.api_key, provider.oauth)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    return f"{pythinker_platform.base_url.rstrip('/')}/feedback", headers


@registry.command
@shell_mode_registry.command
def feedback(app: Shell, args: str):
    """Open a GitHub issue to submit feedback or report a bug"""
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_fb
    from pythinker_code.utils.term import open_url_in_browser

    _t_fb = _get_tok_fb()

    ISSUE_URL = "https://github.com/TechMatrix-labs/pythinker-code/issues/new/choose"

    if open_url_in_browser(ISSUE_URL):
        console.print(f"[{_t_fb.success}]Opening GitHub issues in your browser...[/]")
    else:
        console.print(f"Please open: [underline]{ISSUE_URL}[/underline]")


@registry.command(aliases=["report-error", "report"])
@shell_mode_registry.command(aliases=["report-error", "report"])
async def report_error(app: Shell, args: str):
    """Submit a report about an error you hit, with a snapshot of recent failures."""
    import platform

    import aiohttp

    from pythinker_code.constant import VERSION
    from pythinker_code.telemetry.errors import clear_recent_errors, recent_errors
    from pythinker_code.ui.shell.oauth import current_model_key
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_re
    from pythinker_code.utils.aiohttp import new_client_session
    from pythinker_code.utils.term import open_url_in_browser

    _t_re = _get_tok_re()

    ISSUE_URL = "https://github.com/TechMatrix-labs/pythinker-code/issues"

    def _fallback_to_issues() -> None:
        if not open_url_in_browser(ISSUE_URL):
            console.print(f"Please file the report at [underline]{ISSUE_URL}[/underline].")

    soul = ensure_pythinker_soul(app)
    if soul is None:
        _fallback_to_issues()
        return

    destination = _feedback_destination(soul)
    if destination is None:
        _fallback_to_issues()
        return
    feedback_url, headers = destination

    errors = recent_errors()
    if errors:
        console.print("[bold]Recent errors this session (most recent last):[/bold]")
        for i, err in enumerate(errors, start=1):
            tool_part = f" (tool={_rich_escape(err.tool)})" if err.tool else ""
            console.print(
                f"  [dim]{i}.[/dim] [{_t_re.info}]{_rich_escape(err.site)}[/]"
                f"{tool_part}: {_rich_escape(err.exc_class)}"
            )
    else:
        console.print(
            f"[{_t_re.muted}]No errors recorded this session. "
            f"You can still attach a comment describing what went wrong.[/]"
        )

    from prompt_toolkit import PromptSession

    prompt_session: PromptSession[str] = PromptSession()
    try:
        comment = await prompt_session.prompt_async("Describe what went wrong (Ctrl-C to cancel): ")
    except (EOFError, KeyboardInterrupt):
        console.print(f"[{_t_re.muted}]Report cancelled.[/]")
        return

    comment = comment.strip()
    if not comment and not errors:
        console.print(f"[{_t_re.warning}]Nothing to report. Cancelled.[/]")
        return

    payload = {
        "session_id": soul.runtime.session.id,
        "type": "error",
        "content": comment,
        "version": VERSION,
        "os": f"{platform.system()} {platform.release()}",
        "model": current_model_key(soul),
        "recent_errors": [
            {
                "timestamp": err.timestamp,
                "site": err.site,
                "exc_class": err.exc_class,
                "message": err.message,
                "tool": err.tool,
            }
            for err in errors
        ],
    }

    with console.status(f"[{_t_re.info}]Submitting error report...[/]"):
        try:
            async with (
                new_client_session() as session,
                session.post(
                    feedback_url,
                    json=payload,
                    headers=headers,
                    raise_for_status=True,
                ),
            ):
                pass
            from pythinker_code.telemetry import track

            track("error_report_submitted", error_count=len(errors), has_comment=bool(comment))
            clear_recent_errors()
            console.print(
                f"[{_t_re.success}]Error report submitted. Session ID: {soul.runtime.session.id}[/]"
            )
        except TimeoutError:
            console.print(f"[{_t_re.error}]Submission timed out.[/]")
            _fallback_to_issues()
        except aiohttp.ClientError as e:
            status = getattr(e, "status", None)
            msg = (
                f"Failed to submit error report (HTTP {status})."
                if status
                else "Network error, failed to submit error report."
            )
            console.print(f"[{_t_re.error}]{msg}[/]")
            _fallback_to_issues()


@registry.command(aliases=["reset"])
async def clear(app: Shell, args: str):
    """Clear the context"""
    if ensure_pythinker_soul(app) is None:
        return
    from pythinker_code.telemetry import track

    track("clear")
    await app.run_soul_command("/clear")
    raise Reload()


@registry.command
async def new(app: Shell, args: str):
    """Start a new session"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    current_session = soul.runtime.session
    work_dir = current_session.work_dir
    # Clean up the current session if it has no content, so that chaining
    # /new commands (or switching away before the first message) does not
    # leave orphan empty session directories on disk.
    if current_session.is_empty():
        await current_session.delete()
    session = await Session.create(work_dir)
    from pythinker_code.telemetry import track

    track("session_new")
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_new

    console.print(f"[{_get_tok_new().success}]New session created. Switching...[/]")
    raise Reload(session_id=session.id)


@registry.command(name="title", aliases=["rename"])
async def title(app: Shell, args: str):
    """Set or show the session title"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    session = soul.runtime.session
    if not args.strip():
        console.print(f"Session title: [bold]{_rich_escape(session.title)}[/bold]")
        return

    from pythinker_code.session_state import load_session_state, save_session_state

    new_title = args.strip()[:200]
    # Read-modify-write: load fresh state to avoid overwriting concurrent web changes
    fresh = load_session_state(session.dir)
    fresh.custom_title = new_title
    fresh.title_generated = True
    save_session_state(fresh, session.dir)
    session.state.custom_title = new_title
    session.state.title_generated = True
    session.title = new_title
    from pythinker_code.scratchpad import append_scratch_event_sync, rename_session_scratch
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_title

    rename_session_scratch(session.work_dir, session_id=session.id, session_title=new_title)
    await asyncio.to_thread(
        append_scratch_event_sync,
        session.work_dir,
        session_id=session.id,
        session_title=new_title,
        title="session title set",
        details=[f"title: {new_title}"],
        labels=[f"scope:{new_title}"],
    )
    console.print(f"[{_get_tok_title().success}]Session title set to: {_rich_escape(new_title)}[/]")


@registry.command(name="sessions", aliases=["resume", "session"])
async def list_sessions(app: Shell, args: str):
    """List sessions and resume optionally"""
    import shlex

    from pythinker_code.ui.shell.session_picker import SessionPickerApp

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    current_session = soul.runtime.session
    result = await SessionPickerApp(
        work_dir=current_session.work_dir,
        current_session=current_session,
    ).run()

    if result is None:
        return

    selection, selected_work_dir = result

    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_sess

    _t_sess = _get_tok_sess()
    if selection == current_session.id:
        console.print(f"[{_t_sess.warning}]You are already in this session.[/]")
        return

    if selected_work_dir != current_session.work_dir:
        cmd = f"pythinker --work-dir {shlex.quote(str(selected_work_dir))} --session {selection}"
        console.print(
            f"[{_t_sess.warning}]Session is in a different directory. Run:[/]\n"
            f"  {_rich_escape(cmd)}"
        )
        return

    from pythinker_code.telemetry import track

    track("session_resume")
    console.print(f"[{_t_sess.success}]Switching to session {_rich_escape(selection)}...[/]")
    raise Reload(session_id=selection)


@registry.command(name="task", aliases=["tasks"])
@shell_mode_registry.command(name="task", aliases=["tasks"])
async def task(app: Shell, args: str):
    """Browse and manage background tasks"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_task

    _t_task = _get_tok_task()
    if args.strip():
        console.print(f'[{_t_task.warning}]Usage: "/task" opens the interactive task browser.[/]')
        return
    if soul.runtime.role != "root":
        console.print(
            f"[{_t_task.warning}]Background tasks are only available from the root agent.[/]"
        )
        return

    await TaskBrowserApp(soul).run()


@registry.command(aliases=["color"])
@shell_mode_registry.command(aliases=["color"])
async def theme(app: Shell, args: str) -> None:
    """Switch terminal color theme — interactive picker when no args given"""
    from pythinker_code.ui.theme import get_active_theme
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_theme

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    _t_theme = _get_tok_theme()
    current = get_active_theme()
    arg = args.strip().lower()

    if not arg:
        from pythinker_code.ui.shell.selectors.theme import run_theme_selector

        chosen = await run_theme_selector(
            current_theme=current,
            available_themes=["dark", "light"],
        )
        if chosen is None or chosen == current:
            return
        arg = chosen

    if arg not in ("dark", "light"):
        console.print(
            f"[{_t_theme.error}]Unknown theme: {_rich_escape(arg)}. Use 'dark' or 'light'.[/]"
        )
        return

    if arg == current:
        console.print(f"[{_t_theme.warning}]Already using {_rich_escape(arg)} theme.[/]")
        return

    config_file = soul.runtime.config.source_file
    if config_file is None:
        console.print(
            f"[{_t_theme.warning}]Theme switching requires a config file; "
            f"restart without --config to persist this setting.[/]"
        )
        return

    try:
        config_for_save = load_config(config_file)
        config_for_save.theme = arg  # type: ignore[assignment]
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[{_t_theme.error}]Failed to save config: {_rich_escape(exc)}[/]")
        return

    from pythinker_code.telemetry import track

    track("theme_switch", theme=arg)
    console.print(f"[{_t_theme.success}]Switched to {_rich_escape(arg)} theme. Reloading...[/]")
    raise Reload(session_id=soul.runtime.session.id)


@registry.command
@shell_mode_registry.command
async def thinking(app: Shell, args: str) -> None:
    """Switch thinking level — interactive picker"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    from pythinker_code.ui.shell.selectors.thinking import ThinkingLevel, run_thinking_selector
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_think

    _t_think = _get_tok_think()

    curr_level: ThinkingLevel = "high" if soul.thinking else "off"
    level = await run_thinking_selector(
        current_level=curr_level,
        available_levels=["off", "minimal", "low", "medium", "high", "xhigh"],
    )
    if level is None:
        return

    new_thinking = level != "off"
    if new_thinking == soul.thinking:
        console.print(f"[{_t_think.warning}]Thinking setting unchanged.[/]")
        return

    config_file = soul.runtime.config.source_file
    if config_file is None:
        console.print(
            f"[{_t_think.warning}]Thinking requires a config file; "
            f"restart without --config to persist this setting.[/]"
        )
        return

    try:
        config_for_save = load_config(config_file)
        config_for_save.default_thinking = new_thinking
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[{_t_think.error}]Failed to save config: {_rich_escape(exc)}[/]")
        return

    from pythinker_code.telemetry import track

    track("thinking_toggle", enabled=new_thinking)
    console.print(
        f"[{_t_think.success}]Thinking {'enabled' if new_thinking else 'disabled'}. Reloading...[/]"
    )
    raise Reload(session_id=soul.runtime.session.id)


@registry.command(aliases=["keybindings"])
@shell_mode_registry.command(aliases=["keybindings"])
def keys(app: Shell, args: str):
    """List keyboard shortcuts (semantic keymap)"""
    from rich.console import Group, RenderableType
    from rich.table import Table
    from rich.text import Text

    from pythinker_code.ui.shell.keymap import keybinding_help
    from pythinker_code.ui.theme import get_tui_tokens, tui_rich_style

    _tok = get_tui_tokens()
    bindings = keybinding_help()
    if not bindings:
        console.print(f"[{_tok.warning}]No keybindings registered.[/]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Shortcut", style="bold", no_wrap=True)
    table.add_column("Action", style=tui_rich_style("info"))
    table.add_column("Where", style="dim", no_wrap=True)

    for binding in bindings:
        table.add_row("/".join(binding.keys), binding.description, binding.context)

    blocks: list[RenderableType] = [
        Text.from_markup("[bold]Keyboard shortcuts[/bold]"),
        table,
        Text.from_markup(
            f"[{_tok.muted}]Tip: press ? on an empty prompt for the compact overlay.[/]"
        ),
    ]
    console.print(Group(*blocks))


@registry.command
@shell_mode_registry.command
def tui(app: Shell, args: str):
    """Show or set the TUI style: card or pythinker"""
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_tui
    from pythinker_code.ui.tui_config import get_active_tui_style, set_active_tui_style

    _t_tui = _get_tok_tui()

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    current = get_active_tui_style()
    arg = args.strip().lower()

    # Accept "/tui card", "/tui style card", "/tui set card" — all natural shapes.
    parts = arg.split()
    if parts and parts[0] in ("style", "set"):
        parts = parts[1:]
    target = parts[0] if parts else ""

    if not target:
        console.print(f"Current TUI style: [bold]{_rich_escape(current)}[/bold]")
        console.print(f"[{_t_tui.muted}]Usage: /tui card | /tui pythinker[/]")
        return

    if target not in ("card", "pythinker"):
        target_label = _rich_escape(target)
        console.print(
            f"[{_t_tui.error}]Unknown style: {target_label}. Use 'card' or 'pythinker'.[/]"
        )
        return

    if target == current:
        console.print(f"[{_t_tui.warning}]Already using {_rich_escape(target)} style.[/]")
        return

    config_file = soul.runtime.config.source_file
    if config_file is None:
        # Apply in-memory only — useful for one-off testing without a persisted config.
        set_active_tui_style(target)
        console.print(
            f"[{_t_tui.success}]Switched to {target} style for this session "
            "(no config file to persist).[/]"
        )
        return

    try:
        config_for_save = load_config(config_file)
        config_for_save.tui.style = target  # type: ignore[assignment]
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[{_t_tui.error}]Failed to save config: {_rich_escape(exc)}[/]")
        return

    set_active_tui_style(target)
    if target == "card":
        # Make sure renderers are present immediately for current session.
        from pythinker_code.ui.shell.tool_renderers import register_builtin_renderers

        register_builtin_renderers()

    from pythinker_code.telemetry import track

    track("tui_style_switch", style=target)
    console.print(f"[{_t_tui.success}]Switched to {_rich_escape(target)} style. Reloading...[/]")
    raise Reload(session_id=soul.runtime.session.id)


@registry.command
@shell_mode_registry.command
async def settings(app: Shell, args: str):
    """Open the interactive settings panel; use `/settings show` for read-only view"""
    from rich.console import Group, RenderableType
    from rich.table import Table
    from rich.text import Text

    from pythinker_code.ui.theme import get_active_theme, tui_rich_style
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_set
    from pythinker_code.ui.tui_config import get_active_tui_style

    _t_set = _get_tok_set()

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    config = soul.runtime.config
    mode = args.strip().lower()

    def print_settings_table() -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style=tui_rich_style("info"), no_wrap=True)
        table.add_column()

        table.add_row("Theme", get_active_theme())
        table.add_row("TUI style", get_active_tui_style())
        table.add_row("Default model", config.default_model or "(none)")
        table.add_row("Telemetry", "on" if config.telemetry else "off")
        table.add_row("Default thinking", "on" if config.default_thinking else "off")
        table.add_row("Show thinking stream", "on" if config.show_thinking_stream else "off")
        table.add_row("Default yolo", "on" if config.default_yolo else "off")
        table.add_row("Default plan mode", "on" if config.default_plan_mode else "off")
        if config.source_file is not None:
            table.add_row("Config file", str(config.source_file))
        else:
            table.add_row("Config file", "(none — runtime overrides only)")

        blocks: list[RenderableType] = [Text.from_markup("[bold]Settings[/bold]"), table]
        console.print(Group(*blocks))
        console.print(
            f"[{_t_set.muted}]Tip: /settings opens the interactive panel; "
            f"/theme, /tui, /model, /keys for related controls.[/]"
        )

    if mode in {"show", "list", "view"}:
        print_settings_table()
        return
    if mode:
        console.print(f"[{_t_set.warning}]Usage: /settings [show|list][/]")
        return

    config_file = config.source_file
    if config_file is None:
        print_settings_table()
        console.print(
            f"[{_t_set.warning}]Interactive settings require a config file; "
            f"restart without --config text to persist settings.[/]"
        )
        return

    from pythinker_code.ui.shell.selectors.settings import (
        apply_settings_changes,
        run_settings_selector,
    )

    try:
        config_for_save = load_config(config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[{_t_set.error}]Failed to load config: {_rich_escape(exc)}[/]")
        return

    changes = await run_settings_selector(config_for_save)
    if changes is None:
        return

    changed_ids = apply_settings_changes(config_for_save, changes)
    if not changed_ids:
        console.print(f"[{_t_set.warning}]Settings unchanged.[/]")
        return

    try:
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[{_t_set.error}]Failed to save config: {_rich_escape(exc)}[/]")
        return

    from pythinker_code.telemetry import track

    track("settings_update", changed=",".join(changed_ids), count=len(changed_ids))
    console.print(f"[{_t_set.success}]Updated {len(changed_ids)} setting(s). Reloading...[/]")
    raise Reload(session_id=soul.runtime.session.id)


@registry.command(aliases=["rewind-files"])
@shell_mode_registry.command(aliases=["rewind-files"])
def restore(app: Shell, args: str) -> None:
    """List or restore file mutation checkpoints"""
    from rich.table import Table

    from pythinker_code.file_restore import (
        list_file_restore_points,
        restore_file_restore_point,
    )
    from pythinker_code.ui.theme import get_tui_tokens, tui_rich_style

    _tok = get_tui_tokens()
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    session = soul.runtime.session
    arg = args.strip()
    if not arg:
        points = list_file_restore_points(session, limit=20)
        if not points:
            console.print(f"[{_tok.warning}]No file restore points in this session.[/]")
            return
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("ID", style=tui_rich_style("info"), no_wrap=True)
        table.add_column("Tool", no_wrap=True)
        table.add_column("Path")
        table.add_column("State", no_wrap=True)
        for point in points:
            state = "modified" if point.existed else "created"
            table.add_row(point.id, point.tool_name, str(point.path), state)
        console.print(table)
        console.print(f"[{_tok.muted}]Run /restore <id> or /restore latest.[/]")
        return

    if arg == "latest":
        points = list_file_restore_points(session, limit=1)
        if not points:
            console.print(f"[{_tok.warning}]No file restore points in this session.[/]")
            return
        restore_id = points[0].id
    else:
        restore_id = arg

    try:
        point = restore_file_restore_point(session, restore_id)
    except FileNotFoundError:
        console.print(f"[{_tok.error}]Restore point not found: {_rich_escape(restore_id)}[/]")
        return
    except OSError as exc:
        console.print(
            f"[{_tok.error}]Failed to restore {_rich_escape(restore_id)}: {_rich_escape(exc)}[/]"
        )
        return

    action = "restored" if point.existed else "removed"
    console.print(
        f"[{_tok.success}]File {action} from restore point {_rich_escape(point.id)}: "
        f"{_rich_escape(point.path)}[/]"
    )


@registry.command
@shell_mode_registry.command
def trust(app: Shell, args: str) -> None:
    """Show or update workspace trust safe mode"""
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_trust

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    _t_trust = _get_tok_trust()
    state = soul.runtime.session.state.trust
    mode = args.strip().lower()
    if mode in {"on", "yes", "trust"}:
        state.trusted = True
        state.safe_mode = False
        soul.runtime.approval.set_safe_mode(False)
        soul.runtime.session.save_state()
        console.print(
            f"[{_t_trust.success}]Workspace trusted. Safe mode disabled for this session.[/]"
        )
        return
    if mode in {"off", "no", "untrust", "safe"}:
        state.trusted = False
        state.safe_mode = True
        soul.runtime.approval.set_safe_mode(True)
        soul.runtime.approval.set_yolo(False)
        soul.runtime.approval.set_auto(False)
        soul.runtime.session.state.approval.auto_approve_actions.clear()
        soul.runtime.session.save_state()
        console.print(
            f"[{_t_trust.warning}]Workspace untrusted. Safe mode enabled; "
            "auto-approval is disabled.[/]"
        )
        return
    if mode:
        console.print(f"[{_t_trust.warning}]Usage: /trust [on|off][/]")
        return

    status = "trusted" if state.trusted else "untrusted"
    safe = "on" if state.safe_mode else "off"
    console.print(f"Workspace trust: [bold]{status}[/bold]  safe mode: [bold]{safe}[/bold]")


@registry.command
@shell_mode_registry.command
async def worklog(app: Shell, args: str) -> None:
    """Show a compact session activity timeline"""
    from rich.table import Table

    from pythinker_code.file_restore import list_file_restore_points

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    counts: dict[str, int] = {}
    recent: list[str] = []
    try:
        async for record in soul.runtime.session.wire_file.iter_records():
            event = type(record.to_wire_message()).__name__
            counts[event] = counts.get(event, 0) + 1
            recent.append(event)
            recent = recent[-12:]
    except FileNotFoundError:
        pass

    from pythinker_code.ui.theme import get_tui_tokens, tui_rich_style

    _tok = get_tui_tokens()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Signal", style=tui_rich_style("info"))
    table.add_column("Count", justify="right")
    for key in sorted(counts):
        table.add_row(key, str(counts[key]))
    if counts:
        console.print(table)
        console.print(f"[{_tok.muted}]Recent: {_rich_escape(' -> '.join(recent))}[/]")
    else:
        console.print(f"[{_tok.warning}]No worklog events recorded yet.[/]")

    restore_points = list_file_restore_points(soul.runtime.session, limit=5)
    if restore_points:
        console.print("[bold]Recent restore points:[/bold]")
        for point in restore_points:
            console.print(
                f"  [{_tok.info}]{_rich_escape(point.id)}[/] "
                f"{_rich_escape(point.tool_name)} {_rich_escape(point.path)}"
            )


@registry.command
@shell_mode_registry.command
def context(app: Shell, args: str) -> None:
    """Show context, checkpoint, and compaction status"""
    from rich.table import Table

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    from pythinker_code.ui.theme import get_tui_tokens, tui_rich_style

    _tok = get_tui_tokens()

    status = soul.status
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style=tui_rich_style("info"), no_wrap=True)
    table.add_column()
    table.add_row("Tokens", str(status.context_tokens or 0))
    table.add_row("Window", str(status.max_context_tokens or 0))
    context_usage_label = f"{status.context_usage:.1f}%"
    table.add_row("Usage", context_usage_label)
    table.add_row("Checkpoints", str(soul.context.n_checkpoints))
    table.add_row("Plan mode", "on" if soul.plan_mode else "off")
    table.add_row("Context file", str(soul.runtime.session.context_file))
    console.print(table)
    console.print(f"[{_tok.muted}]Use /compact [focus] to summarize old context.[/]")


@registry.command
@shell_mode_registry.command
def tools(app: Shell, args: str) -> None:
    """List available tools and permission posture"""
    from rich.table import Table

    from pythinker_code.soul.permission import permission_profile_for_runtime
    from pythinker_code.ui.theme import tui_rich_style

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    profile = permission_profile_for_runtime(soul.runtime)
    console.print(
        f"Permission profile: [bold]{profile.name}[/bold] "
        f"({profile.description}; file mutations={'yes' if profile.allow_file_mutation else 'no'}, "
        f"shell mutations={'yes' if profile.allow_shell_mutation else 'no'})"
    )

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Tool", style=tui_rich_style("info"), no_wrap=True)
    table.add_column("Description")
    for tool in sorted(soul.agent.toolset.tools, key=lambda item: item.name):
        desc = " ".join((tool.description or "").split())
        if len(desc) > 100:
            desc = desc[:97] + "..."
        table.add_row(tool.name, desc)
    console.print(table)
    if args.strip().lower() == "audit":
        from pythinker_code.ui.theme import get_tui_tokens as _get_tok_tools

        _t_tools = _get_tok_tools()
        console.print(
            f"[{_t_tools.muted}]Audit: external MCP/wire/plugin tools are blocked in read-only, "
            f"plan, review, and verify profiles unless their side effects are known.[/]"
        )


@registry.command(aliases=["a11y"])
@shell_mode_registry.command(aliases=["a11y"])
def accessibility(app: Shell, args: str) -> None:
    """Show or update accessibility/plain-output preferences"""
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_a11y

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    _t_a11y = _get_tok_a11y()

    state = soul.runtime.session.state.accessibility
    mode = args.strip().lower()
    match mode:
        case "plain" | "on":
            state.plain_output = True
        case "rich" | "off":
            state.plain_output = False
        case "no-animation" | "no-animations":
            state.animations = False
        case "animation" | "animations":
            state.animations = True
        case "ascii":
            state.symbols = "ascii"
        case "unicode":
            state.symbols = "unicode"
        case "":
            pass
        case _:
            console.print(
                f"[{_t_a11y.warning}]Usage: /accessibility "
                "[plain|rich|no-animation|animation|ascii|unicode][/]"
            )
            return
    if mode:
        soul.runtime.session.save_state()
    console.print(
        "Accessibility: "
        f"plain_output=[bold]{'on' if state.plain_output else 'off'}[/bold] "
        f"animations=[bold]{'on' if state.animations else 'off'}[/bold] "
        f"symbols=[bold]{state.symbols}[/bold]"
    )


@registry.command
def web(app: Shell, args: str):
    """Open Pythinker Web UI in browser"""
    from pythinker_code.telemetry import track

    track("web_opened")
    soul = ensure_pythinker_soul(app)
    session_id = soul.runtime.session.id if soul else None
    raise SwitchToWeb(session_id=session_id)


@registry.command
def vis(app: Shell, args: str):
    """Open Pythinker Agent Tracing Visualizer in browser"""
    from pythinker_code.telemetry import track

    track("vis_opened")
    soul = ensure_pythinker_soul(app)
    session_id = soul.runtime.session.id if soul else None
    raise SwitchToVis(session_id=session_id)


@registry.command(name="memory", aliases=["mem"])
async def show_memory(app: Shell, args: str):
    """Show project memory, or manage the approval-gated memory inbox."""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    from pythinker_code.project_memory import ProjectMemoryStore

    store = ProjectMemoryStore(soul.runtime.session.work_dir)
    parts = args.split()
    if parts and parts[0] == "inbox":
        memory_config = getattr(soul.runtime.config, "memory", None)
        if not getattr(memory_config, "consolidation", False):
            console.print(
                "Memory inbox consolidation is disabled. "
                "Set `memory.consolidation = true` in your config to enable it."
            )
            return
        from pythinker_code.memory.consolidation import (
            approve_inbox_candidate,
            generate_inbox_candidates,
            list_inbox_candidates,
            reject_inbox_candidate,
        )

        action = parts[1] if len(parts) > 1 else "list"
        if action == "scan":
            created = await generate_inbox_candidates(store, soul.runtime.session.work_dir)
            console.print(f"Staged {len(created)} memory inbox candidate(s).")
            return
        if action == "approve" and len(parts) > 2:
            console.print(await approve_inbox_candidate(store, parts[2]))
            if soul.runtime.rearm_injection is not None:
                soul.runtime.rearm_injection("project_memory")
            return
        if action == "reject" and len(parts) > 2:
            console.print(await reject_inbox_candidate(store, parts[2]))
            return
        candidates = await list_inbox_candidates(store)
        if not candidates:
            console.print("Memory inbox is empty. Run `/memory inbox scan` to stage candidates.")
            return
        for candidate in candidates:
            console.print(f"- {candidate.id}: {candidate.title} ({candidate.source_path})")
        return

    block = await store.snapshot()
    if not block.strip():
        console.print("No project memory recorded yet. The agent records it with the Memory tool.")
        return
    console.print(block)


@registry.command(name="update", aliases=["upgrade"])
async def update_command(app: Shell, args: str):
    """Check for and optionally install the latest Pythinker version."""
    _ = args, app
    from pythinker_code.ui.shell.update import UpdateResult, run_update_prompt

    result = await run_update_prompt()
    if result is UpdateResult.UPDATED:
        console.print("Updated — restart Pythinker to use the new version.")


@registry.command
async def mcp(app: Shell, args: str):
    """Show MCP servers and tools"""
    from rich.live import Live

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    await soul.start_background_mcp_loading()
    snapshot = soul.status.mcp_status
    if snapshot is None:
        from pythinker_code.ui.theme import get_tui_tokens as _get_tok_mcp

        console.print(f"[{_get_tok_mcp().warning}]No MCP servers configured.[/]")
        return

    if not snapshot.loading:
        console.print(render_mcp_console(snapshot))
        return

    final_snapshot: MCPStatusSnapshot | None = snapshot
    with Live(
        render_mcp_console(snapshot),
        console=console,
        refresh_per_second=8,
        transient=True,
    ) as live:
        while True:
            snapshot = soul.status.mcp_status
            if snapshot is None:
                final_snapshot = None
                break
            final_snapshot = snapshot
            live.update(render_mcp_console(snapshot), refresh=True)
            if not snapshot.loading:
                break
            await asyncio.sleep(0.125)
        try:
            await soul.wait_for_background_mcp_loading()
        except Exception as e:
            logger.debug("MCP loading completed with error while rendering /mcp: {error}", error=e)
        snapshot = soul.status.mcp_status
        if snapshot is not None:
            final_snapshot = snapshot
            live.update(render_mcp_console(snapshot), refresh=True)

    if final_snapshot is not None:
        console.print(render_mcp_console(final_snapshot))


@registry.command
@shell_mode_registry.command
def hooks(app: Shell, args: str):
    """List configured hooks"""
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_hooks

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    _t_hooks = _get_tok_hooks()
    engine = soul.hook_engine
    if not engine.summary:
        console.print(
            f"[{_t_hooks.warning}]No hooks configured. "
            f"Add [[hooks]] sections to your config.toml to set up hooks.[/]"
        )
        return

    console.print()
    console.print("[bold]Configured Hooks:[/bold]")
    console.print()

    for event, entries in engine.details().items():
        console.print(f"  [{_t_hooks.info}]{_rich_escape(event)}[/]: {len(entries)} hook(s)")
        for entry in entries:
            source_tag = (
                f" [dim]({_rich_escape(entry['source'])})[/dim]"
                if entry["source"] == "wire"
                else ""
            )
            console.print(
                f"    [dim]{_rich_escape(entry['matcher'])}[/dim] "
                f"{_rich_escape(entry['command'])}{source_tag}"
            )

    console.print()


@registry.command
async def undo(app: Shell, args: str):
    """Undo: fork the session at a previous turn and retry"""
    from pythinker_code.session_fork import enumerate_turns, fork_session
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_undo
    from pythinker_code.utils.string import shorten

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    _t_undo = _get_tok_undo()
    session = soul.runtime.session
    wire_path = session.dir / "wire.jsonl"
    turns = enumerate_turns(wire_path)

    if not turns:
        console.print(f"[{_t_undo.warning}]No turns found in this session.[/]")
        return

    # Build choices: each turn's first line, truncated
    choices: list[tuple[str, str]] = []
    for turn in turns:
        first_line = turn.user_text.split("\n", 1)[0]
        label = shorten(first_line, width=80, placeholder="...")
        choices.append((str(turn.index), f"[{turn.index}] {label}"))

    try:
        selected = await ChoiceInput(
            message="Select a turn to undo (↑↓ navigate, Enter select, Ctrl+C cancel):",
            options=choices,
            default=choices[-1][0],
        ).prompt_async()
    except (EOFError, KeyboardInterrupt):
        return

    turn_index = int(selected)

    # The selected turn is the one we want to redo — fork includes turns *before* it
    selected_turn = turns[turn_index]
    user_text = selected_turn.user_text

    if turn_index == 0:
        # Fork with no history — just the user text
        new_session = await Session.create(session.work_dir)
        new_session_id = new_session.id
        # Set title to match the convention used by fork_session
        from pythinker_code.session_state import load_session_state, save_session_state

        new_state = load_session_state(new_session.dir)
        new_state.custom_title = f"Undo: {session.title}"
        new_state.title_generated = True
        save_session_state(new_state, new_session.dir)
    else:
        # Fork includes turns 0..turn_index-1
        fork_turn_index = turn_index - 1
        new_session_id = await fork_session(
            source_session_dir=session.dir,
            work_dir=session.work_dir,
            turn_index=fork_turn_index,
            title_prefix="Undo",
            source_title=session.title,
        )

    from pythinker_code.telemetry import track

    track("undo")
    console.print(f"[{_t_undo.success}]Forked at turn {turn_index}. Switching to new session...[/]")
    raise Reload(session_id=new_session_id, prefill_text=user_text)


@registry.command
async def fork(app: Shell, args: str):
    """Fork the current session (copy all history to a new session)"""
    from pythinker_code.session_fork import fork_session

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    session = soul.runtime.session
    new_session_id = await fork_session(
        source_session_dir=session.dir,
        work_dir=session.work_dir,
        turn_index=None,
        title_prefix="Fork",
        source_title=session.title,
    )

    from pythinker_code.telemetry import track

    track("session_fork")
    from pythinker_code.ui.theme import get_tui_tokens as _get_tok_fork

    console.print(f"[{_get_tok_fork().success}]Session forked. Switching to new session...[/]")
    raise Reload(session_id=new_session_id)


from . import (  # noqa: E402
    debug,  # noqa: F401 # type: ignore[reportUnusedImport]
    export_import,  # noqa: F401 # type: ignore[reportUnusedImport]
    oauth,  # noqa: F401 # type: ignore[reportUnusedImport]
    setup,  # noqa: F401 # type: ignore[reportUnusedImport]
    update,  # noqa: F401 # type: ignore[reportUnusedImport]
    usage,  # noqa: F401 # type: ignore[reportUnusedImport]
)
