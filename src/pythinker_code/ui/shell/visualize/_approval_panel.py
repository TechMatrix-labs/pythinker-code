from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from prompt_toolkit.application.run_in_terminal import run_in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyPressEvent
from rich.console import Group, RenderableType
from rich.markup import escape
from rich.padding import Padding
from rich.style import Style as RichStyle
from rich.text import Text

from pythinker_code.ui.shell.components.render_utils import sanitize_ansi
from pythinker_code.ui.shell.console import console, render_to_ansi
from pythinker_code.ui.shell.keyboard import KeyEvent
from pythinker_code.ui.shell.keymap import key_text
from pythinker_code.ui.shell.spacing import blank_row
from pythinker_code.ui.shell.visualize._dialog_shell import DialogOption, render_dialog
from pythinker_code.ui.theme import get_tui_tokens as _get_tui_tokens
from pythinker_code.ui.theme import tui_rich_style
from pythinker_code.utils.rich.diff_render import (
    collect_diff_hunks,
    render_diff_panel,
    render_diff_preview,
    render_diff_summary_panel,
    render_diff_summary_preview,
)
from pythinker_code.utils.rich.syntax import PythinkerSyntax
from pythinker_code.wire.types import (
    ApprovalRequest,
    ApprovalResponse,
    BriefDisplayBlock,
    DiffDisplayBlock,
    ShellDisplayBlock,
)

# Truncation limits for approval request display
MAX_PREVIEW_LINES = 4
_APPROVAL_CHROME_WIDTH = 8


def _truncate_text_renderable(renderable: RenderableType, width: int) -> RenderableType:
    """Keep preview rows inside the prompt width.

    Rich usually wraps prose, but diff preview rows contain line numbers, paths,
    and code tokens where wrapping produces noisy overflow in the bottom TUI
    modal. Truncating these compact preview rows keeps the approval panel stable;
    the registered expand shortcut still opens the full pager.
    """
    if width <= 0 or not isinstance(renderable, Text):
        return renderable
    text = renderable.copy()
    text.truncate(max(1, width), overflow="ellipsis")
    return text


class ApprovalContentBlock(NamedTuple):
    """A pre-rendered content block for approval request with line count."""

    text: str
    lines: int
    style: str | RichStyle = ""
    lexer: str = ""


def _safe_display_text(text: str) -> str:
    """Strip terminal control sequences before rendering untrusted approval text."""
    return sanitize_ansi(text).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _safe_markup_text(text: str) -> str:
    return escape(_safe_display_text(text))


def _render_feedback_with_cursor(text: str, cursor: int | None) -> Text:
    safe_text = sanitize_ansi(text)
    if safe_text != text:
        cursor = None
    if cursor is None or cursor >= len(safe_text):
        return Text(safe_text + "\u2588")
    cursor = max(cursor, 0)
    return Text.assemble(
        Text(safe_text[:cursor]),
        Text(safe_text[cursor], style="reverse"),
        Text(safe_text[cursor + 1 :]),
    )


