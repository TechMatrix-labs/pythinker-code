# pyright: reportUnusedClass=false
"""Renderable block components for the streaming agent view.

Each block receives data via method calls and produces Rich renderables.
They have no knowledge of the event loop or prompt_toolkit.
"""

from __future__ import annotations

import json
import random
import time
from collections import deque
from typing import Any, NamedTuple, cast

import streamingjson  # type: ignore[reportMissingTypeStubs]
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.style import Style
from rich.text import Text

from pythinker_code.soul import format_context_status, format_token_count
from pythinker_code.tools import extract_key_argument
from pythinker_code.ui.shell.components import ToolExecutionComponent
from pythinker_code.ui.shell.components.markdown import (
    PythinkerMarkdown as Markdown,
)
from pythinker_code.ui.shell.components.markdown import (
    markdown_commit_boundary,
)
from pythinker_code.ui.shell.console import console, current_console_width
from pythinker_code.ui.shell.motion import (
    ActivitySnapshot,
    activity_status_line,
)
from pythinker_code.ui.shell.tips import FEATURE_TIPS
from pythinker_code.ui.shell.tool_renderers import (
    ToolResultPayload,
    get_tool_renderer,
)
from pythinker_code.ui.shell.tool_renderers.generic import generic_renderer
from pythinker_code.ui.shell.visualize._activity_tree import ActivityRow, render_activity_tree
from pythinker_code.ui.shell.visualize._worklog import (
    WorkLogState,
    denied_error,
    render_display_blocks,
    render_worklog_entry,
    tool_style,
)
from pythinker_code.ui.theme import tui_rich_style
from pythinker_code.ui.tui_config import is_card_style
from pythinker_code.utils.datetime import format_elapsed
from pythinker_code.utils.rich.columns import BulletColumns
from pythinker_code.wire.types import (
    MCPStatusSnapshot,
    Notification,
    StatusUpdate,
    ToolCall,
    ToolCallPart,
    ToolResult,
    ToolReturnValue,
)

_ELLIPSIS = "..."
_THINKING_PREVIEW_LINES = 6
MAX_SUBAGENT_TOOL_CALLS_TO_SHOW = 4

# Background-agent statuses that mean "still running" — the tool call result
# has arrived but the spawned agent has not yet finished.  Blocks with this
# status must stay in the Live area so their spinner keeps animating.
_AGENT_ACTIVE_STATUSES = frozenset({"created", "starting", "running", "awaiting_approval"})
_TODO_TOOL_NAMES = frozenset({"SetTodoList", "TodoWrite"})


def _is_active_background_agent(tool_name: str, result_text: str) -> bool:
    """Return True when result_text represents a still-running background Agent."""
    if tool_name != "Agent":
        return False
    values: dict[str, str] = {}
    for line in result_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            values[k.strip()] = v.strip()
    return values.get("kind") == "agent" and values.get("status") in _AGENT_ACTIVE_STATUSES


def _truncate_to_display_width(line: str, max_width: int) -> str:
    """Truncate *line* so its terminal display width fits within *max_width*.

    Uses ``rich.cells.cell_len`` for CJK-aware column width measurement.
    """
    from rich.cells import cell_len

    if cell_len(line) <= max_width:
        return line
    ellipsis_width = cell_len(_ELLIPSIS)
    budget = max_width - ellipsis_width
    width = 0
    for i, ch in enumerate(line):
        width += cell_len(ch)
        if width > budget:
            return line[:i] + _ELLIPSIS
    return line


