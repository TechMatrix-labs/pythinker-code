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
        console.print("[red]PythinkerSoul required[/red]")
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

    from pythinker_code.utils.rich.columns import BulletColumns

    def section(title: str, items: list[tuple[str, str]], color: str) -> BulletColumns:
        lines: list[RenderableType] = [Text.from_markup(f"[bold]{_rich_escape(title)}:[/bold]")]
        for name, desc in items:
            lines.append(
                BulletColumns(
                    Text.from_markup(
                        f"[{color}]{_rich_escape(name)}[/{color}]: "
                        f"[grey50]{_rich_escape(desc)}[/grey50]"
                    ),
                    bullet_style=color,
                )
            )
        return BulletColumns(Group(*lines))

    renderables: list[RenderableType] = []
    renderables.append(
        BulletColumns(
            Group(
                Text.from_markup("[grey50]Help! I need somebody. Help! Not just anybody.[/grey50]"),
                Text.from_markup("[grey50]Help! You know I need someone. Help![/grey50]"),
                Text.from_markup("[grey50]\u2015 The Beatles, [italic]Help![/italic][/grey50]"),
            ),
            bullet_style="grey50",
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

    renderables.append(section("Keyboard shortcuts", _KEYBOARD_SHORTCUTS, "yellow"))
    renderables.append(
        section(
            "Slash commands",
            [(c.slash_name(), c.description) for c in sorted(commands, key=lambda c: c.name)],
            "blue",
        )
    )
    if skills:
        renderables.append(
            section(
                "Skills",
                [(c.slash_name(), c.description) for c in sorted(skills, key=lambda c: c.name)],
                "cyan",
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
    if not type_defs:
        console.print("[yellow]No subagents are registered for this agent.[/yellow]")
        return

    table = Table.grid(expand=True)
    table.add_column(ratio=1, no_wrap=True)
    table.add_column(ratio=4)
    table.add_column(ratio=1, no_wrap=True)
    table.add_column(ratio=2, no_wrap=True)
    table.add_row(
        Text("agent", style="bold cyan"),
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
            Text(type_def.name, style="cyan"),
            Text(type_def.when_to_use or type_def.description or "—", style="grey70"),
            Text(type_def.default_model or "inherit", style="grey58"),
            Text(tool_label, style="grey58"),
        )

    footer = Text("Use the Agent tool with subagent_type=<agent>, or ask Pythinker to delegate.")
    footer.stylize("grey58")
    console.print(
        Panel(
            table,
            title="[bold cyan]Agents[/bold cyan]",
            subtitle=footer,
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


@registry.command
async def model(app: Shell, args: str):
    """Switch LLM model or thinking mode"""
    from pythinker_code.llm import derive_model_capabilities

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    config = soul.runtime.config

    await refresh_managed_models(config)

    if not config.models:
        console.print('[yellow]No models configured, send "/login" to login.[/yellow]')
        return

    if not config.is_from_default_location:
        console.print(
            "[yellow]Model switching requires the default config file; "
            "restart without --config/--config-file.[/yellow]"
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
        console.print(f"[red]Provider not found: {_rich_escape(selected_model_cfg.provider)}[/red]")
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
            f"[yellow]Already using {_rich_escape(selected_display)} "
            f"with thinking {'on' if new_thinking else 'off'}.[/yellow]"
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
        console.print(f"[red]Failed to save config: {_rich_escape(exc)}[/red]")
        return

    from pythinker_code.telemetry import track

    if model_changed:
        track("model_switch", model=selected_model_name)
    if thinking_changed:
        track("thinking_toggle", enabled=new_thinking)
    console.print(
        f"[green]Switched to {selected_display} "
        f"with thinking {'on' if new_thinking else 'off'}. "
        "Reloading...[/green]"
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
            f"[yellow]LM Studio pre-load failed for {model_id}: {exc}[/yellow]\n"
            "[dim]The chat will still try the model on first message.[/dim]"
        )


@registry.command
@shell_mode_registry.command
async def editor(app: Shell, args: str):
    """Set default external editor for Ctrl-O"""
    from pythinker_code.utils.editor import get_editor_command

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    config = soul.runtime.config
    config_file = config.source_file
    if config_file is None:
        console.print(
            "[yellow]Editor switching is unavailable with inline --config; "
            "use --config-file to persist this setting.[/yellow]"
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
            console.print(f"[red]Invalid editor command: {_rich_escape(new_editor)}[/red]")
            return

        binary = parts[0]
        if not shutil.which(binary):
            console.print(
                f"[yellow]Warning: '{_rich_escape(binary)}' not found in PATH. "
                f"Saving anyway — make sure it's installed before using Ctrl-O.[/yellow]"
            )

    if new_editor == current_editor:
        editor_label = _rich_escape(new_editor or "auto-detect")
        console.print(f"[yellow]Editor is already set to: {editor_label}[/yellow]")
        return

    # Save to disk
    try:
        config_for_save = load_config(config_file)
        config_for_save.default_editor = new_editor
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[red]Failed to save config: {_rich_escape(exc)}[/red]")
        return

    # Sync in-memory config so Ctrl-O picks it up immediately
    config.default_editor = new_editor

    if new_editor:
        console.print(f"[green]Editor set to: {_rich_escape(new_editor)}[/green]")
    else:
        resolved = get_editor_command()
        label = " ".join(resolved) if resolved else "none"
        console.print(f"[green]Editor set to auto-detect (resolved: {_rich_escape(label)})[/green]")


@registry.command(aliases=["release-notes"])
@shell_mode_registry.command(aliases=["release-notes"])
def changelog(app: Shell, args: str):
    """Show release notes"""
    from rich.console import Group, RenderableType
    from rich.text import Text

    from pythinker_code.utils.rich.columns import BulletColumns

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
                    Text.from_markup(f"[grey50]{_rich_escape(item)}[/grey50]"),
                    bullet_style="grey50",
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


def _feedback_github_config(soul: PythinkerSoul) -> tuple[str, str] | None:
    """Return GitHub OAuth client_id and repo when direct user-owned issues are enabled."""
    import os

    feedback_config = soul.runtime.config.feedback
    client_id = os.getenv("PYTHINKER_FEEDBACK_GITHUB_CLIENT_ID", "").strip()
    if not client_id:
        client_id = feedback_config.github_client_id.strip()
    repo = os.getenv("PYTHINKER_FEEDBACK_GITHUB_REPO", "").strip()
    if not repo:
        repo = feedback_config.github_repo.strip()
    if not client_id or not repo:
        return None
    return client_id, repo


def _feedback_issue_title(payload: dict[str, str | None]) -> str:
    version = f" {payload['version']}" if payload.get("version") else ""
    session = payload.get("session_id") or ""
    suffix = f" ({session[:8]})" if session else ""
    return f"[Pythinker CLI] Feedback{version}{suffix}"


def _feedback_issue_body(payload: dict[str, str | None]) -> str:
    return "\n".join(
        [
            "## User submission",
            "",
            payload.get("content") or "_(no comment)_",
            "",
            "## Context",
            "",
            "- Type: feedback",
            f"- Session: {payload.get('session_id') or 'unknown'}",
            f"- Version: {payload.get('version') or 'unknown'}",
            f"- OS: {payload.get('os') or 'unknown'}",
            f"- Model: {payload.get('model') or 'unknown'}",
        ]
    )


@registry.command
@shell_mode_registry.command
async def feedback(app: Shell, args: str):
    """Submit feedback to make Pythinker CLI better"""
    import platform
    import webbrowser

    import aiohttp

    from pythinker_code.constant import VERSION
    from pythinker_code.ui.shell.oauth import current_model_key
    from pythinker_code.utils.aiohttp import new_client_session

    ISSUE_URL = "https://github.com/mohamed-elkholy95/Pythinker-Code/issues"

    def _fallback_to_issues():
        if not webbrowser.open(ISSUE_URL):
            console.print(f"Please submit feedback at [underline]{ISSUE_URL}[/underline].")

    soul = ensure_pythinker_soul(app)
    if soul is None:
        _fallback_to_issues()
        return

    github_config = _feedback_github_config(soul)
    destination = None if github_config is not None else _feedback_destination(soul)
    if github_config is None and destination is None:
        _fallback_to_issues()
        return

    from prompt_toolkit import PromptSession

    prompt_session: PromptSession[str] = PromptSession()
    try:
        content = await prompt_session.prompt_async("Enter your feedback: ")
    except (EOFError, KeyboardInterrupt):
        console.print("[grey50]Feedback cancelled.[/grey50]")
        return

    content = content.strip()
    if not content:
        console.print("[yellow]Feedback cannot be empty.[/yellow]")
        return

    payload = {
        "session_id": soul.runtime.session.id,
        "content": content,
        "version": VERSION,
        "os": f"{platform.system()} {platform.release()}",
        "model": current_model_key(soul),
    }

    if github_config is not None:
        client_id, repo = github_config
        from pythinker_code.auth.github_feedback import (
            GitHubFeedbackError,
            create_github_issue,
            load_github_feedback_token,
            login_github_feedback,
            star_github_repo,
        )

        try:
            token = load_github_feedback_token()
            if token is None:
                console.print("[cyan]GitHub login required to create the issue as you.[/cyan]")
                async for event in login_github_feedback(client_id):
                    if event.type == "waiting":
                        console.print(event.message, markup=False)
                    elif event.type in {"verification_url", "success", "error"}:
                        style = None
                        if event.type == "success":
                            style = "green"
                        elif event.type == "error":
                            style = "red"
                        console.print(event.message, markup=False, style=style)
                token = load_github_feedback_token()
            if token is None:
                console.print("[red]GitHub login did not produce a usable token.[/red]")
                return
            with console.status("[cyan]Creating GitHub issue...[/cyan]"):
                issue = await create_github_issue(
                    repo,
                    token,
                    title=_feedback_issue_title(payload),
                    body=_feedback_issue_body(payload),
                )
            from pythinker_code.telemetry import track

            track("feedback_submitted", destination="github")
            if issue.html_url:
                issue_url = _rich_escape(issue.html_url)
                console.print(f"[green]GitHub issue created:[/green] {issue_url}")
            else:
                console.print("[green]GitHub issue created.[/green]")

            try:
                star_answer = await prompt_session.prompt_async(
                    "Do you like Pythinker CLI? Star the GitHub repo? [y/N]: "
                )
            except (EOFError, KeyboardInterrupt):
                star_answer = ""
            if star_answer.strip().lower() in {"y", "yes"}:
                try:
                    with console.status("[cyan]Starring GitHub repo...[/cyan]"):
                        await star_github_repo(repo, token)
                    track("github_repo_starred")
                    console.print("[green]Thanks for starring the repo![/green]")
                except (GitHubFeedbackError, TimeoutError, aiohttp.ClientError) as e:
                    console.print(f"[yellow]Could not star the repo: {_rich_escape(e)}[/yellow]")
        except (GitHubFeedbackError, TimeoutError, aiohttp.ClientError) as e:
            console.print(f"[red]Failed to create GitHub issue: {_rich_escape(e)}[/red]")
            _fallback_to_issues()
        return

    assert destination is not None
    feedback_url, headers = destination

    with console.status("[cyan]Submitting feedback...[/cyan]"):
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
            session_id = soul.runtime.session.id
            from pythinker_code.telemetry import track

            track("feedback_submitted")
            console.print(
                f"[green]Feedback submitted, thank you! Your session ID is: {session_id}[/green]"
            )
        except TimeoutError:
            console.print("[red]Feedback submission timed out.[/red]")
            _fallback_to_issues()
        except aiohttp.ClientError as e:
            status = getattr(e, "status", None)
            if status:
                msg = f"Failed to submit feedback (HTTP {status})."
            else:
                msg = "Network error, failed to submit feedback."
            console.print(f"[red]{msg}[/red]")
            _fallback_to_issues()


@registry.command(aliases=["report-error", "report"])
@shell_mode_registry.command(aliases=["report-error", "report"])
async def report_error(app: Shell, args: str):
    """Submit a report about an error you hit, with a snapshot of recent failures."""
    import platform
    import webbrowser

    import aiohttp

    from pythinker_code.constant import VERSION
    from pythinker_code.telemetry.errors import clear_recent_errors, recent_errors
    from pythinker_code.ui.shell.oauth import current_model_key
    from pythinker_code.utils.aiohttp import new_client_session

    ISSUE_URL = "https://github.com/mohamed-elkholy95/Pythinker-Code/issues"

    def _fallback_to_issues():
        if not webbrowser.open(ISSUE_URL):
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
                f"  [dim]{i}.[/dim] [cyan]{_rich_escape(err.site)}[/cyan]"
                f"{tool_part}: {_rich_escape(err.exc_class)}"
            )
    else:
        console.print(
            "[grey50]No errors recorded this session. "
            "You can still attach a comment describing what went wrong.[/grey50]"
        )

    from prompt_toolkit import PromptSession

    prompt_session: PromptSession[str] = PromptSession()
    try:
        comment = await prompt_session.prompt_async("Describe what went wrong (Ctrl-C to cancel): ")
    except (EOFError, KeyboardInterrupt):
        console.print("[grey50]Report cancelled.[/grey50]")
        return

    comment = comment.strip()
    if not comment and not errors:
        console.print("[yellow]Nothing to report. Cancelled.[/yellow]")
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

    with console.status("[cyan]Submitting error report...[/cyan]"):
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
                f"[green]Error report submitted. Session ID: {soul.runtime.session.id}[/green]"
            )
        except TimeoutError:
            console.print("[red]Submission timed out.[/red]")
            _fallback_to_issues()
        except aiohttp.ClientError as e:
            status = getattr(e, "status", None)
            msg = (
                f"Failed to submit error report (HTTP {status})."
                if status
                else "Network error, failed to submit error report."
            )
            console.print(f"[red]{msg}[/red]")
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
    console.print("[green]New session created. Switching...[/green]")
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
    console.print(f"[green]Session title set to: {_rich_escape(new_title)}[/green]")


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

    if selection == current_session.id:
        console.print("[yellow]You are already in this session.[/yellow]")
        return

    if selected_work_dir != current_session.work_dir:
        cmd = f"pythinker --work-dir {shlex.quote(str(selected_work_dir))} --session {selection}"
        console.print(
            f"[yellow]Session is in a different directory. Run:[/yellow]\n  {_rich_escape(cmd)}"
        )
        return

    from pythinker_code.telemetry import track

    track("session_resume")
    console.print(f"[green]Switching to session {_rich_escape(selection)}...[/green]")
    raise Reload(session_id=selection)


@registry.command(name="task", aliases=["tasks"])
@shell_mode_registry.command(name="task", aliases=["tasks"])
async def task(app: Shell, args: str):
    """Browse and manage background tasks"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return
    if args.strip():
        console.print('[yellow]Usage: "/task" opens the interactive task browser.[/yellow]')
        return
    if soul.runtime.role != "root":
        console.print("[yellow]Background tasks are only available from the root agent.[/yellow]")
        return

    await TaskBrowserApp(soul).run()


@registry.command(aliases=["color"])
@shell_mode_registry.command(aliases=["color"])
async def theme(app: Shell, args: str) -> None:
    """Switch terminal color theme — interactive picker when no args given"""
    from pythinker_code.ui.theme import get_active_theme

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

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
        console.print(f"[red]Unknown theme: {_rich_escape(arg)}. Use 'dark' or 'light'.[/red]")
        return

    if arg == current:
        console.print(f"[yellow]Already using {_rich_escape(arg)} theme.[/yellow]")
        return

    config_file = soul.runtime.config.source_file
    if config_file is None:
        console.print(
            "[yellow]Theme switching requires a config file; "
            "restart without --config to persist this setting.[/yellow]"
        )
        return

    try:
        config_for_save = load_config(config_file)
        config_for_save.theme = arg  # type: ignore[assignment]
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[red]Failed to save config: {_rich_escape(exc)}[/red]")
        return

    from pythinker_code.telemetry import track

    track("theme_switch", theme=arg)
    console.print(f"[green]Switched to {_rich_escape(arg)} theme. Reloading...[/green]")
    raise Reload(session_id=soul.runtime.session.id)


@registry.command
@shell_mode_registry.command
async def thinking(app: Shell, args: str) -> None:
    """Switch thinking level — interactive picker"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    from pythinker_code.ui.shell.selectors.thinking import ThinkingLevel, run_thinking_selector

    curr_level: ThinkingLevel = "high" if soul.thinking else "off"
    level = await run_thinking_selector(
        current_level=curr_level,
        available_levels=["off", "minimal", "low", "medium", "high", "xhigh"],
    )
    if level is None:
        return

    new_thinking = level != "off"
    if new_thinking == soul.thinking:
        console.print("[yellow]Thinking setting unchanged.[/yellow]")
        return

    config_file = soul.runtime.config.source_file
    if config_file is None:
        console.print(
            "[yellow]Thinking requires a config file; "
            "restart without --config to persist this setting.[/yellow]"
        )
        return

    try:
        config_for_save = load_config(config_file)
        config_for_save.default_thinking = new_thinking
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[red]Failed to save config: {_rich_escape(exc)}[/red]")
        return

    from pythinker_code.telemetry import track

    track("thinking_toggle", enabled=new_thinking)
    console.print(
        f"[green]Thinking {'enabled' if new_thinking else 'disabled'}. Reloading...[/green]"
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

    bindings = keybinding_help()
    if not bindings:
        console.print("[yellow]No keybindings registered.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Shortcut", style="bold", no_wrap=True)
    table.add_column("Action", style="cyan")
    table.add_column("Where", style="dim", no_wrap=True)

    for binding in bindings:
        table.add_row("/".join(binding.keys), binding.description, binding.context)

    blocks: list[RenderableType] = [
        Text.from_markup("[bold]Keyboard shortcuts[/bold]"),
        table,
        Text.from_markup(
            "[grey50]Tip: press ? on an empty prompt for the compact overlay.[/grey50]"
        ),
    ]
    console.print(Group(*blocks))


@registry.command
@shell_mode_registry.command
def tui(app: Shell, args: str):
    """Show or set the TUI style: card or pythinker"""
    from pythinker_code.ui.tui_config import get_active_tui_style, set_active_tui_style

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
        console.print("[grey50]Usage: /tui card | /tui pythinker[/grey50]")
        return

    if target not in ("card", "pythinker"):
        target_label = _rich_escape(target)
        console.print(f"[red]Unknown style: {target_label}. Use 'card' or 'pythinker'.[/red]")
        return

    if target == current:
        console.print(f"[yellow]Already using {_rich_escape(target)} style.[/yellow]")
        return

    config_file = soul.runtime.config.source_file
    if config_file is None:
        # Apply in-memory only — useful for one-off testing without a persisted config.
        set_active_tui_style(target)
        console.print(
            f"[green]Switched to {target} style for this session "
            "(no config file to persist).[/green]"
        )
        return

    try:
        config_for_save = load_config(config_file)
        config_for_save.tui.style = target  # type: ignore[assignment]
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[red]Failed to save config: {_rich_escape(exc)}[/red]")
        return

    set_active_tui_style(target)
    if target == "card":
        # Make sure renderers are present immediately for current session.
        from pythinker_code.ui.shell.tool_renderers import register_builtin_renderers

        register_builtin_renderers()

    from pythinker_code.telemetry import track

    track("tui_style_switch", style=target)
    console.print(f"[green]Switched to {_rich_escape(target)} style. Reloading...[/green]")
    raise Reload(session_id=soul.runtime.session.id)


@registry.command
@shell_mode_registry.command
async def settings(app: Shell, args: str):
    """Open the interactive settings panel; use `/settings show` for read-only view"""
    from rich.console import Group, RenderableType
    from rich.table import Table
    from rich.text import Text

    from pythinker_code.ui.theme import get_active_theme
    from pythinker_code.ui.tui_config import get_active_tui_style

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    config = soul.runtime.config
    mode = args.strip().lower()

    def print_settings_table() -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="cyan", no_wrap=True)
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
            "[grey50]Tip: /settings opens the interactive panel; "
            "/theme, /tui, /model, /keys for related controls.[/grey50]"
        )

    if mode in {"show", "list", "view"}:
        print_settings_table()
        return
    if mode:
        console.print("[yellow]Usage: /settings [show|list][/yellow]")
        return

    config_file = config.source_file
    if config_file is None:
        print_settings_table()
        console.print(
            "[yellow]Interactive settings require a config file; "
            "restart without --config text to persist settings.[/yellow]"
        )
        return

    from pythinker_code.ui.shell.selectors.settings import (
        apply_settings_changes,
        run_settings_selector,
    )

    try:
        config_for_save = load_config(config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[red]Failed to load config: {_rich_escape(exc)}[/red]")
        return

    changes = await run_settings_selector(config_for_save)
    if changes is None:
        return

    changed_ids = apply_settings_changes(config_for_save, changes)
    if not changed_ids:
        console.print("[yellow]Settings unchanged.[/yellow]")
        return

    try:
        save_config(config_for_save, config_file)
    except (ConfigError, OSError) as exc:
        console.print(f"[red]Failed to save config: {_rich_escape(exc)}[/red]")
        return

    from pythinker_code.telemetry import track

    track("settings_update", changed=",".join(changed_ids), count=len(changed_ids))
    console.print(f"[green]Updated {len(changed_ids)} setting(s). Reloading...[/green]")
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

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    session = soul.runtime.session
    arg = args.strip()
    if not arg:
        points = list_file_restore_points(session, limit=20)
        if not points:
            console.print("[yellow]No file restore points in this session.[/yellow]")
            return
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Tool", no_wrap=True)
        table.add_column("Path")
        table.add_column("State", no_wrap=True)
        for point in points:
            state = "modified" if point.existed else "created"
            table.add_row(point.id, point.tool_name, str(point.path), state)
        console.print(table)
        console.print("[grey50]Run /restore <id> or /restore latest.[/grey50]")
        return

    if arg == "latest":
        points = list_file_restore_points(session, limit=1)
        if not points:
            console.print("[yellow]No file restore points in this session.[/yellow]")
            return
        restore_id = points[0].id
    else:
        restore_id = arg

    try:
        point = restore_file_restore_point(session, restore_id)
    except FileNotFoundError:
        console.print(f"[red]Restore point not found: {_rich_escape(restore_id)}[/red]")
        return
    except OSError as exc:
        console.print(
            f"[red]Failed to restore {_rich_escape(restore_id)}: {_rich_escape(exc)}[/red]"
        )
        return

    action = "restored" if point.existed else "removed"
    console.print(
        f"[green]File {action} from restore point {_rich_escape(point.id)}: "
        f"{_rich_escape(point.path)}[/green]"
    )


@registry.command
@shell_mode_registry.command
def trust(app: Shell, args: str) -> None:
    """Show or update workspace trust safe mode"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    state = soul.runtime.session.state.trust
    mode = args.strip().lower()
    if mode in {"on", "yes", "trust"}:
        state.trusted = True
        state.safe_mode = False
        soul.runtime.approval.set_safe_mode(False)
        soul.runtime.session.save_state()
        console.print("[green]Workspace trusted. Safe mode disabled for this session.[/green]")
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
            "[yellow]Workspace untrusted. Safe mode enabled; auto-approval is disabled.[/yellow]"
        )
        return
    if mode:
        console.print("[yellow]Usage: /trust [on|off][/yellow]")
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

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Signal", style="cyan")
    table.add_column("Count", justify="right")
    for key in sorted(counts):
        table.add_row(key, str(counts[key]))
    if counts:
        console.print(table)
        console.print(f"[grey50]Recent: {_rich_escape(' -> '.join(recent))}[/grey50]")
    else:
        console.print("[yellow]No worklog events recorded yet.[/yellow]")

    restore_points = list_file_restore_points(soul.runtime.session, limit=5)
    if restore_points:
        console.print("[bold]Recent restore points:[/bold]")
        for point in restore_points:
            console.print(
                f"  [cyan]{_rich_escape(point.id)}[/cyan] "
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

    status = soul.status
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("Tokens", str(status.context_tokens or 0))
    table.add_row("Window", str(status.max_context_tokens or 0))
    context_usage_label = f"{status.context_usage:.1f}%"
    table.add_row("Usage", context_usage_label)
    table.add_row("Checkpoints", str(soul.context.n_checkpoints))
    table.add_row("Plan mode", "on" if soul.plan_mode else "off")
    table.add_row("Context file", str(soul.runtime.session.context_file))
    console.print(table)
    console.print("[grey50]Use /compact [focus] to summarize old context.[/grey50]")


@registry.command
@shell_mode_registry.command
def tools(app: Shell, args: str) -> None:
    """List available tools and permission posture"""
    from rich.table import Table

    from pythinker_code.soul.permission import permission_profile_for_runtime

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
    table.add_column("Tool", style="cyan", no_wrap=True)
    table.add_column("Description")
    for tool in sorted(soul.agent.toolset.tools, key=lambda item: item.name):
        desc = " ".join((tool.description or "").split())
        if len(desc) > 100:
            desc = desc[:97] + "..."
        table.add_row(tool.name, desc)
    console.print(table)
    if args.strip().lower() == "audit":
        console.print(
            "[grey50]Audit: external MCP/wire/plugin tools are blocked in read-only, "
            "plan, review, and verify profiles unless their side effects are known.[/grey50]"
        )


@registry.command(aliases=["a11y"])
@shell_mode_registry.command(aliases=["a11y"])
def accessibility(app: Shell, args: str) -> None:
    """Show or update accessibility/plain-output preferences"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

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
                "[yellow]Usage: /accessibility "
                "[plain|rich|no-animation|animation|ascii|unicode][/yellow]"
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
        console.print("[yellow]No MCP servers configured.[/yellow]")
        return

    if not snapshot.loading:
        console.print(render_mcp_console(snapshot))
        return

    with Live(
        render_mcp_console(snapshot),
        console=console,
        refresh_per_second=8,
        transient=False,
    ) as live:
        while True:
            snapshot = soul.status.mcp_status
            if snapshot is None:
                break
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
            live.update(render_mcp_console(snapshot), refresh=True)


@registry.command
@shell_mode_registry.command
def hooks(app: Shell, args: str):
    """List configured hooks"""
    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    engine = soul.hook_engine
    if not engine.summary:
        console.print(
            "[yellow]No hooks configured. "
            "Add [[hooks]] sections to your config.toml to set up hooks.[/yellow]"
        )
        return

    console.print()
    console.print("[bold]Configured Hooks:[/bold]")
    console.print()

    for event, entries in engine.details().items():
        console.print(f"  [cyan]{_rich_escape(event)}[/cyan]: {len(entries)} hook(s)")
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
    from pythinker_code.utils.string import shorten

    soul = ensure_pythinker_soul(app)
    if soul is None:
        return

    session = soul.runtime.session
    wire_path = session.dir / "wire.jsonl"
    turns = enumerate_turns(wire_path)

    if not turns:
        console.print("[yellow]No turns found in this session.[/yellow]")
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
    console.print(f"[green]Forked at turn {turn_index}. Switching to new session...[/green]")
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
    console.print("[green]Session forked. Switching to new session...[/green]")
    raise Reload(session_id=new_session_id)


from . import (  # noqa: E402
    debug,  # noqa: F401 # type: ignore[reportUnusedImport]
    export_import,  # noqa: F401 # type: ignore[reportUnusedImport]
    oauth,  # noqa: F401 # type: ignore[reportUnusedImport]
    setup,  # noqa: F401 # type: ignore[reportUnusedImport]
    update,  # noqa: F401 # type: ignore[reportUnusedImport]
    usage,  # noqa: F401 # type: ignore[reportUnusedImport]
)