class ApprovalRequestPanel:
    FEEDBACK_OPTION_INDEX = 3

    def __init__(self, request: ApprovalRequest):
        self.request = request
        self.options: list[tuple[str, ApprovalResponse.Kind]] = [
            ("Approve once", "approve"),
            ("Approve for this session", "approve_for_session"),
            ("Reject", "reject"),
            ("Reject, tell the model what to do instead", "reject"),
        ]
        self.selected_index = 0

        # Pre-render content for the preview.
        # All blocks (diff and non-diff) are rendered in original display order
        # into a single list of renderables to preserve interleaving.
        self._preview_renderables: list[RenderableType] = []
        self._has_diff = False
        self._non_diff_truncated = False
        # Legacy content blocks for non-diff blocks (used by render_full fallback)
        self._content_blocks: list[ApprovalContentBlock] = []

        # Line budget for non-diff blocks
        non_diff_budget = MAX_PREVIEW_LINES

        # Handle description (only if no display blocks)
        if request.description and not request.display:
            text = _safe_display_text(request.description)
            line_count = text.count("\n") + 1
            self._content_blocks.append(ApprovalContentBlock(text=text, lines=line_count))
            preview_text = text
            if line_count > non_diff_budget:
                preview_text = "\n".join(text.split("\n")[:non_diff_budget])
                self._non_diff_truncated = True
            self._preview_renderables.append(Text(preview_text))
            non_diff_budget -= min(line_count, non_diff_budget)

        # Handle display blocks — group consecutive same-file DiffDisplayBlocks
        display = request.display
        idx = 0
        while idx < len(display):
            block = display[idx]
            if isinstance(block, DiffDisplayBlock):
                path = block.path
                diff_blocks: list[DiffDisplayBlock] = []
                while idx < len(display):
                    b = display[idx]
                    if not isinstance(b, DiffDisplayBlock) or b.path != path:
                        break
                    diff_blocks.append(b)
                    idx += 1
                if any(b.is_summary for b in diff_blocks):
                    self._has_diff = True
                    self._preview_renderables.extend(render_diff_summary_preview(path, diff_blocks))
                else:
                    hunks, added, removed = collect_diff_hunks(diff_blocks)
                    if hunks:
                        self._has_diff = True
                        renderables, _remaining = render_diff_preview(
                            path,
                            hunks,
                            added,
                            removed,
                        )
                        self._preview_renderables.extend(renderables)
            elif isinstance(block, ShellDisplayBlock):
                text = _safe_display_text(block.command)
                line_count = text.count("\n") + 1
                self._content_blocks.append(
                    ApprovalContentBlock(text=text, lines=line_count, lexer=block.language)
                )
                if non_diff_budget > 0:
                    truncated = text
                    if line_count > non_diff_budget:
                        truncated = "\n".join(text.split("\n")[:non_diff_budget])
                        self._non_diff_truncated = True
                    self._preview_renderables.append(PythinkerSyntax(truncated, block.language))
                    non_diff_budget -= min(line_count, non_diff_budget)
                else:
                    self._non_diff_truncated = True
                idx += 1
            elif isinstance(block, BriefDisplayBlock) and block.text:
                text = _safe_display_text(block.text)
                line_count = text.count("\n") + 1
                self._content_blocks.append(
                    ApprovalContentBlock(text=text, lines=line_count, style=tui_rich_style("muted"))
                )
                if non_diff_budget > 0:
                    truncated = text
                    if line_count > non_diff_budget:
                        truncated = "\n".join(text.split("\n")[:non_diff_budget])
                        self._non_diff_truncated = True
                    self._preview_renderables.append(Text(truncated, style=tui_rich_style("muted")))
                    non_diff_budget -= min(line_count, non_diff_budget)
                else:
                    self._non_diff_truncated = True
                idx += 1
            else:
                idx += 1

        # P1: diff pager always has context lines not shown in preview
        # P2: non-diff blocks may have been truncated
        self.has_expandable_content = self._has_diff or self._non_diff_truncated

    def render(
        self,
        *,
        feedback_text: str | None = None,
        feedback_cursor: int | None = None,
        width: int | None = None,
    ) -> RenderableType:
        """Render the approval menu as a bordered panel."""
        _t = _get_tui_tokens()
        content_lines: list[RenderableType] = [
            Text.from_markup(
                f"[{_t.warning}]"
                f"{_safe_markup_text(self.request.sender)} is requesting approval to "
                f"{_safe_markup_text(self.request.action)}:[/]"
            )
        ]
        content_lines.extend(self._render_source_metadata_lines())
        content_lines.append(blank_row())

        panel_width = width or console.size.width
        preview_width = max(1, panel_width - _APPROVAL_CHROME_WIDTH)

        # Render preview (diff + non-diff in original display order)
        content_lines.extend(
            _truncate_text_renderable(renderable, preview_width)
            for renderable in self._preview_renderables
        )

        expand_key = key_text("app.tools.expand") or "ctrl+o"
        if self.has_expandable_content and self._non_diff_truncated:
            content_lines.append(
                Text(f"... (truncated, {expand_key} to expand)", style="dim italic")
            )

        lines: list[RenderableType] = []
        if content_lines:
            lines.append(Padding(Group(*content_lines), (0, 0, 0, 1)))

        # Whether inline feedback input is active
        show_inline_feedback = feedback_text is not None and self.is_feedback_selected

        if show_inline_feedback:
            if lines:
                lines.append(blank_row())
            for i, (option_text, _) in enumerate(self.options):
                num = i + 1
                is_feedback_option = i == self.FEEDBACK_OPTION_INDEX
                if i == self.selected_index and is_feedback_option:
                    input_display = _render_feedback_with_cursor(
                        feedback_text or "", feedback_cursor
                    )
                    lines.append(
                        Text.assemble(
                            Text(f"\u2192 [{num}] Reject: "),
                            input_display,
                            style=tui_rich_style("accent"),
                        )
                    )
                elif i == self.selected_index:
                    lines.append(
                        Text(f"\u2192 [{num}] {option_text}", style=tui_rich_style("accent"))
                    )
                else:
                    lines.append(Text(f"  [{num}] {option_text}", style=tui_rich_style("muted")))
            dialog_options: list[DialogOption] = []
            footer = Text(
                "Type your feedback, then press Enter to reject; Esc rejects without feedback.",
                style="dim",
            )
        else:
            dialog_options = [
                DialogOption(
                    label=option_text,
                    selected=i == self.selected_index,
                    key=str(i + 1),
                )
                for i, (option_text, _) in enumerate(self.options)
            ]
            footer_parts = ["\u2191/\u2193 select", "\u21b5 submit", "esc reject"]
            if self.has_expandable_content:
                footer_parts.append(f"{expand_key} expand")
            footer = Text("  ".join(footer_parts), style="dim")

        return render_dialog(
            kind="approval",
            title=f"{_safe_markup_text(self.request.sender)} approval",
            body=lines,
            options=dialog_options,
            footer=footer,
            border_style=tui_rich_style("warning"),
            width=width,
        )

    def _render_block(
        self, block: ApprovalContentBlock, max_lines: int | None = None
    ) -> RenderableType:
        """Render a content block, optionally truncated."""
        text = block.text
        if max_lines is not None and block.lines > max_lines:
            text = "\n".join(text.split("\n")[:max_lines])

        if block.lexer:
            return PythinkerSyntax(text, block.lexer)
        return Text(text, style=block.style)

    def render_full(self) -> list[RenderableType]:
        """Render full content for pager (no truncation)."""
        return [self._render_block(block) for block in self._content_blocks]

    def _render_source_metadata_lines(self) -> list[RenderableType]:
        lines: list[RenderableType] = []
        if self.request.subagent_type is not None or self.request.agent_id is not None:
            if self.request.subagent_type is not None and self.request.agent_id is not None:
                subagent_text = f"{self.request.subagent_type} ({self.request.agent_id})"
            elif self.request.subagent_type is not None:
                subagent_text = self.request.subagent_type
            else:
                assert self.request.agent_id is not None
                subagent_text = self.request.agent_id
            lines.append(
                Text(
                    f"Subagent: {_safe_display_text(subagent_text)}", style=tui_rich_style("muted")
                )
            )
        if self.request.source_description:
            lines.append(
                Text(
                    f"Task: {_safe_display_text(self.request.source_description)}",
                    style=tui_rich_style("muted"),
                )
            )
        return lines

    def move_up(self):
        """Move selection up."""
        self.selected_index = (self.selected_index - 1) % len(self.options)

    def move_down(self):
        """Move selection down."""
        self.selected_index = (self.selected_index + 1) % len(self.options)

    @property
    def is_feedback_selected(self) -> bool:
        return self.selected_index == self.FEEDBACK_OPTION_INDEX

    def get_selected_response(self) -> ApprovalResponse.Kind:
        """Get the approval response based on selected option."""
        return self.options[self.selected_index][1]


