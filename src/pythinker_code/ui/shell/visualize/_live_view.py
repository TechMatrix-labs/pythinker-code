# pyright: reportPrivateUsage=false, reportUnusedClass=false
"""Base event-consuming view for the streaming agent (Rich Live mode).

``_LiveView`` consumes wire events, updates internal state (content blocks,
tool calls, spinners, approval/question queues), and composes them into a
Rich renderable via ``compose()``.  The Rich ``Live`` context drives refresh.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Literal

from pythinker_core.message import Message
from pythinker_core.tooling import ToolError, ToolOk, ToolReturnValue
from rich import box
from rich.console import Group, RenderableType
from rich.live import Live
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from pythinker_code.tools.display import TodoDisplayBlock, TodoDisplayItem
from pythinker_code.ui.shell.components.render_utils import truncate_to_width
from pythinker_code.ui.shell.console import console, current_console_width
from pythinker_code.ui.shell.echo import render_user_echo
from pythinker_code.ui.shell.keyboard import KeyboardListener, KeyEvent
from pythinker_code.ui.shell.motion import (
    ActivitySnapshot,
    activity_status_line,
    reduced_motion_enabled,
)
from pythinker_code.ui.shell.spacing import BLANK_ROW
from pythinker_code.ui.shell.spinner_words import spinner_message
from pythinker_code.ui.shell.tips import current_tip
from pythinker_code.ui.shell.visualize._approval_panel import (
    ApprovalRequestPanel,
    show_approval_in_pager,
)
from pythinker_code.ui.shell.visualize._blocks import (
    Markdown,
    _CompactionBlock,
    _ContentBlock,
    _NotificationBlock,
    _StatusBlock,
    _ToolCallBlock,
)
from pythinker_code.ui.shell.visualize._question_panel import (
    QuestionRequestPanel,
    prompt_other_input,
    show_question_body_in_pager,
)
from pythinker_code.ui.shell.visualize._worklog import render_worklog_card
from pythinker_code.ui.theme import tui_rich_style
from pythinker_code.utils.aioqueue import Queue, QueueShutDown
from pythinker_code.utils.datetime import format_elapsed
from pythinker_code.utils.logging import logger
from pythinker_code.wire import WireUISide
from pythinker_code.wire.types import (
    ApprovalRequest,
    ApprovalResponse,
    BtwBegin,
    BtwEnd,
    CompactionBegin,
    CompactionEnd,
    ContentPart,
    MCPLoadingBegin,
    MCPLoadingEnd,
    Notification,
    PlanDisplay,
    QuestionRequest,
    StatusUpdate,
    SteerInput,
    StepBegin,
    StepInterrupted,
    StepRetry,
    SubagentEvent,
    TextPart,
    ThinkPart,
    ToolCall,
    ToolCallPart,
    ToolCallRequest,
    ToolResult,
    TurnBegin,
    TurnEnd,
    WireMessage,
)

MAX_LIVE_NOTIFICATIONS = 4
EXTERNAL_MESSAGE_GRACE_S = 0.1
_LIVE_VERTICAL_OVERFLOW: Literal["crop", "ellipsis", "visible"] = "ellipsis"
# Canonical inter-block spacer. The live stream owns the gaps *between* action
# blocks; cards/panels must not add external top/bottom spacing (see spacing.py).
_ACTION_SPACER = BLANK_ROW
# Show the rotating feature tip under the spinner only once a turn has been
# running long enough that a quick turn won't flash it.
_WORKING_TIP_MIN_ELAPSED_S = 4.0
_MAX_PINNED_TODO_LINES = 12


def _append_action_block(
    blocks: list[RenderableType], block: RenderableType, *, leading: bool = False
) -> None:
    """Append a live action block with a one-row gap around stream/status rows."""
    if blocks or leading:
        blocks.append(_ACTION_SPACER)
    blocks.append(block)


def _format_step_retry(retry: StepRetry) -> Text:
    reason = _step_retry_reason(retry)
    wait = format_elapsed(retry.wait_s)
    return Text(
        f"Retrying after {reason} · attempt {retry.next_attempt}/{retry.max_attempts} · {wait}",
        style=tui_rich_style("muted") + Style(italic=True),
    )


def _step_retry_reason(retry: StepRetry) -> str:
    if retry.status_code == 429:
        return "rate limit"
    if retry.status_code is not None and retry.status_code >= 500:
        return "server error"
    if retry.error_type == "APITimeoutError":
        return "timeout"
    if retry.error_type == "APIConnectionError":
        return "connection issue"
    if retry.error_type == "APIEmptyResponseError":
        return "empty response"
    return retry.error_type


@asynccontextmanager
async def _keyboard_listener(
    handler: Callable[[KeyboardListener, KeyEvent], Awaitable[None]],
):
    listener = KeyboardListener()
    await listener.start()

    async def _keyboard():
        while True:
            event = await listener.get()
            await handler(listener, event)

    task = asyncio.create_task(_keyboard())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await listener.stop()


class _LiveView:
    def __init__(
        self,
        initial_status: StatusUpdate,
        cancel_event: asyncio.Event | None = None,
        *,
        show_thinking_stream: bool = False,
    ):
        self._cancel_event = cancel_event
        self._show_thinking_stream = show_thinking_stream

        self._active_turn_depth = 0
        self._turn_start_time: float | None = None
        self._latest_context_tokens = initial_status.context_tokens
        self._latest_todos: tuple[TodoDisplayItem, ...] = ()
        self._pinned_todos_visible = True
        self._compaction_block: _CompactionBlock | None = None
        self._mcp_loading_spinner: RenderableType | None = None
        self._btw_spinner: RenderableType | None = None
        self._btw_question: str | None = None

        self._current_content_block: _ContentBlock | None = None
        self._tool_call_blocks: dict[str, _ToolCallBlock] = {}
        self._last_tool_call_block: _ToolCallBlock | None = None
        self._current_step_retry: StepRetry | None = None
        self._approval_request_queue = deque[ApprovalRequest]()
        """
        It is possible that multiple subagents request approvals at the same time,
        in which case we will have to queue them up and show them one by one.
        """
        self._current_approval_request_panel: ApprovalRequestPanel | None = None
        self._question_request_queue = deque[QuestionRequest]()
        self._current_question_panel: QuestionRequestPanel | None = None
        self._notification_blocks = deque[_NotificationBlock]()
        self._live_notification_blocks = deque[_NotificationBlock](maxlen=MAX_LIVE_NOTIFICATIONS)
        self._status_block = _StatusBlock(initial_status)

        self._need_recompose = False
        self._external_messages: Queue[WireMessage] = Queue()

    def _reset_live_shape(self, live: Live) -> None:
        # Rich doesn't expose a public API to clear Live's cached render height.
        # After leaving the pager, stale height causes cursor restores to jump,
        # so we reset the private _shape to re-anchor the next refresh.
        live._live_render._shape = None  # type: ignore[reportPrivateUsage]

    async def _drain_external_message_after_wire_shutdown(
        self,
        external_task: asyncio.Task[WireMessage],
    ) -> tuple[WireMessage | None, asyncio.Task[WireMessage]]:
        try:
            msg = await asyncio.wait_for(
                asyncio.shield(external_task),
                timeout=EXTERNAL_MESSAGE_GRACE_S,
            )
        except (TimeoutError, QueueShutDown):
            return None, external_task
        return msg, asyncio.create_task(self._external_messages.get())

    async def visualize_loop(self, wire: WireUISide):
        with Live(
            self.compose(),
            console=console,
            refresh_per_second=10,
            transient=True,
            # Never let the transient Live region paint beyond the terminal
            # viewport.  Interactive prompt mode has its own row budget; this
            # protects non-interactive Rich Live mode from tall tool cards,
            # approval panels, or streaming output overlapping the screen.
            vertical_overflow=_LIVE_VERTICAL_OVERFLOW,
        ) as live:

            async def keyboard_handler(listener: KeyboardListener, event: KeyEvent) -> None:
                # Handle Ctrl+O specially - pause Live only while the pager is active.
                # Ctrl+E remains accepted as a legacy alias.
                if event in (KeyEvent.CTRL_O, KeyEvent.CTRL_E):
                    if self._has_expandable_modal_panel():
                        from pythinker_code.telemetry import track

                        track("shortcut_expand")
                        await listener.pause()
                        live.stop()
                        try:
                            self._show_expandable_panel_content()
                        finally:
                            # Reset live render shape so the next refresh re-anchors cleanly.
                            # Resume the listener even if restarting Live raises, so the
                            # keyboard never deadlocks paused.
                            try:
                                self._reset_live_shape(live)
                                live.start()
                                live.update(self.compose(), refresh=True)
                            finally:
                                await listener.resume()
                    elif self._toggle_latest_tool_card():
                        live.update(self.compose(), refresh=True)
                    return

                # Handle ENTER/SPACE on question panel when "Other" is selected
                if self._should_prompt_question_other_for_key(event):
                    panel = self._current_question_panel
                    assert panel is not None
                    question_text = panel.current_question_text
                    await listener.pause()
                    live.stop()
                    try:
                        text = await prompt_other_input(question_text)
                    finally:
                        # Always resume the listener, even if restarting Live raises.
                        try:
                            self._reset_live_shape(live)
                            live.start()
                        finally:
                            await listener.resume()

                    self._submit_question_other_text(text)
                    live.update(self.compose(), refresh=True)
                    return

                self.dispatch_keyboard_event(event)
                if self._need_recompose:
                    live.update(self.compose(), refresh=True)
                    self._need_recompose = False

            async with _keyboard_listener(keyboard_handler):
                wire_task = asyncio.create_task(wire.receive())
                external_task = asyncio.create_task(self._external_messages.get())
                try:
                    while True:
                        try:
                            done, _ = await asyncio.wait(
                                [wire_task, external_task],
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if wire_task in done:
                                msg = wire_task.result()
                                wire_task = asyncio.create_task(wire.receive())
                            else:
                                msg = external_task.result()
                                external_task = asyncio.create_task(self._external_messages.get())
                        except QueueShutDown:
                            (
                                msg,
                                external_task,
                            ) = await self._drain_external_message_after_wire_shutdown(
                                external_task
                            )
                            if msg is not None:
                                self.dispatch_wire_message(msg)
                                if self._need_recompose:
                                    live.update(self.compose(), refresh=True)
                                    self._need_recompose = False
                                continue
                            self.cleanup(is_interrupt=False)
                            live.update(self.compose(), refresh=True)
                            break

                        if isinstance(msg, StepInterrupted):
                            self.cleanup(is_interrupt=True)
                            live.update(self.compose(), refresh=True)
                            break

                        self.dispatch_wire_message(msg)
                        if self._need_recompose:
                            live.update(self.compose(), refresh=True)
                            self._need_recompose = False
                finally:
                    wire_task.cancel()
                    external_task.cancel()
                    self._external_messages.shutdown(immediate=True)
                    with suppress(asyncio.CancelledError, QueueShutDown):
                        await wire_task
                    with suppress(asyncio.CancelledError, QueueShutDown):
                        await external_task

    def refresh_soon(self) -> None:
        self._need_recompose = True

    def _on_question_panel_state_changed(self) -> None:
        """Hook for subclasses to react when question panel visibility changes."""
        return None

    def enqueue_external_message(self, msg: WireMessage) -> None:
        try:
            self._external_messages.put_nowait(msg)
        except QueueShutDown:
            logger.debug("Ignoring external wire message after live view shutdown: {msg}", msg=msg)

    def has_expandable_panel(self) -> bool:
        return self._has_expandable_modal_panel() or self._expandable_tool_card() is not None

    def _has_expandable_modal_panel(self) -> bool:
        return (
            self._expandable_approval_panel() is not None
            or self._expandable_question_panel() is not None
        )

    def _expandable_approval_panel(self) -> ApprovalRequestPanel | None:
        panel = self._current_approval_request_panel
        if panel is not None and panel.has_expandable_content:
            return panel
        return None

    def _expandable_question_panel(self) -> QuestionRequestPanel | None:
        panel = self._current_question_panel
        if panel is not None and panel.has_expandable_content:
            return panel
        return None

    def _expandable_tool_card(self) -> _ToolCallBlock | None:
        candidates = list(self._tool_call_blocks.values())
        if self._last_tool_call_block in candidates:
            candidates.remove(self._last_tool_call_block)
            candidates.append(self._last_tool_call_block)
        for block in reversed(candidates):
            if block.has_expandable_card:
                return block
        return None

    def _toggle_latest_tool_card(self) -> bool:
        block = self._expandable_tool_card()
        if block is None:
            return False
        block.toggle_expanded()
        self.refresh_soon()
        return True

    def _show_expandable_panel_content(self) -> bool:
        if approval_panel := self._expandable_approval_panel():
            show_approval_in_pager(approval_panel)
            return True
        if question_panel := self._expandable_question_panel():
            show_question_body_in_pager(question_panel)
            return True
        return False

    def _should_prompt_question_other_for_key(self, key: KeyEvent) -> bool:
        panel = self._current_question_panel
        if panel is None or not panel.should_prompt_other_input():
            return False
        return key == KeyEvent.ENTER or (key == KeyEvent.SPACE and not panel.is_multi_select)

    def _submit_question_other_text(self, text: str) -> None:
        panel = self._current_question_panel
        if panel is None:
            return

        all_done = panel.submit_other(text)
        if all_done:
            panel.request.resolve(panel.get_answers())
            self.show_next_question_request()
        self.refresh_soon()

    # -- Composable rendering --------------------------------------------------

    def compose_interactive_panels(self) -> list[RenderableType]:
        """Approval and question panels — interactive overlays.

        In Non-interactive mode (Rich Live), these are rendered by ``compose()``.
        In Interactive mode (prompt_toolkit), these are rendered by modal
        delegates in Layer 2, so ``render_agent_status()`` skips them to
        avoid double-rendering.
        """
        blocks: list[RenderableType] = []
        if self._current_approval_request_panel:
            blocks.append(self._current_approval_request_panel.render())
        if self._current_question_panel:
            blocks.append(self._current_question_panel.render())
        return blocks

    def compose_agent_output(
        self, *, include_working_indicator: bool = True
    ) -> list[RenderableType]:
        """Spinners, content blocks, tool calls, notifications.

        Pure agent streaming status — no interactive overlays.
        Always safe to render regardless of modal state.

        ``include_working_indicator`` controls whether the trailing verb
        spinner is emitted. The interactive prompt sets it ``False`` so it can
        pin the spinner *below* a clipped agent stream (see
        ``render_pinned_status_tail``), keeping it visible instead of letting
        the clip hint cover it.

        Display priority (highest → lowest):
          1. MCP loading spinner (connecting to servers)
          2. Compaction spinner (context compaction in progress)
          3. Content blocks + tool call blocks (streaming output)
          4. Moon spinner fallback (turn active but nothing else visible)
        The btw spinner is always shown (side-channel, not mutually exclusive).
        """
        blocks: list[RenderableType] = []
        if self._btw_spinner is not None:
            _append_action_block(blocks, self._btw_spinner)
        if self._mcp_loading_spinner is not None:
            _append_action_block(blocks, self._mcp_loading_spinner)
        elif self._compaction_block is not None:
            _append_action_block(blocks, self._compaction_block)
        else:
            current_step_retry = getattr(self, "_current_step_retry", None)
            if current_step_retry is not None:
                _append_action_block(blocks, _format_step_retry(current_step_retry), leading=True)
            if self._current_content_block is not None:
                _append_action_block(blocks, self._current_content_block.compose(), leading=True)
            # When an approval panel is on-screen for a specific tool call, the
            # panel already previews the same command/diff that the pending tool
            # card would show. Suppress the matching card to avoid the duplicate.
            suppressed_tool_call_id: str | None = None
            if self._current_approval_request_panel is not None:
                suppressed_tool_call_id = self._current_approval_request_panel.request.tool_call_id
            for tool_call in list(self._tool_call_blocks.values()):
                if (
                    suppressed_tool_call_id is not None
                    and tool_call.tool_call_id == suppressed_tool_call_id
                ):
                    continue
                if tool_call.is_todo_list:
                    # Todo updates are pinned under the verb spinner; don't also
                    # render a floating todo tool card above the stream.
                    continue
                # leading=True gives the first live tool card a blank row above
                # it too, so a still-running agent is separated from a finished
                # one already committed to scrollback.
                _append_action_block(blocks, tool_call.compose(), leading=True)
            if include_working_indicator and self._active_turn_depth > 0:
                # Keep a stable activity indicator visible even while content or
                # tool cards are already on-screen. This makes long-running
                # background waits feel alive instead of frozen.
                _append_action_block(blocks, self._working_indicator(), leading=True)
        for notification in list(self._live_notification_blocks):
            _append_action_block(blocks, notification.compose())
        return blocks

    def _working_indicator(self) -> RenderableType:
        now = time.monotonic()
        elapsed = 0.0 if self._turn_start_time is None else now - self._turn_start_time
        width = current_console_width()
        line = activity_status_line(
            ActivitySnapshot(label=spinner_message(now), elapsed_s=elapsed),
            width=width,
        )
        todo_block = self._pinned_todo_block(width=width)
        if todo_block is not None:
            return Group(line, todo_block)
        # During longer waits, surface a rotating CLI-feature tip under the verb.
        if elapsed < _WORKING_TIP_MIN_ELAPSED_S:
            return line
        tip = Text("  ⎿  ", style=tui_rich_style("muted"))
        tip.append("Tip: ", style=tui_rich_style("dim"))
        tip.append(current_tip(now), style=tui_rich_style("dim"))
        return Group(line, tip)

    def _pinned_todo_block(self, *, width: int) -> RenderableType | None:
        """Render the single todo source of truth under the pinned verb spinner."""
        if not getattr(self, "_pinned_todos_visible", True):
            return None
        todos = tuple(
            todo
            for todo in getattr(self, "_latest_todos", ())
            if todo.status in ("done", "in_progress", "pending") and todo.title.strip()
        )
        if not todos:
            return None

        visible = todos[:_MAX_PINNED_TODO_LINES]
        hidden = todos[_MAX_PINNED_TODO_LINES:]
        rows: list[Text] = [self._pinned_todo_header(todos, width=width)]
        has_continuation = bool(hidden)
        for index, todo in enumerate(visible):
            is_last_visible = index == len(visible) - 1
            branch = "└─" if is_last_visible and not has_continuation else "├─"
            if todo.status == "done":
                icon = "●"
                icon_token = "success"
                title_token = "muted"
            elif todo.status == "in_progress":
                icon = "■"
                icon_token = "accent"
                title_token = "activity_label"
            else:
                icon = "□"
                icon_token = "muted"
                title_token = "tool_output"
            title_style = tui_rich_style(title_token)
            if todo.status == "in_progress":
                title_style += Style(bold=True)
            prefix = f"     {branch} "
            title_budget = max(1, width - len(prefix) - 2)
            title = truncate_to_width(todo.title.strip(), title_budget)
            row = Text(prefix, style=tui_rich_style("muted"))
            row.append(icon, style=tui_rich_style(icon_token))
            row.append(" ")
            row.append(title, style=title_style)
            rows.append(row)

        if hidden:
            hidden_pending = sum(1 for todo in hidden if todo.status == "pending")
            label = "pending" if hidden_pending == len(hidden) else "more"
            row = Text("     └─ ", style=tui_rich_style("muted"))
            row.append(f"… +{len(hidden)} {label}", style=tui_rich_style("muted"))
            rows.append(row)
        return Group(*rows)

    def toggle_pinned_todos(self) -> bool:
        """Toggle visibility of the pinned todo list and return the new state."""
        self._pinned_todos_visible = not getattr(self, "_pinned_todos_visible", True)
        self.refresh_soon()
        return self._pinned_todos_visible

    def _pinned_todo_header(self, todos: tuple[TodoDisplayItem, ...], *, width: int) -> Text:
        """Render the pinned todo summary line with the same counts as the todo card."""
        total = len(todos)
        done = sum(1 for todo in todos if todo.status == "done")
        active = sum(1 for todo in todos if todo.status == "in_progress")
        pending = sum(1 for todo in todos if todo.status == "pending")
        parts = [f"{done}/{total} done"]
        if active:
            parts.append(f"{active} active")
        if pending:
            parts.append(f"{pending} pending")
        summary = f"todos({' · '.join(parts)})"
        row = Text("  ⎿  ", style=tui_rich_style("muted"))
        row.append(truncate_to_width(summary, max(1, width - 5)), style=tui_rich_style("muted"))
        return row

    def compose(self, *, include_status: bool = True) -> RenderableType:
        """Compose the full live view display content.

        Combines interactive panels (approval/question) and agent output.
        Panels are rendered first so they remain visible at the top of the
        terminal even when tool-call output is long enough to push content
        beyond the visible area.

        In Interactive mode, prefer ``compose_agent_output()`` for Layer 1
        rendering to avoid double-rendering panels that modal delegates
        already handle in Layer 2.
        """
        blocks: list[RenderableType] = []
        blocks.extend(self.compose_interactive_panels())
        agent_blocks = self.compose_agent_output()
        blocks.extend(agent_blocks)
        if include_status:
            # One blank row under the spinner verb (the agent stream's tail)
            # before the status line — but only when the status line has content,
            # since an empty status row already renders as a blank line.
            if agent_blocks and self._status_block.text.plain.strip():
                blocks.append(_ACTION_SPACER)
            blocks.append(self._status_block.render())
        return Group(*blocks)

    def dispatch_wire_message(self, msg: WireMessage) -> None:
        """Dispatch the Wire message to UI components."""
        assert not isinstance(msg, StepInterrupted)  # handled in visualize_loop

        if isinstance(msg, StepBegin):
            self.cleanup(is_interrupt=False)
            self._mcp_loading_spinner = None
            # Defensive: if StepBegin arrives without a preceding TurnBegin
            # (e.g. during replay), ensure the turn is considered active.
            if self._active_turn_depth == 0:
                self._active_turn_depth = 1
                self._turn_start_time = time.monotonic()
            self.refresh_soon()
            return
        if isinstance(msg, StepRetry):
            self.discard_retry_attempt(msg)
            self.refresh_soon()
            return

        match msg:
            case TurnBegin():
                if self._active_turn_depth == 0:
                    self._turn_start_time = time.monotonic()
                self._active_turn_depth += 1
                self.flush_content()
                self.refresh_soon()
            case SteerInput(user_input=user_input):
                self.cleanup(is_interrupt=False)
                content: list[ContentPart]
                if isinstance(user_input, list):
                    content = list(user_input)
                else:
                    content = [TextPart(text=user_input)]
                console.print(render_user_echo(Message(role="user", content=content)))
            case TurnEnd():
                self._active_turn_depth = max(0, self._active_turn_depth - 1)
                if self._active_turn_depth == 0:
                    self._turn_start_time = None
            case CompactionBegin():
                self._compaction_block = _CompactionBlock(
                    context_tokens=self._latest_context_tokens,
                )
                self.refresh_soon()
            case CompactionEnd():
                self._compaction_block = None
                self.refresh_soon()
            case MCPLoadingBegin():
                glyph = (
                    "●" if reduced_motion_enabled() or int(time.monotonic() / 0.8) % 2 == 0 else " "
                )
                line = Text(f"{glyph} ", style=tui_rich_style("muted"))
                line.append("Connecting MCP servers...", style=tui_rich_style("muted"))
                self._mcp_loading_spinner = line
                self.refresh_soon()
            case MCPLoadingEnd():
                self._mcp_loading_spinner = None
                self.refresh_soon()
            case BtwBegin(question=question):
                truncated = (question[:40] + "...") if len(question) > 40 else question
                self._btw_question = question
                glyph = (
                    "●" if reduced_motion_enabled() or int(time.monotonic() / 0.8) % 2 == 0 else " "
                )
                line = Text(f"{glyph} ", style=tui_rich_style("muted"))
                line.append(f"Side question... {truncated}", style=tui_rich_style("muted"))
                self._btw_spinner = line
                self.refresh_soon()
            case BtwEnd(response=response, error=error):
                self._btw_spinner = None
                q = self._btw_question or ""
                truncated_q = (q[:50] + "...") if len(q) > 50 else q
                self._btw_question = None
                if response:
                    console.print(
                        Panel(
                            Markdown(response),
                            title=f"[dim]btw: {rich_escape(truncated_q)}[/dim]",
                            border_style=tui_rich_style("border_muted"),
                            box=box.ROUNDED,
                            padding=(0, 1),
                        )
                    )
                elif error:
                    console.print(
                        Panel(
                            Text(error, style=tui_rich_style("error")),
                            title="[dim]btw (error)[/dim]",
                            border_style=tui_rich_style("error"),
                            box=box.ROUNDED,
                            padding=(0, 1),
                        )
                    )
                self.refresh_soon()
            case StatusUpdate():
                self._status_block.update(msg)
                if msg.context_tokens is not None:
                    self._latest_context_tokens = msg.context_tokens
                    if self._compaction_block is not None:
                        self._compaction_block.update_context_tokens(msg.context_tokens)
            case Notification():
                self.append_notification(msg)
            case ContentPart():
                self.append_content(msg)
            case ToolCall():
                self.append_tool_call(msg)
            case ToolCallPart():
                self.append_tool_call_part(msg)
            case ToolResult():
                self.append_tool_result(msg)
            case ApprovalResponse():
                self._reconcile_approval_requests()
            case SubagentEvent():
                self.handle_subagent_event(msg)
            case PlanDisplay():
                self.display_plan(msg)
            case ApprovalRequest():
                self.request_approval(msg)
            case QuestionRequest():
                self.request_question(msg)
            case ToolCallRequest():
                logger.warning("Unexpected ToolCallRequest in shell UI: {msg}", msg=msg)
            case _:
                pass

    def _try_submit_question(self, method: str = "enter") -> None:
        """Submit the current question answer; if all done, resolve and advance."""
        panel = self._current_question_panel
        if panel is None:
            return
        all_done = panel.submit()
        if all_done:
            from pythinker_code.telemetry import track

            track("question_answered", method=method)
            panel.request.resolve(panel.get_answers())
            self.show_next_question_request()

    def dispatch_keyboard_event(self, event: KeyEvent) -> None:
        # Handle question panel keyboard events
        if self._current_question_panel is not None:
            match event:
                case KeyEvent.UP:
                    self._current_question_panel.move_up()
                case KeyEvent.DOWN:
                    self._current_question_panel.move_down()
                case KeyEvent.LEFT:
                    self._current_question_panel.prev_tab()
                case KeyEvent.RIGHT | KeyEvent.TAB:
                    self._current_question_panel.next_tab()
                case KeyEvent.SPACE:
                    if self._current_question_panel.is_multi_select:
                        self._current_question_panel.toggle_select()
                    else:
                        self._try_submit_question(method="space")
                case KeyEvent.ENTER:
                    # "Other" is handled in keyboard_handler (async context)
                    self._try_submit_question(method="enter")
                case KeyEvent.ESCAPE:
                    from pythinker_code.telemetry import track

                    track("question_dismissed")
                    self._current_question_panel.request.resolve({})
                    self.show_next_question_request()
                case (
                    KeyEvent.NUM_1
                    | KeyEvent.NUM_2
                    | KeyEvent.NUM_3
                    | KeyEvent.NUM_4
                    | KeyEvent.NUM_5
                    | KeyEvent.NUM_6
                ):
                    # Number keys select option in question panel
                    num_map = {
                        KeyEvent.NUM_1: 0,
                        KeyEvent.NUM_2: 1,
                        KeyEvent.NUM_3: 2,
                        KeyEvent.NUM_4: 3,
                        KeyEvent.NUM_5: 4,
                        KeyEvent.NUM_6: 5,
                    }
                    idx = num_map[event]
                    panel = self._current_question_panel
                    if panel.select_index(idx):
                        if panel.is_multi_select:
                            panel.toggle_select()
                        elif not panel.is_other_selected:
                            # Auto-submit for single-select (unless "Other")
                            self._try_submit_question(method="number_key")
                case _:
                    pass
            self.refresh_soon()
            return

        # Ctrl+T toggles the pinned todo list; it is the only todo UI surface.
        if event == KeyEvent.CTRL_T and self._latest_todos:
            self.toggle_pinned_todos()
            return

        # handle ESC key to cancel the run
        if event == KeyEvent.ESCAPE and self._cancel_event is not None:
            from pythinker_code.telemetry import track

            track("cancel")
            self._cancel_event.set()
            return

        # Handle approval panel keyboard events
        if self._current_approval_request_panel is not None:
            match event:
                case KeyEvent.UP:
                    self._current_approval_request_panel.move_up()
                    self.refresh_soon()
                case KeyEvent.DOWN:
                    self._current_approval_request_panel.move_down()
                    self.refresh_soon()
                case KeyEvent.ENTER:
                    self._submit_approval()
                case KeyEvent.NUM_1 | KeyEvent.NUM_2 | KeyEvent.NUM_3 | KeyEvent.NUM_4:
                    # Number keys directly select and submit approval option
                    num_map = {
                        KeyEvent.NUM_1: 0,
                        KeyEvent.NUM_2: 1,
                        KeyEvent.NUM_3: 2,
                        KeyEvent.NUM_4: 3,
                    }
                    idx = num_map[event]
                    if idx < len(self._current_approval_request_panel.options):
                        self._current_approval_request_panel.selected_index = idx
                        self._submit_approval()
                case _:
                    pass
            return

    def _submit_approval(self) -> None:
        """Submit the currently selected approval response."""
        assert self._current_approval_request_panel is not None
        request = self._current_approval_request_panel.request
        resp = self._current_approval_request_panel.get_selected_response()
        request.resolve(resp)
        if resp == "approve_for_session":
            to_remove_from_queue: list[ApprovalRequest] = []
            for request in self._approval_request_queue:
                # approve all queued requests with the same action
                if request.action == self._current_approval_request_panel.request.action:
                    request.resolve("approve_for_session")
                    to_remove_from_queue.append(request)
            for request in to_remove_from_queue:
                self._approval_request_queue.remove(request)
        self.show_next_approval_request()

    def cleanup(self, is_interrupt: bool) -> None:
        """Cleanup the live view on step end or interruption."""
        self.flush_content()

        for block in self._tool_call_blocks.values():
            if not block.finished:
                # this should not happen, but just in case
                block.finish(
                    ToolError(message="", brief="Interrupted")
                    if is_interrupt
                    else ToolOk(output="")
                )
        self._last_tool_call_block = None
        self.flush_finished_tool_calls()
        # Drain background-pending blocks skipped above.  They must be printed
        # to scrollback here; the transient Live area is about to be erased.
        for tool_call_id in list(self._tool_call_blocks.keys()):
            block = self._tool_call_blocks.pop(tool_call_id)
            console.print()
            console.print(block.compose())
            self.refresh_soon()
        self.flush_notifications()

        # Clear transient spinners to prevent visual residuals after interrupts
        self._compaction_block = None
        self._mcp_loading_spinner = None
        self._btw_spinner = None
        self._current_step_retry = None

        if is_interrupt:
            self._active_turn_depth = 0
            self._turn_start_time = None

        while self._approval_request_queue:
            # should not happen, but just in case
            self._approval_request_queue.popleft().resolve("reject")
        self._current_approval_request_panel = None

        while self._question_request_queue:
            self._question_request_queue.popleft().resolve({})
        self._current_question_panel = None

    def discard_retry_attempt(self, retry: StepRetry) -> None:
        """Discard partial streamed state from a failed step attempt.

        The failed attempt may have already streamed content or a tool call into
        the transient Live area. Keep scrollback untouched, but clear the live
        attempt state so the retry status and next attempt do not render beside
        stale partial output.
        """
        self._current_content_block = None
        self._tool_call_blocks.clear()
        self._last_tool_call_block = None
        self._current_step_retry = retry

    def flush_content(self) -> None:
        """Flush the current content block."""
        if self._current_content_block is not None:
            if self._current_content_block.has_pending():
                # One blank row before the block (matching tool cards) so steps
                # are separated — unless this block already streamed earlier
                # paragraphs, in which case this is its continuation.
                if not self._current_content_block.has_emitted_to_scrollback:
                    console.print()
                console.print(self._current_content_block.compose_final())
            self._current_content_block = None
            self.refresh_soon()

    def flush_finished_tool_calls(self) -> None:
        """Flush all leading finished tool call blocks.

        Background-pending blocks (Agent results with still-running status) are
        skipped with ``continue`` instead of stopping the flush — they stay in
        the Live area so their spinner keeps animating.  Subsequent finished
        blocks can still flush past them because background agents are async.
        """
        tool_call_ids = list(self._tool_call_blocks.keys())
        for tool_call_id in tool_call_ids:
            block = self._tool_call_blocks[tool_call_id]
            if block.is_background_pending:
                continue  # stays in Live area; animated each refresh tick
            if not block.finished:
                break

            self._tool_call_blocks.pop(tool_call_id)
            console.print()
            console.print(block.compose())
            if self._last_tool_call_block == block:
                self._last_tool_call_block = None
            self.refresh_soon()

    def flush_notifications(self) -> None:
        """Flush rendered notifications to terminal history."""
        self._live_notification_blocks.clear()
        while self._notification_blocks:
            console.print()
            console.print(self._notification_blocks.popleft().compose())
            self.refresh_soon()

    def append_content(self, part: ContentPart) -> None:
        match part:
            case ThinkPart(think=text) | TextPart(text=text):
                is_think = isinstance(part, ThinkPart)
                # Skip empty TextPart, but still create the block for empty
                # ThinkPart so the "Thinking" indicator shows immediately
                # (e.g. Anthropic/OpenAI block-start events yield think="").
                if not text and not is_think:
                    return
                self._current_step_retry = None
                if self._current_content_block is None:
                    self._current_content_block = _ContentBlock(
                        is_think, show_thinking_stream=self._show_thinking_stream
                    )
                    self.refresh_soon()
                elif self._current_content_block.is_think != is_think:
                    self.flush_content()
                    self._current_content_block = _ContentBlock(
                        is_think, show_thinking_stream=self._show_thinking_stream
                    )
                    self.refresh_soon()
                if text:
                    self._current_content_block.append(text)
                    self.refresh_soon()
            case _:
                # TODO: support more content part types
                pass

    def append_tool_call(self, tool_call: ToolCall) -> None:
        self._current_step_retry = None
        self.flush_content()
        self._tool_call_blocks[tool_call.id] = _ToolCallBlock(tool_call)
        self._last_tool_call_block = self._tool_call_blocks[tool_call.id]
        self.refresh_soon()

    def append_tool_call_part(self, part: ToolCallPart) -> None:
        if not part.arguments_part:
            return
        if self._last_tool_call_block is None:
            return
        self._last_tool_call_block.append_args_part(part.arguments_part)
        self.refresh_soon()

    def append_tool_result(self, result: ToolResult) -> None:
        if block := self._tool_call_blocks.get(result.tool_call_id):
            self._record_todo_display(result.return_value)
            if block.is_todo_list and not result.return_value.is_error:
                # Successful todo updates are represented only by the pinned
                # todo summary under the verb spinner.
                self._tool_call_blocks.pop(result.tool_call_id, None)
                if self._last_tool_call_block == block:
                    self._last_tool_call_block = None
                self.refresh_soon()
                return
            block.finish(result.return_value)
            self.flush_finished_tool_calls()
            self.refresh_soon()

    def _record_todo_display(self, result: ToolReturnValue) -> None:
        """Remember the latest todo display block for the pinned status tail."""
        for block in getattr(result, "display", []) or []:
            if isinstance(block, TodoDisplayBlock):
                self._latest_todos = tuple(block.items)
                return

    def append_notification(self, notification: Notification) -> None:
        block = _NotificationBlock(notification)
        self._notification_blocks.append(block)
        self._live_notification_blocks.append(block)
        self.refresh_soon()

    def request_approval(self, request: ApprovalRequest) -> None:
        self._approval_request_queue.append(request)

        if self._current_approval_request_panel is None:
            console.bell()
            self.show_next_approval_request()

    def _reconcile_approval_requests(self) -> None:
        self._approval_request_queue = deque(
            request for request in self._approval_request_queue if not request.resolved
        )
        if (
            self._current_approval_request_panel is not None
            and self._current_approval_request_panel.request.resolved
        ):
            self._current_approval_request_panel = None
            self.show_next_approval_request()
        else:
            self.refresh_soon()

    def show_next_approval_request(self) -> None:
        """
        Show the next approval request from the queue.
        If there are no pending requests, clear the current approval panel.
        """
        if not self._approval_request_queue:
            if self._current_approval_request_panel is not None:
                self._current_approval_request_panel = None
                self.refresh_soon()
            return

        while self._approval_request_queue:
            request = self._approval_request_queue.popleft()
            if request.resolved:
                # skip resolved requests
                continue
            self._current_approval_request_panel = ApprovalRequestPanel(request)
            self.refresh_soon()
            break
        else:
            # All queued requests were already resolved
            if self._current_approval_request_panel is not None:
                self._current_approval_request_panel = None
                self.refresh_soon()

    def display_plan(self, msg: PlanDisplay) -> None:
        """Render plan content inline in the chat with a bordered panel."""
        self.flush_content()
        self.flush_finished_tool_calls()
        plan_body = Markdown(msg.content)
        panel = render_worklog_card(
            "Plan",
            plan_body,
            subtitle=msg.file_path,
            border_style=tui_rich_style("border"),
        )
        console.print(panel)

    def request_question(self, request: QuestionRequest) -> None:
        self._question_request_queue.append(request)
        if self._current_question_panel is None:
            console.bell()
            self.show_next_question_request()

    def show_next_question_request(self) -> None:
        """Show the next question request from the queue."""
        if not self._question_request_queue:
            if self._current_question_panel is not None:
                self._current_question_panel = None
                self.refresh_soon()
                self._on_question_panel_state_changed()
            return

        while self._question_request_queue:
            request = self._question_request_queue.popleft()
            if request.resolved:
                continue
            self._current_question_panel = QuestionRequestPanel(request)
            self.refresh_soon()
            self._on_question_panel_state_changed()
            break
        else:
            # All queued requests were already resolved
            if self._current_question_panel is not None:
                self._current_question_panel = None
                self.refresh_soon()
                self._on_question_panel_state_changed()

    def handle_subagent_event(self, event: SubagentEvent) -> None:
        if event.parent_tool_call_id is None:
            return
        block = self._tool_call_blocks.get(event.parent_tool_call_id)
        if block is None:
            return
        if event.agent_id is not None and event.subagent_type is not None:
            block.set_subagent_metadata(event.agent_id, event.subagent_type)

        match event.event:
            case ToolCall() as tool_call:
                block.append_sub_tool_call(tool_call)
            case ToolCallPart() as tool_call_part:
                block.append_sub_tool_call_part(tool_call_part)
            case ToolResult() as tool_result:
                block.finish_sub_tool_call(tool_result)
                self.refresh_soon()
            case _:
                # ignore other events for now
                # TODO: may need to handle multi-level nested subagents
                pass