def _estimate_tokens(text: str) -> float:
    """Estimate token count for mixed CJK/Latin text.

    Returns a **float** so that callers can accumulate across small chunks
    without per-chunk floor truncation (e.g. a 3-char ASCII chunk would
    yield 0 if truncated to int immediately, but 0.75 as float).

    Heuristics based on common BPE tokenizers (cl100k, o200k):
    - CJK ideographs: ~1.5 tokens per character (often split into 2-byte pieces)
    - Latin / ASCII: ~1 token per 4 characters (words average ~4 chars)
    """
    cjk = 0
    other = 0
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
            or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
            or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility Ideographs
            or 0x3000 <= cp <= 0x303F  # CJK Symbols and Punctuation
            or 0xFF00 <= cp <= 0xFFEF  # Fullwidth Forms
        ):
            cjk += 1
        else:
            other += 1
    return cjk * 1.5 + other / 4


def _find_committed_boundary(text: str) -> int | None:
    """Return the character offset up to which *text* can be safely committed."""
    return markdown_commit_boundary(text)


def _tail_lines(text: str, n: int) -> str:
    """Extract the last *n* lines from *text* via reverse scanning (O(n))."""
    pos = len(text)
    for _ in range(n):
        pos = text.rfind("\n", 0, pos)
        if pos == -1:
            return text
    return text[pos + 1 :]