def show_approval_in_pager(panel: ApprovalRequestPanel) -> None:
    """Show the full approval request content in a pager."""
    with console.screen(), console.pager(styles=True):
        from pythinker_code.ui.theme import get_tui_tokens

        _tokens = get_tui_tokens()
        console.print(
            Text.from_markup(
                f"[{_tokens.warning}]⚠ "
                f"{_safe_markup_text(panel.request.sender)} is requesting approval to "
                f"{_safe_markup_text(panel.request.action)}:[/]"
            )
        )
        console.print()

        # Render display blocks with the unified diff renderer.
        display = panel.request.display
        rendered_any = False
        idx = 0
        while idx < len(display):
            block = display[idx]
            if isinstance(block, DiffDisplayBlock):
                path = block.path
                diff_blocks: list[DiffDisplayBlock] = []
                while idx < len(display):
                    b = display[idx]
                    if not isinstance(b, DiffDisplayBlock) or b.path != path:
                        break
                    diff_blocks.append(b)
                    idx += 1
                if any(b.is_summary for b in diff_blocks):
                    console.print(render_diff_summary_panel(path, diff_blocks))
                    rendered_any = True
                else:
                    hunks, added, removed = collect_diff_hunks(diff_blocks)
                    if hunks:
                        console.print(render_diff_panel(path, hunks, added, removed))
                        rendered_any = True
            elif isinstance(block, ShellDisplayBlock):
                console.print(PythinkerSyntax(_safe_display_text(block.command), block.language))
                rendered_any = True
                idx += 1
            elif isinstance(block, BriefDisplayBlock) and block.text:
                console.print(Text(_safe_display_text(block.text), style=tui_rich_style("muted")))
                rendered_any = True
                idx += 1
            else:
                idx += 1

        # Fallback: if nothing was rendered (e.g. type mismatch after deserialization),
        # use legacy pre-rendered content blocks.
        if not rendered_any:
            for renderable in panel.render_full():
                console.print(renderable)


