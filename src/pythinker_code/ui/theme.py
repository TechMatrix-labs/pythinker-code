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
            "header.title": "bg:#1f2937 #F4F4F5 bold",
            "header.meta": "bg:#1f2937 #A3A3A3",
            "status.running": "bg:#1f2937 #7BC97F bold",
            "status.success": "bg:#1f2937 #7BC97F",
            "status.warning": "bg:#1f2937 #E6B450",
            "status.error": "bg:#1f2937 #EF5E62",
            "status.info": "bg:#1f2937 #AFE3F1",
            "task-list": "bg:#111827 #d1d5db",
            "task-list.checked": "bg:#164e63 #ecfeff bold",
            "frame.border": "#3A506D",
            "frame.label": "bg:#17182a #F4F4F5 bold",
            "footer": "bg:#17182a #A3A3A3",
            "footer.key": "bg:#17182a #AFE3F1 bold",
            "footer.text": "bg:#17182a #A3A3A3",
            "footer.warning": "bg:#4a3315 #E6B450 bold",
            "footer.meta": "bg:#17182a #5F6B7E",
        }
    )


def _task_browser_style_light() -> PTKStyle:
    return PTKStyle.from_dict(
        {
            "header": "bg:#e5e7eb #1f2937",
            "header.title": "bg:#e5e7eb #213853 bold",
            "header.meta": "bg:#e5e7eb #666666",
            "status.running": "bg:#e5e7eb #2C7A39 bold",
            "status.success": "bg:#e5e7eb #2C7A39",
            "status.warning": "bg:#e5e7eb #9A6B18",
            "status.error": "bg:#e5e7eb #C0392B",
            "status.info": "bg:#e5e7eb #176B7E",
            "task-list": "bg:#f9fafb #374151",
            "task-list.checked": "bg:#cffafe #164e63 bold",
            "frame.border": "#495F7C",
            "frame.label": "bg:#f1f5f9 #213853 bold",
            "footer": "bg:#f1f5f9 #475569",
            "footer.key": "bg:#f1f5f9 #176B7E bold",
            "footer.text": "bg:#f1f5f9 #475569",
            "footer.warning": "bg:#fee2e2 #C0392B bold",
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
    "compact-input.prompt": "fg:#F4F4F5 bold",
    "compact-input.frame": "fg:#3A506D",
    "running-prompt-placeholder": "fg:#A3A3A3 italic",
    "running-prompt-separator": "fg:#2B3A52",
    # Slash completion menu — selected row gets the same selected-bg as cards.
    "slash-completion-menu": "",
    "slash-completion-menu.separator": "fg:#2B3A52",
    "slash-completion-menu.marker": "fg:#2B3A52",
    "slash-completion-menu.marker.current": "fg:#AFE3F1 bold",
    "slash-completion-menu.command": "fg:#F4F4F5",
    "slash-completion-menu.command.match": "fg:#AFE3F1 bold",
    "slash-completion-menu.meta": "fg:#A3A3A3",
    "slash-completion-menu.command.current": "bg:#243C54 fg:#F4F4F5 bold",
    "slash-completion-menu.command.match.current": "bg:#243C54 fg:#AFE3F1 bold",
    "slash-completion-menu.meta.current": "bg:#243C54 fg:#A3A3A3",
    "slash-completion-menu.row.current": "bg:#243C54",
    "shell-dialog": "fg:#F4F4F5",
    "shell-dialog.title": "fg:#F4F4F5 bold",
    "shell-dialog.border": "fg:#2B3A52",
    "shell-dialog.option": "fg:#A3A3A3",
    "shell-dialog.option.current": "bg:#243C54 fg:#F4F4F5 bold",
    "shell-footer.key": "fg:#AFE3F1 bold",
    "shell-footer.meta": "fg:#A3A3A3",
    "shell-footer.warning": "fg:#E6B450",
    "shell-footer.error": "fg:#EF5E62",
}

_PROMPT_STYLE_LIGHT = {
    "bottom-toolbar": "noreverse",
    "compact-input": "",
    "compact-input.prompt": "fg:#213853 bold",
    "compact-input.frame": "fg:#495F7C",
    "running-prompt-placeholder": "fg:#666666 italic",
    "running-prompt-separator": "fg:#C8BEC0",
    "slash-completion-menu": "",
    "slash-completion-menu.separator": "fg:#C8BEC0",
    "slash-completion-menu.marker": "fg:#8A93A0",
    "slash-completion-menu.marker.current": "fg:#176B7E bold",
    "slash-completion-menu.command": "fg:#4b5563",
    "slash-completion-menu.command.match": "fg:#176B7E bold",
    "slash-completion-menu.meta": "fg:#666666",
    "slash-completion-menu.command.current": "bg:#E6F2F6 fg:#213853 bold",
    "slash-completion-menu.command.match.current": "bg:#E6F2F6 fg:#176B7E bold",
    "slash-completion-menu.meta.current": "bg:#E6F2F6 fg:#666666",
    "slash-completion-menu.row.current": "bg:#E6F2F6",
    "shell-dialog": "fg:#374151",
    "shell-dialog.title": "fg:#213853 bold",
    "shell-dialog.border": "fg:#C8BEC0",
    "shell-dialog.option": "fg:#666666",
    "shell-dialog.option.current": "bg:#E6F2F6 fg:#213853 bold",
    "shell-footer.key": "fg:#176B7E bold",
    "shell-footer.meta": "fg:#666666",
    "shell-footer.warning": "fg:#9A6B18",
    "shell-footer.error": "fg:#C0392B",
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
    separator="fg:#2B3A52",
    yolo_label="bold fg:#E6B450",
    auto_label="bold fg:#7BC97F",
    plan_label="bold fg:#AFE3F1",
    plan_prompt="fg:#AFE3F1",
    cwd="fg:#5F6B7E",
    bg_tasks="fg:#A3A3A3",
    tip="fg:#A3A3A3",
    tip_key="fg:#A3A3A3 bold",
)

_TOOLBAR_LIGHT = ToolbarColors(
    separator="fg:#C8BEC0",
    yolo_label="bold fg:#9A6B18",
    auto_label="bold fg:#2C7A39",
    plan_label="bold fg:#176B7E",
    plan_prompt="fg:#176B7E",
    cwd="fg:#8A93A0",
    bg_tasks="fg:#666666",
    tip="fg:#666666",
    tip_key="fg:#666666 bold",
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


# Markdown/report role mapping: prose-heavy output stays professional and
# low-chrome. Headings/strong text use primary text, emphasis/quotes use muted
# grey, code/links use blue, and status accents stay green/red.
# All values are derived from TuiTokens so there is a single source of truth.
def _build_markdown_colors(tokens: TuiTokens) -> MarkdownColors:
    return MarkdownColors(
        heading=tokens.tool_title,
        emphasis=tokens.muted,
        strong=tokens.tool_title,
        inline_code=tokens.info,
        link=tokens.info,
        quote=tokens.muted,
        table_border=tokens.border_muted,
        code_block_border=tokens.border_muted,
        code_block_bg=tokens.code_block_bg,
        spinner_active=tokens.info,
        spinner_done=tokens.success,
        spinner_failed=tokens.error,
    )


def get_markdown_colors(theme: ThemeName | None = None) -> MarkdownColors:
    name = theme if theme is not None else _active_theme
    tokens = _TUI_TOKENS_LIGHT if name == "light" else _TUI_TOKENS_DARK
    return _build_markdown_colors(tokens)


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
    detail="fg:#A3A3A3",
    connected="fg:#7BC97F",
    connecting="fg:#AFE3F1",
    pending="fg:#E6B450",
    failed="fg:#EF5E62",
)

_MCP_PROMPT_LIGHT = MCPPromptColors(
    text="fg:#213853",
    detail="fg:#666666",
    connected="fg:#2C7A39",
    connecting="fg:#176B7E",
    pending="fg:#9A6B18",
    failed="fg:#C0392B",
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
    info: str
    success: str
    error: str
    warning: str
    muted: str
    dim: str
    text: str
    thinking_text: str
    activity_label: str
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
    # Code block background (used by markdown renderer)
    code_block_bg: str


TUI_TOKEN_NAMES = frozenset(field.name for field in fields(TuiTokens))


_TUI_TOKENS_DARK = TuiTokens(
    accent="#5EA7E8",
    border="#3A506D",
    border_accent="#AFE3F1",
    border_muted="#2B3A52",
    info="#AFE3F1",
    success="#7BC97F",
    error="#EF5E62",
    warning="#E6B450",
    muted="#A3A3A3",
    dim="#5F6B7E",
    text="",
    thinking_text="#8A8A8A",
    activity_label="#F4F4F5",
    selected_bg="#243C54",
    user_message_bg="#1B2738",
    user_message_text="",
    custom_message_bg="#16242E",
    custom_message_text="",
    custom_message_label="#AFE3F1",
    tool_pending_bg="#1B2230",
    tool_success_bg="#16271C",
    tool_error_bg="#2E1D24",
    tool_title="#F4F4F5",
    tool_output="#A3A3A3",
    tool_diff_added="#7BC97F",
    tool_diff_removed="#EF5E62",
    tool_diff_context="#A3A3A3",
    bash_mode="#7BC97F",
    code_block_bg="#1f2030",
)


_TUI_TOKENS_LIGHT = TuiTokens(
    accent="#256EA8",
    border="#495F7C",
    border_accent="#176B7E",
    border_muted="#C8BEC0",
    info="#176B7E",
    success="#2C7A39",
    error="#C0392B",
    warning="#9A6B18",
    muted="#666666",
    dim="#8A93A0",
    text="#213853",
    thinking_text="#6B6B6B",
    activity_label="#213853",
    selected_bg="#E6F2F6",
    user_message_bg="#F0E4E4",
    user_message_text="",
    custom_message_bg="#E6F2F6",
    custom_message_text="",
    custom_message_label="#176B7E",
    tool_pending_bg="#EFE7E8",
    tool_success_bg="#E4F0E6",
    tool_error_bg="#F6E3E3",
    tool_title="#213853",
    tool_output="#666666",
    tool_diff_added="#2C7A39",
    tool_diff_removed="#C0392B",
    tool_diff_context="#666666",
    bash_mode="#2C7A39",
    code_block_bg="#f1f5f9",
)

# Pre-built markdown palettes derived from the canonical token instances.
_MARKDOWN_DARK = _build_markdown_colors(_TUI_TOKENS_DARK)
_MARKDOWN_LIGHT = _build_markdown_colors(_TUI_TOKENS_LIGHT)


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