class _ContentBlock:
    """Streaming content block with incremental markdown commitment.

    For **composing** (``is_think=False``), confirmed markdown blocks are flushed
    to the terminal permanently via ``console.print()`` as they become complete,
    giving users real-time streaming output.  Only the unconfirmed tail remains
    in the transient Rich Live area.

    For **thinking** (``is_think=True``), the default behavior is to keep the
    raw reasoning text only for token accounting and never render it.  The
    Live area shows a compact ``Thinking`` label with an animated bullet
    sequence, elapsed time, token count, and a live tokens/second pulse;
    when the block ends, a one-liner ``Thought for Xs · N tokens`` is
    committed to history in grey italics.

    When ``show_thinking_stream=True``, the legacy behavior is restored: the
    Live area shows a ``Thinking...`` spinner above a 6-line scrolling preview
    of the raw reasoning text, and the full reasoning markdown is committed
    to history when the block ends.
    """

    def __init__(self, is_think: bool, *, show_thinking_stream: bool = False):
        self.is_think = is_think
        self._show_thinking_stream = show_thinking_stream
        self.raw_text = ""
        # Accumulated float estimate — avoids per-chunk int truncation.
        self._token_count: float = 0.0
        self._start_time = time.monotonic()
        # Incremental commitment state (composing only).
        self._committed_len = 0
        self._has_printed_bullet = False

    # -- Public API ----------------------------------------------------------

    def append(self, content: str) -> None:
        self.raw_text += content
        self._token_count += _estimate_tokens(content)
        # Block boundaries require newlines; skip parse for mid-line chunks.
        if not self.is_think and "\n" in content:
            self._flush_committed()

    def compose(self) -> RenderableType:
        """Render the transient Live area content.

        Thinking mode shows the italic ``Thinking`` label with animated
        bullets; composing mode shows the dots spinner over the
        uncommitted markdown tail.  When ``show_thinking_stream`` is enabled,
        thinking mode falls back to the legacy ``Thinking...`` spinner stacked
        above a 6-line scrolling preview of the raw reasoning text.
        """
        if self.is_think:
            if self._show_thinking_stream:
                return self._compose_thinking_stream()
            return self._compose_thinking()
        return self._compose_spinner()

    def compose_final(self) -> RenderableType:
        """Render the remaining uncommitted content when the block ends."""
        if self.is_think:
            if self._show_thinking_stream:
                remaining = self._pending_text()
                if not remaining:
                    return Text("")
                thinking_style = tui_rich_style("thinking_text")
                # Render reasoning as plain muted text — not themed Markdown — so
                # it reads as uniform grey rather than picking up bright heading /
                # purple emphasis colors.
                return BulletColumns(
                    Text(remaining, style=thinking_style + Style(italic=True)),
                    bullet_style=thinking_style,
                )
            elapsed_str = format_elapsed(time.monotonic() - self._start_time)
            count_str = format_token_count(int(self._token_count))
            return Text(
                f"Thought for {elapsed_str} · {count_str} tokens",
                style=tui_rich_style("thinking_text") + Style(italic=True),
            )
        remaining = self._pending_text()
        if not remaining:
            return Text("")
        return self._wrap_bullet(Markdown(remaining))

    def has_pending(self) -> bool:
        """Whether there is uncommitted content to flush."""
        # Thinking blocks always commit a final trace line if any content
        # was received, so gate on raw_text rather than uncommitted length.
        if self.is_think:
            return bool(self.raw_text)
        return bool(self._pending_text())

    # -- Private -------------------------------------------------------------

    def _pending_text(self) -> str:
        return self.raw_text[self._committed_len :]

    def _wrap_bullet(self, renderable: RenderableType) -> BulletColumns:
        """First call gets the ``•`` bullet; subsequent calls get a space."""
        if self._has_printed_bullet:
            return BulletColumns(renderable, bullet=Text(" "))
        self._has_printed_bullet = True
        return BulletColumns(renderable)

    @property
    def has_emitted_to_scrollback(self) -> bool:
        """Whether any part of this block has been printed to scrollback yet."""
        return self._has_printed_bullet

    def _flush_committed(self) -> None:
        """Commit confirmed markdown blocks to permanent terminal output."""
        pending = self._pending_text()
        if not pending:
            return
        boundary = _find_committed_boundary(pending)
        if boundary is None:
            return
        committed_text = pending[:boundary]
        if not self._has_printed_bullet:
            # Leading blank row separates this step from the previous block.
            console.print()
        console.print(self._wrap_bullet(Markdown(committed_text)))
        self._committed_len += boundary

    def _activity_snapshot(
        self, label: str, *, label_style: Style | None = None
    ) -> ActivitySnapshot:
        elapsed = time.monotonic() - self._start_time
        tokens_int = int(self._token_count)
        token_rate = None
        if elapsed > 0.5 and tokens_int > 0:
            rate = int(tokens_int / elapsed)
            token_rate = rate if rate > 0 else None
        return ActivitySnapshot(
            label=label,
            elapsed_s=elapsed,
            tokens=tokens_int,
            token_rate=token_rate,
            label_style=label_style,
            # Composing / Thinking use the morphing filled shape, not braille dots.
            spinner="shape",
        )

    def _compose_spinner(self) -> Text:
        return activity_status_line(
            self._activity_snapshot("Composing", label_style=tui_rich_style("thinking_text")),
            width=current_console_width(),
        )

    def _compose_thinking_stream(self) -> RenderableType:
        """Legacy 'Thinking...' spinner stacked over a 6-line scrolling preview."""
        spinner = self._compose_thinking_spinner()
        pending = self._pending_text()
        if not pending:
            return spinner
        preview = self._build_preview(pending)
        preview_style = tui_rich_style("thinking_text") + Style(italic=True)
        return Group(spinner, Text(preview, style=preview_style))

    def _compose_thinking_spinner(self) -> Text:
        return activity_status_line(
            self._activity_snapshot("Thinking", label_style=tui_rich_style("thinking_text")),
            width=current_console_width(),
        )

    def _build_preview(self, text: str) -> str:
        """Tail-trim *text* to the last ``_THINKING_PREVIEW_LINES`` and clamp width."""
        max_width = current_console_width() - 2
        tail_text = _tail_lines(text, _THINKING_PREVIEW_LINES)
        lines = tail_text.split("\n")
        return "\n".join(_truncate_to_display_width(line, max_width) for line in lines)

    def _compose_thinking(self) -> Text:
        return activity_status_line(
            self._activity_snapshot("Thinking", label_style=tui_rich_style("thinking_text")),
            width=current_console_width(),
        )


