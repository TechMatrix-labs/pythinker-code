"""Centralized terminal color theme definitions.

All UI-facing colors live here so that switching between dark and light
terminal themes only requires changing the active ``ThemeName``.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal

from prompt_toolkit.styles import Style as PTKStyle
from rich.style import Style as RichStyle

type ThemeName = Literal["dark", "light"]


# ---------------------------------------------------------------------------
# Diff colors (used by utils/rich/diff_render.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiffColors:
    add_bg: RichStyle
    del_bg: RichStyle
    add_hl: RichStyle
    del_hl: RichStyle


_DIFF_DARK = DiffColors(
    add_bg=RichStyle(bgcolor="#12261e"),
    del_bg=RichStyle(bgcolor="#2d1214"),
    add_hl=RichStyle(bgcolor="#1a4a2e"),
    del_hl=RichStyle(bgcolor="#5c1a1d"),
)

_DIFF_LIGHT = DiffColors(
    add_bg=RichStyle(bgcolor="#dafbe1"),
    del_bg=RichStyle(bgcolor="#ffebe9"),
    add_hl=RichStyle(bgcolor="#aff5b4"),
    del_hl=RichStyle(bgcolor="#ffc1c0"),
)


# ---------------------------------------------------------------------------
# Task browser colors (used by ui/shell/task_browser.py)
# ---------------------------------------------------------------------------


def _task_browser_style_dark() -> PTKStyle:
    return PTKStyle.from_dict(
        {
            "header": "bg:#1f2937 #e5e7eb",
            "header.title": "bg:#1f2937 #BAC4FD bold",
            "header.meta": "bg:#1f2937 #9ca3af",
            "status.running": "bg:#1f2937 #86efac bold",
            "status.success": "bg:#1f2937 #86efac",
            "status.warning": "bg:#1f2937 #fbbf24",
            "status.error": "bg:#1f2937 #fca5a5",
            "status.info": "bg:#1f2937 #93c5fd",
            "task-list": "bg:#111827 #d1d5db",
            "task-list.checked": "bg:#164e63 #ecfeff bold",
            "frame.border": "#6f7fe8",
            "frame.label": "bg:#17182a #BAC4FD bold",
            "footer": "bg:#17182a #d7dcff",
            "footer.key": "bg:#17182a #BAC4FD bold",
            "footer.text": "bg:#17182a #d7dcff",
            "footer.warning": "bg:#4a3315 #f2cc60 bold",
            "footer.meta": "bg:#17182a #9aa4d6",
        }
    )


def _task_browser_style_light() -> PTKStyle:
    return PTKStyle.from_dict(
        {
            "header": "bg:#e5e7eb #1f2937",
            "header.title": "bg:#e5e7eb #0e7490 bold",
            "header.meta": "bg:#e5e7eb #6b7280",
            "status.running": "bg:#e5e7eb #166534 bold",
            "status.success": "bg:#e5e7eb #166534",
            "status.warning": "bg:#e5e7eb #92400e",
            "status.error": "bg:#e5e7eb #991b1b",
            "status.info": "bg:#e5e7eb #1e40af",
            "task-list": "bg:#f9fafb #374151",
            "task-list.checked": "bg:#cffafe #164e63 bold",
            "frame.border": "#0e7490",
            "frame.label": "bg:#f1f5f9 #0e7490 bold",
            "footer": "bg:#f1f5f9 #475569",
            "footer.key": "bg:#f1f5f9 #0e7490 bold",
            "footer.text": "bg:#f1f5f9 #475569",
            "footer.warning": "bg:#fee2e2 #991b1b bold",
            "footer.meta": "bg:#f1f5f9 #64748b",
        }
    )


# ---------------------------------------------------------------------------
# Prompt / completion menu colors (used by ui/shell/prompt.py)
# ---------------------------------------------------------------------------


_PROMPT_STYLE_DARK = {
    "bottom-toolbar": "noreverse",
    # Input area — minimal: no background bar, only the prompt glyph is
    # colored. Lets the terminal background show through so the input row
    # reads as a single line of text rather than a chrome panel.
    "compact-input": "",
    "compact-input.prompt": "fg:#BAC4FD bold",
    "compact-input.frame": "fg:#8EA0F8",
    "running-prompt-placeholder": "fg:#8b90a8 italic",
    "running-prompt-separator": "fg:#555a70",
    # Slash completion menu — selected row gets the same selected-bg as cards.
    "slash-completion-menu": "",
    "slash-completion-menu.separator": "fg:#555a70",
    "slash-completion-menu.marker": "fg:#555a70",
    "slash-completion-menu.marker.current": "fg:#BAC4FD bold",
    "slash-completion-menu.command": "fg:#c4c9e8",
    "slash-completion-menu.command.match": "fg:#BAC4FD bold",
    "slash-completion-menu.meta": "fg:#8b90a8",
    "slash-completion-menu.command.current": "bg:#323449 fg:#BAC4FD bold",
    "slash-completion-menu.command.match.current": "bg:#323449 fg:#BAC4FD bold",
    "slash-completion-menu.meta.current": "bg:#323449 fg:#c4c9e8",
    "slash-completion-menu.row.current": "bg:#323449",
    "shell-dialog": "fg:#d7dcff",
    "shell-dialog.title": "fg:#f4f6ff bold",
    "shell-dialog.border": "fg:#555a70",
    "shell-dialog.option": "fg:#aeb6df",
    "shell-dialog.option.current": "bg:#25283d fg:#BAC4FD bold",
    "shell-footer.key": "fg:#BAC4FD bold",
    "shell-footer.meta": "fg:#aeb6df",
    "shell-footer.warning": "fg:#f2cc60",
    "shell-footer.error": "fg:#f38ba8",
}

_PROMPT_STYLE_LIGHT = {
    "bottom-toolbar": "noreverse",
    "compact-input": "",
    "compact-input.prompt": "fg:#5a8080 bold",
    "compact-input.frame": "fg:#547da7",
    "running-prompt-placeholder": "fg:#6b7280 italic",
    "running-prompt-separator": "fg:#d1d5db",
    "slash-completion-menu": "",
    "slash-completion-menu.separator": "fg:#d1d5db",
    "slash-completion-menu.marker": "fg:#9ca3af",
    "slash-completion-menu.marker.current": "fg:#5a8080 bold",
    "slash-completion-menu.command": "fg:#4b5563",
    "slash-completion-menu.command.match": "fg:#5a8080 bold",
    "slash-completion-menu.meta": "fg:#6b7280",
    "slash-completion-menu.command.current": "bg:#d0d0e0 fg:#5a8080 bold",
    "slash-completion-menu.command.match.current": "bg:#d0d0e0 fg:#5a8080 bold",
    "slash-completion-menu.meta.current": "bg:#d0d0e0 fg:#4b5563",
    "slash-completion-menu.row.current": "bg:#d0d0e0",
    "shell-dialog": "fg:#374151",
    "shell-dialog.title": "fg:#1f2937 bold",
    "shell-dialog.border": "fg:#d1d5db",
    "shell-dialog.option": "fg:#6b7280",
    "shell-dialog.option.current": "bg:#d0d0e0 fg:#5a8080 bold",
    "shell-footer.key": "fg:#5a8080 bold",
    "shell-footer.meta": "fg:#6b7280",
    "shell-footer.warning": "fg:#92400e",
    "shell-footer.error": "fg:#991b1b",
}


# ---------------------------------------------------------------------------
# Bottom toolbar fragment colors (used by ui/shell/prompt.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolbarColors:
    separator: str
    yolo_label: str
    auto_label: str
    plan_label: str
    plan_prompt: str
    cwd: str
    bg_tasks: str
    tip: str
    tip_key: str


_TOOLBAR_DARK = ToolbarColors(
    separator="fg:#4d4d4d",
    yolo_label="bold fg:#ffff00",
    auto_label="bold fg:#ff8800",
    plan_label="bold fg:#00aaff",
    plan_prompt="fg:#00aaff",
    cwd="fg:#666666",
    bg_tasks="fg:#888888",
    tip="fg:#555555",
    tip_key="fg:#777777 bold",
)

_TOOLBAR_LIGHT = ToolbarColors(
    separator="fg:#d1d5db",
    yolo_label="bold fg:#b45309",
    auto_label="bold fg:#c2410c",
    plan_label="bold fg:#2563eb",
    plan_prompt="fg:#2563eb",
    cwd="fg:#6b7280",
    bg_tasks="fg:#4b5563",
    tip="fg:#9ca3af",
    tip_key="fg:#6b7280 bold",
)


# ---------------------------------------------------------------------------
# Markdown / spinner palette (used by ui/shell markdown renderer and the
# turn-execution spinner). Foreground colors only; resolved to Rich styles
# by ``markdown_rich_style``. Values are Rich color names so they degrade
# gracefully on 16-color terminals.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarkdownColors:
    heading: str
    emphasis: str
    strong: str
    inline_code: str
    link: str
    quote: str
    table_border: str
    code_block_border: str
    code_block_bg: str
    spinner_active: str
    spinner_done: str
    spinner_failed: str


_MARKDOWN_DARK = MarkdownColors(
    heading="#BAC4FD",
    emphasis="#CBA6F7",
    strong="#F2CC60",
    inline_code="#A6E3A1",
    link="#BAC4FD",
    quote="#8b90a8",
    table_border="#6f7fe8",
    code_block_border="#555a70",
    code_block_bg="#1f2030",
    spinner_active="#BAC4FD",
    spinner_done="green",
    spinner_failed="red",
)

_MARKDOWN_LIGHT = MarkdownColors(
    heading="#0e7490",
    emphasis="#7e22ce",
    strong="#a16207",
    inline_code="#15803d",
    link="#1d4ed8",
    quote="#6b7280",
    table_border="#0e7490",
    code_block_border="#9ca3af",
    code_block_bg="#f1f5f9",
    spinner_active="#1d4ed8",
    spinner_done="#15803d",
    spinner_failed="#b91c1c",
)


def get_markdown_colors(theme: ThemeName | None = None) -> MarkdownColors:
    name = theme if theme is not None else _active_theme
    return _MARKDOWN_LIGHT if name == "light" else _MARKDOWN_DARK


def markdown_rich_style(token: str, *, theme: ThemeName | None = None) -> RichStyle:
    """Resolve a MarkdownColors field name to a Rich Style.

    Background tokens (suffix ``_bg``) produce a style with ``bgcolor``;
    everything else produces a style with ``color``.
    """
    colors = get_markdown_colors(theme)
    value = getattr(colors, token)
    if not value:
        return RichStyle()
    if token.endswith("_bg"):
        return RichStyle(bgcolor=value)
    return RichStyle(color=value)


# ---------------------------------------------------------------------------
# MCP status prompt colors (used by ui/shell/mcp_status.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MCPPromptColors:
    text: str
    detail: str
    connected: str
    connecting: str
    pending: str
    failed: str


_MCP_PROMPT_DARK = MCPPromptColors(
    text="fg:#d4d4d4",
    detail="fg:#7c8594",
    connected="fg:#56d364",
    connecting="fg:#56a4ff",
    pending="fg:#f2cc60",
    failed="fg:#ff7b72",
)

_MCP_PROMPT_LIGHT = MCPPromptColors(
    text="fg:#374151",
    detail="fg:#6b7280",
    connected="fg:#166534",
    connecting="fg:#1d4ed8",
    pending="fg:#92400e",
    failed="fg:#dc2626",
)


# ---------------------------------------------------------------------------
# Public API — resolve by theme name
# ---------------------------------------------------------------------------

_active_theme: ThemeName = "dark"


def set_active_theme(theme: ThemeName) -> None:
    global _active_theme
    _active_theme = theme


def get_active_theme() -> ThemeName:
    return _active_theme


def get_diff_colors() -> DiffColors:
    return _DIFF_LIGHT if _active_theme == "light" else _DIFF_DARK


def get_task_browser_style() -> PTKStyle:
    return _task_browser_style_light() if _active_theme == "light" else _task_browser_style_dark()


def get_prompt_style() -> PTKStyle:
    d = _PROMPT_STYLE_LIGHT if _active_theme == "light" else _PROMPT_STYLE_DARK
    return PTKStyle.from_dict(d)


def get_toolbar_colors() -> ToolbarColors:
    return _TOOLBAR_LIGHT if _active_theme == "light" else _TOOLBAR_DARK


def get_mcp_prompt_colors() -> MCPPromptColors:
    return _MCP_PROMPT_LIGHT if _active_theme == "light" else _MCP_PROMPT_DARK


# ---------------------------------------------------------------------------
# Pythinker semantic TUI tokens (used by ui/shell/components/* and the tool
# renderer registry). Default semantic token palette
# and light themes so the Pythinker code path renders with the reference
# palette. Existing pythinker styles continue to work — these tokens add a
# parallel naming layer keyed by *semantic role* rather than concrete color.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TuiTokens:
    """Pythinker semantic theme tokens.

    Values are hex strings (``"#rrggbb"``) or the empty string for "use
    terminal default". Background tokens (``*_bg``) are intended for
    Rich ``bgcolor=`` arguments; foreground tokens for ``color=``.
    """

    # Core
    accent: str
    border: str
    border_accent: str
    border_muted: str
    success: str
    error: str
    warning: str
    muted: str
    dim: str
    text: str
    thinking_text: str
    # Backgrounds
    selected_bg: str
    user_message_bg: str
    user_message_text: str
    custom_message_bg: str
    custom_message_text: str
    custom_message_label: str
    tool_pending_bg: str
    tool_success_bg: str
    tool_error_bg: str
    tool_title: str
    tool_output: str
    # Diffs
    tool_diff_added: str
    tool_diff_removed: str
    tool_diff_context: str
    # Bash mode accent
    bash_mode: str


TUI_TOKEN_NAMES = frozenset(field.name for field in fields(TuiTokens))


_TUI_TOKENS_DARK = TuiTokens(
    accent="#BAC4FD",
    border="#8EA0F8",
    border_accent="#BAC4FD",
    border_muted="#555a70",
    success="#A6E3A1",
    error="#F38BA8",
    warning="#F2CC60",
    muted="#8b90a8",
    dim="#6f748a",
    text="",
    thinking_text="#8b90a8",
    selected_bg="#323449",
    user_message_bg="#2d3042",
    user_message_text="",
    custom_message_bg="#302b45",
    custom_message_text="",
    custom_message_label="#CBA6F7",
    tool_pending_bg="#282a3a",
    tool_success_bg="#253527",
    tool_error_bg="#3a2632",
    tool_title="",
    tool_output="#8b90a8",
    tool_diff_added="#A6E3A1",
    tool_diff_removed="#F38BA8",
    tool_diff_context="#8b90a8",
    bash_mode="#A6E3A1",
)


_TUI_TOKENS_LIGHT = TuiTokens(
    accent="#0284c7",
    border="#547da7",
    border_accent="#5a8080",
    border_muted="#b0b0b0",
    success="#588458",
    error="#aa5555",
    warning="#9a7326",
    muted="#6c6c6c",
    dim="#767676",
    text="",
    thinking_text="#6c6c6c",
    selected_bg="#d0d0e0",
    user_message_bg="#e8e8e8",
    user_message_text="",
    custom_message_bg="#ede7f6",
    custom_message_text="",
    custom_message_label="#7e57c2",
    tool_pending_bg="#e8e8f0",
    tool_success_bg="#e8f0e8",
    tool_error_bg="#f0e8e8",
    tool_title="",
    tool_output="#6c6c6c",
    tool_diff_added="#588458",
    tool_diff_removed="#aa5555",
    tool_diff_context="#6c6c6c",
    bash_mode="#588458",
)


def get_tui_tokens(theme: ThemeName | None = None) -> TuiTokens:
    """Return Pythinker semantic tokens for *theme* (defaults to active)."""
    name = theme if theme is not None else _active_theme
    return _TUI_TOKENS_LIGHT if name == "light" else _TUI_TOKENS_DARK


def tui_rich_style(token: str, *, theme: ThemeName | None = None) -> RichStyle:
    """Resolve a TuiTokens field name to a Rich Style.

    Background tokens (suffix ``_bg``) produce a style with ``bgcolor``;
    everything else produces a style with ``color``. Empty hex values
    (``""``) yield an empty style — Rich falls back to terminal defaults.

    Raises:
        ValueError: If *token* is not a known TuiTokens field.
    """
    if token not in TUI_TOKEN_NAMES:
        known = ", ".join(sorted(TUI_TOKEN_NAMES))
        raise ValueError(f"Unknown TUI token {token!r}. Known tokens: {known}")
    tokens = get_tui_tokens(theme)
    value = getattr(tokens, token)
    if not value:
        return RichStyle()
    if token.endswith("_bg"):
        return RichStyle(bgcolor=value)
    return RichStyle(color=value)