class ApprovalPromptDelegate:
    modal_priority = 20
    _KEY_MAP: dict[str, KeyEvent] = {
        "up": KeyEvent.UP,
        "down": KeyEvent.DOWN,
        "enter": KeyEvent.ENTER,
        "1": KeyEvent.NUM_1,
        "2": KeyEvent.NUM_2,
        "3": KeyEvent.NUM_3,
        "4": KeyEvent.NUM_4,
        "escape": KeyEvent.ESCAPE,
        "c-c": KeyEvent.ESCAPE,
        "c-d": KeyEvent.ESCAPE,
    }

    def __init__(
        self,
        request: ApprovalRequest,
        *,
        on_response: Callable[[ApprovalRequest, ApprovalResponse.Kind, str], None],
        buffer_state_provider: Callable[[], tuple[str, int]] | None = None,
        text_expander: Callable[[str], str] | None = None,
    ) -> None:
        self._panel = ApprovalRequestPanel(request)
        self._on_response = on_response
        self._buffer_state_provider = buffer_state_provider
        self._text_expander = text_expander
        self._feedback_draft: str = ""

    @property
    def request(self) -> ApprovalRequest:
        return self._panel.request

    def set_request(self, request: ApprovalRequest) -> None:
        self._panel = ApprovalRequestPanel(request)
        self._feedback_draft = ""

    def _is_inline_feedback_active(self) -> bool:
        return self._panel.is_feedback_selected and self._buffer_state_provider is not None

    def render_running_prompt_body(self, columns: int) -> ANSI:
        feedback_text: str | None = None
        feedback_cursor: int | None = None
        if self._is_inline_feedback_active() and self._buffer_state_provider is not None:
            feedback_text, feedback_cursor = self._buffer_state_provider()
        body = render_to_ansi(
            self._panel.render(
                feedback_text=feedback_text,
                feedback_cursor=feedback_cursor,
                width=columns,
            ),
            columns=columns,
        ).rstrip("\n")
        return ANSI(body)

    def running_prompt_placeholder(self) -> str | None:
        return None

    def running_prompt_allows_text_input(self) -> bool:
        return self._is_inline_feedback_active()

    def running_prompt_hides_input_buffer(self) -> bool:
        return True

    def running_prompt_accepts_submission(self) -> bool:
        return False

    def should_handle_running_prompt_key(self, key: str) -> bool:
        if key in {"c-o", "c-e"}:
            return self._panel.has_expandable_content
        if self._is_inline_feedback_active():
            return key in {"enter", "escape", "c-c", "c-d", "up", "down"}
        return key in {
            "up",
            "down",
            "enter",
            "1",
            "2",
            "3",
            "4",
            "escape",
            "c-c",
            "c-d",
            "c-e",
        }

    def handle_running_prompt_key(self, key: str, event: KeyPressEvent) -> None:
        if key in {"c-o", "c-e"}:
            event.app.create_background_task(self._show_panel_in_pager())
            return

        # Inline feedback mode: user is typing in the "Reject + feedback" field
        if self._is_inline_feedback_active():
            mapped = self._KEY_MAP.get(key)
            if key == "enter" or mapped == KeyEvent.ENTER:
                text = event.current_buffer.text.strip()
                if text:
                    if self._text_expander is not None:
                        text = self._text_expander(text)
                    self._clear_buffer(event.current_buffer)
                    self._feedback_draft = ""
                    self._panel.request.resolve("reject")
                    self._on_response(self._panel.request, "reject", text)
                # Empty enter: do nothing (keep editing)
                return
            if mapped == KeyEvent.ESCAPE:
                self._clear_buffer(event.current_buffer)
                self._feedback_draft = ""
                self._panel.request.resolve("reject")
                self._on_response(self._panel.request, "reject", "")
                return
            if mapped in {KeyEvent.UP, KeyEvent.DOWN}:
                self._feedback_draft = event.current_buffer.text
                self._clear_buffer(event.current_buffer)
                if mapped == KeyEvent.UP:
                    self._panel.move_up()
                else:
                    self._panel.move_down()
                return
            return

        mapped = self._KEY_MAP.get(key)
        if mapped is None:
            return
        match mapped:
            case KeyEvent.UP:
                self._panel.move_up()
                self._maybe_restore_feedback_draft(event.current_buffer)
            case KeyEvent.DOWN:
                self._panel.move_down()
                self._maybe_restore_feedback_draft(event.current_buffer)
            case KeyEvent.ENTER:
                self._submit_current_request(event.current_buffer)
            case KeyEvent.ESCAPE:
                self._panel.request.resolve("reject")
                self._on_response(self._panel.request, "reject", "")
            case KeyEvent.NUM_1 | KeyEvent.NUM_2 | KeyEvent.NUM_3 | KeyEvent.NUM_4:
                num_map = {
                    KeyEvent.NUM_1: 0,
                    KeyEvent.NUM_2: 1,
                    KeyEvent.NUM_3: 2,
                    KeyEvent.NUM_4: 3,
                }
                idx = num_map[mapped]
                if idx < len(self._panel.options):
                    self._panel.selected_index = idx
                    if not self._is_inline_feedback_active():
                        self._submit_current_request(event.current_buffer)
            case _:
                pass

    async def _show_panel_in_pager(self) -> None:
        await run_in_terminal(lambda: show_approval_in_pager(self._panel))

    def _maybe_restore_feedback_draft(self, buffer: Buffer) -> None:
        if self._is_inline_feedback_active() and self._feedback_draft:
            buffer.set_document(
                Document(text=self._feedback_draft, cursor_position=len(self._feedback_draft)),
                bypass_readonly=True,
            )

    @staticmethod
    def _clear_buffer(buffer: Buffer) -> None:
        if buffer.text:
            buffer.set_document(Document(text="", cursor_position=0), bypass_readonly=True)

    def _submit_current_request(self, buffer: Buffer) -> None:
        self._clear_buffer(buffer)
        self._feedback_draft = ""
        response = self._panel.get_selected_response()
        self._panel.request.resolve(response)
        self._on_response(self._panel.request, response, "")