class _ToolCallBlock:
    class FinishedSubCall(NamedTuple):
        call: ToolCall
        result: ToolReturnValue

    def __init__(self, tool_call: ToolCall):
        self._tool_name = tool_call.function.name
        self._tool_call_id = tool_call.id
        self._lexer = streamingjson.Lexer()
        if tool_call.function.arguments is not None:
            self._lexer.append_string(tool_call.function.arguments)

        self._argument = self._extract_worklog_argument(
            tool_call.function.arguments, self._tool_name
        )
        self._result: ToolReturnValue | None = None
        self._subagent_id: str | None = None
        self._subagent_type: str | None = None

        self._ongoing_subagent_tool_calls: dict[str, ToolCall] = {}
        self._last_subagent_tool_call: ToolCall | None = None
        self._n_finished_subagent_tool_calls = 0
        self._finished_subagent_tool_calls = deque[_ToolCallBlock.FinishedSubCall](
            maxlen=MAX_SUBAGENT_TOOL_CALLS_TO_SHOW
        )
        # Pythinker card: lazily built when the tui style is "card" AND a
        # renderer is registered for this tool. Stays None on the legacy
        # ``pythinker`` worklog path so that rendering is bit-for-bit
        # unchanged.
        self._tui_card: ToolExecutionComponent | None = None
        # True while the Agent tool result indicates a still-running background
        # agent.  The block stays in _tool_call_blocks (and in the Live area)
        # rather than being flushed to static scrollback, so the spinner keeps
        # animating at the Live refresh rate.
        self._is_background_pending: bool = False

        self._renderable: RenderableType = self._compose()

    def compose(self) -> RenderableType:
        # Running tool cards and background-pending Agent cards include live
        # status markers. Recompose them on each Live/prompt refresh.
        if self._result is None or self._is_background_pending:
            return self._compose()
        return self._renderable

    @property
    def tool_call_id(self) -> str:
        return self._tool_call_id

    @property
    def is_todo_list(self) -> bool:
        return self._tool_name in _TODO_TOOL_NAMES

    @property
    def finished(self) -> bool:
        return self._result is not None

    @property
    def is_background_pending(self) -> bool:
        return self._is_background_pending

    @property
    def has_expandable_card(self) -> bool:
        return self._tui_card is not None and self._tui_card.can_expand

    def toggle_expanded(self) -> None:
        if self._tui_card is None:
            return
        self._tui_card.toggle_expanded()
        self._renderable = self._compose()

    def append_args_part(self, args_part: str):
        if self.finished:
            return
        self._lexer.append_string(args_part)
        # TODO: maybe don't extract detail if it's already stable
        argument = self._extract_worklog_argument(self._lexer.complete_json(), self._tool_name)
        if argument and argument != self._argument:
            self._argument = argument
            self._renderable = self._compose()

    def finish(self, result: ToolReturnValue):
        self._result = result
        result_text = self._card_result_text(result)
        self._is_background_pending = _is_active_background_agent(self._tool_name, result_text)
        self._renderable = self._compose()

    def append_sub_tool_call(self, tool_call: ToolCall):
        self._ongoing_subagent_tool_calls[tool_call.id] = tool_call
        self._last_subagent_tool_call = tool_call

    def append_sub_tool_call_part(self, tool_call_part: ToolCallPart):
        if self._last_subagent_tool_call is None:
            return
        if not tool_call_part.arguments_part:
            return
        if self._last_subagent_tool_call.function.arguments is None:
            self._last_subagent_tool_call.function.arguments = tool_call_part.arguments_part
        else:
            self._last_subagent_tool_call.function.arguments += tool_call_part.arguments_part

    def finish_sub_tool_call(self, tool_result: ToolResult):
        self._last_subagent_tool_call = None
        sub_tool_call = self._ongoing_subagent_tool_calls.pop(tool_result.tool_call_id, None)
        if sub_tool_call is None:
            return

        self._finished_subagent_tool_calls.append(
            _ToolCallBlock.FinishedSubCall(
                call=sub_tool_call,
                result=tool_result.return_value,
            )
        )
        self._n_finished_subagent_tool_calls += 1
        self._renderable = self._compose()

    def set_subagent_metadata(self, agent_id: str, subagent_type: str) -> None:
        changed = (self._subagent_id, self._subagent_type) != (agent_id, subagent_type)
        self._subagent_id = agent_id
        self._subagent_type = subagent_type
        if changed:
            self._renderable = self._compose()

    def _compose(self) -> RenderableType:
        if is_card_style():
            card_rendered = self._compose_card()
            if card_rendered is not None:
                return card_rendered
        children: list[RenderableType] = []
        if self._subagent_id is not None and self._subagent_type is not None:
            children.append(
                BulletColumns(
                    Text(
                        f"subagent {self._subagent_type} ({self._subagent_id})",
                        style=tui_rich_style("muted"),
                    ),
                    bullet_style=tui_rich_style("muted"),
                )
            )

        style = tool_style(self._tool_name)
        if style.label == "Subagent" and self._result is not None:
            if self._n_finished_subagent_tool_calls:
                summary = Text(
                    f"{self._n_finished_subagent_tool_calls} tool calls completed",
                    style=tui_rich_style("muted"),
                )
                if self._finished_subagent_tool_calls:
                    summary.append(
                        f" · {len(self._finished_subagent_tool_calls)} recent tracked",
                        style=tui_rich_style("muted"),
                    )
                children.append(BulletColumns(summary, bullet_style=tui_rich_style("muted")))
        elif self._n_finished_subagent_tool_calls > MAX_SUBAGENT_TOOL_CALLS_TO_SHOW:
            n_hidden = self._n_finished_subagent_tool_calls - MAX_SUBAGENT_TOOL_CALLS_TO_SHOW
            children.append(
                BulletColumns(
                    Text(
                        f"{n_hidden} more tool call{'s' if n_hidden > 1 else ''} ...",
                        style=tui_rich_style("muted") + Style(italic=True),
                    ),
                    bullet_style=tui_rich_style("muted"),
                )
            )
        if not (style.label == "Subagent" and self._result is not None):
            rows: list[ActivityRow] = []
            for sub_call, sub_result in self._finished_subagent_tool_calls:
                argument = extract_key_argument(
                    sub_call.function.arguments or "", sub_call.function.name
                )
                detail = sub_call.function.name
                if argument:
                    detail = f"{detail} {argument}"
                rows.append(
                    ActivityRow(
                        label="agent",
                        detail=detail,
                        state="failed" if sub_result.is_error else "completed",
                    )
                )
            if rows:
                children.append(render_activity_tree(rows, width=current_console_width()))

        if self._result is None:
            return render_worklog_entry(
                label=style.label,
                target=self._argument,
                state=WorkLogState.RUNNING,
                icon=style.icon,
                icon_style=style.style,
                children=children,
            )

        error_message = self._result.message if self._result.is_error else ""
        if self._result.is_error and not error_message:
            error_message = getattr(self._result, "brief", "") or "Tool failed"
        state = (
            WorkLogState.DENIED
            if self._result.is_error and denied_error(error_message)
            else WorkLogState.FAILED
            if self._result.is_error
            else WorkLogState.COMPLETED
        )
        children.extend(
            render_display_blocks(
                getattr(self._result, "display", []) or [], is_error=self._result.is_error
            )
        )
        return render_worklog_entry(
            label=style.label,
            target=self._argument,
            state=state,
            detail=error_message if self._result.is_error else None,
            icon=style.icon,
            icon_style=style.style,
            children=children,
        )

    def _compose_card(self) -> RenderableType | None:
        """Build/update the Pythinker card. Returns None to fall through.

        Renderer resolution: prefer a tool-specific renderer registered
        under ``tool_name``; fall back to the generic renderer so any
        tool gets a Pythinker card under the flag. Returns None only if
        the generic renderer itself is missing (i.e. the built-ins were
        never registered).
        """
        definition = get_tool_renderer(self._tool_name)
        if definition is None:
            definition = generic_renderer()
        if self._tui_card is None:
            self._tui_card = ToolExecutionComponent(
                self._tool_name,
                self._tool_call_id,
                definition=definition,
            )
            # We see the tool call event, so the model has begun work.
            self._tui_card.mark_execution_started()
        raw_args = self._lexer.complete_json() or "{}"
        try:
            parsed = json.loads(raw_args, strict=False)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            self._tui_card.update_args(cast(dict[str, Any], parsed))
        # Args are complete once a result lands; before that we treat
        # complete_json output as best-effort.
        if self._result is not None:
            self._tui_card.set_args_complete()
            self._tui_card.set_result(
                ToolResultPayload(
                    text=self._card_result_text(self._result),
                    is_error=self._result.is_error,
                    details=self._card_result_details(self._result),
                ),
                is_partial=self._is_background_pending,
            )
        return self._tui_card.render()

    @staticmethod
    def _card_result_details(result: ToolReturnValue) -> dict[str, Any]:
        """Preserve structured tool result data for Blackbox-style cards.

        The legacy card boundary only passed flattened text, which made exact
        file/shell renderers impossible: diffs lost their display blocks,
        shell status lost its machine-readable status, and success messages
        were mixed into stdout.  Keep the text fallback, but also expose the
        safe in-process fields that renderers can choose to consume.
        """
        output = result.output if isinstance(result.output, str) else ""
        return {
            "output": output,
            "message": result.message,
            "display": getattr(result, "display", []) or [],
            "extras": getattr(result, "extras", None) or {},
        }

    @staticmethod
    def _card_result_text(result: ToolReturnValue) -> str:
        """Flatten a ToolReturnValue to a single text payload for cards.

        Tool renderers expect the *primary content* (file body, command
        output, grep matches) — that lives in ``output`` for Pythinker.
        Fall back to ``message`` (e.g. "Successfully wrote N bytes" from
        WriteFile, where ``output`` is empty) and finally ``brief`` for
        tools that only emit a summary block. Non-string outputs are
        skipped here; specialized renderers should pull richer detail
        from ``ctx.args``.
        """
        if result.is_error:
            parts: list[str] = []
            if result.message:
                parts.append(result.message)
            if isinstance(result.output, str) and result.output:
                parts.append(result.output)
            if not parts:
                brief = getattr(result, "brief", "") or "Tool failed"
                parts.append(brief)
            return "\n\n".join(parts)
        if isinstance(result.output, str) and result.output:
            return result.output
        if result.message:
            return result.message
        return getattr(result, "brief", "") or ""

    @staticmethod
    def _extract_worklog_argument(arguments: str | None, tool_name: str) -> str | None:
        argument = extract_key_argument(arguments or "", tool_name)
        try:
            args = json.loads(arguments or "{}", strict=False)
        except json.JSONDecodeError:
            return argument
        if not isinstance(args, dict):
            return argument
        args = cast(dict[str, Any], args)
        match tool_name:
            case "ReadFile":
                path = args.get("path") or args.get("file_path")
                return str(path) if path else argument
            case _:
                return argument

    @staticmethod
    def _extract_full_url(arguments: str | None, tool_name: str) -> str | None:
        """Extract the full URL from FetchURL tool arguments."""
        if tool_name != "FetchURL" or not arguments:
            return None
        try:
            args = json.loads(arguments, strict=False)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(args, dict):
            url = cast(dict[str, Any], args).get("url")
            if url:
                return str(url)
        return None


class _NotificationBlock:
    _SEVERITY_STYLE = {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red",
    }

    def __init__(self, notification: Notification):
        self.notification = notification

    def compose(self) -> RenderableType:
        style = self._SEVERITY_STYLE.get(self.notification.severity, "cyan")
        lines: list[RenderableType] = [Text(self.notification.title, style=f"bold {style}")]
        body = self.notification.body.strip()
        if body:
            body_lines = body.splitlines()
            preview = "\n".join(body_lines[:2])
            if len(body_lines) > 2:
                preview += "\n..."
            lines.append(Text(preview, style=tui_rich_style("muted")))
        return BulletColumns(Group(*lines), bullet_style=style)


class _StatusBlock:
    def __init__(self, initial: StatusUpdate) -> None:
        self.text = Text("", justify="right")
        self._context_usage: float = 0.0
        self._context_tokens: int = 0
        self._max_context_tokens: int = 0
        self._mcp_status: MCPStatusSnapshot | None = None
        self.update(initial)

    def render(self) -> RenderableType:
        return self.text

    def update(self, status: StatusUpdate) -> None:
        if status.context_usage is not None:
            self._context_usage = status.context_usage
        if status.context_tokens is not None:
            self._context_tokens = status.context_tokens
        if status.max_context_tokens is not None:
            self._max_context_tokens = status.max_context_tokens
        if status.mcp_status is not None:
            self._mcp_status = status.mcp_status
        if status.context_usage is not None or status.mcp_status is not None:
            parts: list[str] = []
            if self._context_usage or self._max_context_tokens:
                parts.append(
                    format_context_status(
                        self._context_usage,
                        self._context_tokens,
                        self._max_context_tokens,
                    )
                )
            if self._mcp_status is not None and self._mcp_status.loading:
                parts.append(
                    f"MCP {self._mcp_status.connected}/{self._mcp_status.total} · "
                    f"{self._mcp_status.tools} tools"
                )
            self.text.plain = "  ".join(parts)


class _CompactionBlock:
    """Animated compaction progress with a time-based estimate.

    The bar fills toward 95% over ``EXPECTED_DURATION_S`` (compaction has no
    real progress signal), then disappears once ``CompactionEnd`` arrives.
    """

    BAR_WIDTH = 40
    EXPECTED_DURATION_S = 60.0
    MAX_ESTIMATED_PROGRESS = 0.95

    TIPS: tuple[str, ...] = FEATURE_TIPS

    def __init__(self, *, context_tokens: int | None = None) -> None:
        self._start = time.monotonic()
        self._tip = random.choice(self.TIPS)
        self._context_tokens = context_tokens

    def update_context_tokens(self, context_tokens: int | None) -> None:
        """Refresh the token count shown in the compacting title."""
        if context_tokens is not None:
            self._context_tokens = context_tokens

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from console.render(self._render(), options)

    def _render(self) -> RenderableType:
        elapsed = max(0.0, time.monotonic() - self._start)
        progress = min(elapsed / self.EXPECTED_DURATION_S, self.MAX_ESTIMATED_PROGRESS)
        filled = int(round(progress * self.BAR_WIDTH))
        empty = self.BAR_WIDTH - filled
        pct = int(progress * 100)
        accent = tui_rich_style("accent")
        muted = tui_rich_style("muted")
        subtle = tui_rich_style("dim")
        title_style = accent + Style(italic=True)

        title = Text()
        title.append("✢ ", style=accent)
        title.append("Compacting conversation…", style=title_style)
        title.append(f" ({format_elapsed(elapsed)}", style=subtle)
        if self._context_tokens is not None:
            title.append(f" · ↑ {format_token_count(self._context_tokens)} tokens", style=subtle)
        title.append(")", style=subtle)

        bar = Text("  ")
        bar.append("▰" * filled, style=tui_rich_style("activity_label"))
        bar.append("▱" * empty, style=muted)
        bar.append(f" {pct}%", style=muted)

        tip = Text("  ⎿  ", style=muted)
        tip.append(f"Tip: {self._tip}", style=subtle)

        return Group(title, bar, tip)
