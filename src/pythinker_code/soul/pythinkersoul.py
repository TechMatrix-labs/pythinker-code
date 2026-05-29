from __future__ import annotations

import asyncio
import contextlib
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import pythinker_core
import tenacity
from pythinker_core import StepResult
from pythinker_core.chat_provider import (
    APIConnectionError,
    APIEmptyResponseError,
    APIStatusError,
    APITimeoutError,
    RetryableChatProvider,
)
from pythinker_core.message import Message, ToolCall
from tenacity import RetryCallState, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from pythinker_code.approval_runtime import (
    ApprovalSource,
    get_current_approval_source_or_none,
    reset_current_approval_source,
    set_current_approval_source,
)
from pythinker_code.background import build_active_task_snapshot
from pythinker_code.hooks.engine import HookEngine
from pythinker_code.llm import ModelCapability
from pythinker_code.notifications import (
    NotificationView,
    build_notification_message,
    extract_notification_ids,
)
from pythinker_code.prompt_templates import PromptTemplate, expand_prompt_template
from pythinker_code.skill import Skill, read_skill_text_with_local_specialization
from pythinker_code.skill.flow import Flow, FlowEdge, FlowNode, parse_choice
from pythinker_code.soul import (
    LLMNotSet,
    LLMNotSupported,
    MaxStepsReached,
    Soul,
    StatusSnapshot,
    wire_send,
)
from pythinker_code.soul.agent import Agent, Runtime
from pythinker_code.soul.compaction import (
    CompactionResult,
    SimpleCompaction,
    estimate_text_tokens,
    should_auto_compact,
)
from pythinker_code.soul.compaction_restore import (
    build_compaction_restore_context,
    build_hook_context_message,
    compact_summary_text,
)
from pythinker_code.soul.context import Context
from pythinker_code.soul.dynamic_injection import (
    DynamicInjection,
    DynamicInjectionProvider,
    collect_within_budget,
    dynamic_to_candidate,
    injection_budget_from_runtime,
    normalize_history,
)
from pythinker_code.soul.dynamic_injections.auto_mode import AutoModeInjectionProvider
from pythinker_code.soul.dynamic_injections.plan_mode import PlanModeInjectionProvider
from pythinker_code.soul.message import (
    check_message,
    system,
    system_reminder,
    tool_result_to_message,
)
from pythinker_code.soul.permission import (
    permission_profile_for_runtime,
    reset_step_permission_profile,
    set_step_permission_profile,
)
from pythinker_code.soul.slash import registry as soul_slash_registry
from pythinker_code.soul.toolset import PythinkerToolset
from pythinker_code.tools.dmail import NAME as SendDMail_NAME
from pythinker_code.tools.utils import ToolRejectedError
from pythinker_code.utils.logging import logger
from pythinker_code.utils.slashcmd import SlashCommand, parse_slash_command_call
from pythinker_code.utils.sleep_inhibitor import SleepInhibitor
from pythinker_code.wire.file import WireFile
from pythinker_code.wire.types import (
    CompactionBegin,
    CompactionEnd,
    ContentPart,
    MCPLoadingBegin,
    MCPLoadingEnd,
    StatusUpdate,
    SteerInput,
    StepBegin,
    StepInterrupted,
    StepRetry,
    TextPart,
    ToolResult,
    TurnBegin,
    TurnEnd,
)

if TYPE_CHECKING:

    def type_check(soul: PythinkerSoul):
        _: Soul = soul


SKILL_COMMAND_PREFIX = "skill:"
FLOW_COMMAND_PREFIX = "flow:"
DEFAULT_MAX_FLOW_MOVES = 1000


def classify_llm_system(chat_provider: object | None) -> str:
    """Classify a chat provider into a stable gen_ai.system telemetry value."""
    try:
        provider_class = type(chat_provider).__name__.lower() if chat_provider is not None else ""
        if "anthropic" in provider_class:
            return "anthropic"
        if "openai" in provider_class:
            return "openai"
        if "google" in provider_class or "gemini" in provider_class:
            return "google"
        return provider_class or "unknown"
    except Exception:
        return "unknown"


def classify_api_error(e: Exception) -> tuple[str, int | None]:
    """Classify an LLM API exception into (error_type, status_code).

    Exposed at module level so telemetry tests can import the real function
    instead of duplicating the classification table.

    Returns:
        (error_type, status_code) where status_code is None for non-HTTP errors.
    """
    status_code: int | None = None
    if isinstance(e, APIStatusError):
        status = getattr(e, "status_code", getattr(e, "status", 0))
        status_code = int(status) if status else None
        if status == 429:
            return "rate_limit", status_code
        if status in (401, 403):
            return "auth", status_code
        if status >= 500:
            return "5xx_server", status_code
        if 400 <= status < 500:
            msg_lower = str(e).lower()
            if (
                "context length" in msg_lower
                or "context_length" in msg_lower
                or "max tokens" in msg_lower
                or "maximum context" in msg_lower
                or "too many tokens" in msg_lower
            ):
                return "context_overflow", status_code
            return "4xx_client", status_code
        return "api", status_code
    if isinstance(e, APIConnectionError):
        return "network", None
    if isinstance(e, (APITimeoutError, TimeoutError)):
        return "timeout", None
    if isinstance(e, APIEmptyResponseError):
        return "empty_response", None
    return "other", None


type StepStopReason = Literal["no_tool_calls", "tool_rejected"]


_MISSING_REQUIRED_FIELD_RE = re.compile(
    r"^\s*(?P<field>[A-Za-z_][A-Za-z0-9_\-.]*)\s*\n\s+Field required",
    re.MULTILINE,
)


def _missing_required_fields_from_validation_error(message: str) -> list[str]:
    """Extract field names from Pydantic's missing-field validation text."""
    if "Error validating JSON arguments:" not in message:
        return []
    return [match.group("field") for match in _MISSING_REQUIRED_FIELD_RE.finditer(message)]


def _is_empty_tool_arguments(tool_call: ToolCall) -> bool:
    raw = tool_call.function.arguments
    return raw is None or raw.strip() in {"", "{}"}


def _malformed_empty_tool_call_summary(
    tool_calls: Sequence[ToolCall], tool_results: Sequence[ToolResult]
) -> str | None:
    """Return a concise summary when a step only produced empty invalid tool calls.

    Some models can get stuck emitting `{}`/empty arguments for tools with required
    fields. Continuing the agent loop just floods the UI with repeated validation
    cards. Detect that dead-end shape and stop after the first invalid batch.
    """
    if not tool_calls or len(tool_calls) != len(tool_results):
        return None

    calls_by_id = {call.id: call for call in tool_calls}
    missing_by_tool: list[str] = []
    for result in tool_results:
        call = calls_by_id.get(result.tool_call_id)
        if call is None or not _is_empty_tool_arguments(call):
            return None
        if not result.return_value.is_error:
            return None
        fields = _missing_required_fields_from_validation_error(result.return_value.message)
        if not fields:
            return None
        missing_by_tool.append(f"{call.function.name}.{', '.join(fields)}")

    if not missing_by_tool:
        return None
    return "; ".join(missing_by_tool)


_UNFINISHED_INTENT_LEAD_RE = re.compile(
    r"^(let me|let's|let us|now let me|now i'?ll|i'?ll|i will|i'?m going to|"
    r"i am going to|first,?\s+i'?ll|next,?\s+i'?ll)\b",
    re.IGNORECASE,
)
_UNFINISHED_INTENT_ACTION_RE = re.compile(
    r"\b(synthesi|summari|writ|creat|compil|prepar|draft|put together|generat|"
    r"produc|present|report|provid|run|check|cross-check|verif|read|search|"
    r"analy|review|implement|fix|updat|build|gather|look|examin|continu|"
    r"proceed|start|begin|assembl|consolidat|finaliz|outlin|map out|"
    r"investigat|explor|dig into|pull together)\w*",
    re.IGNORECASE,
)


def _looks_like_unfinished_intent(text: str) -> bool:
    """Return True when *text* is essentially a statement of intent to act, with
    no actual result delivered.

    Models sometimes end a message with a transitional preamble such as
    "Let me synthesize the findings into a unified report." but attach no tool
    call and produce no result. The agent loop treats any tool-call-free message
    as the final answer, so the turn ends before the promised work is done. This
    detects that shape (conservatively) so the loop can nudge one more step.
    """
    text = text.strip()
    if not text or len(text) > 400 or text.endswith("?"):
        return False
    sentences = [s.strip() for s in re.split(r"[.!\n]+", text) if s.strip()]
    if not sentences:
        return False
    last = sentences[-1]
    if "let me know" in last.lower():
        return False
    return bool(
        _UNFINISHED_INTENT_LEAD_RE.match(last) and _UNFINISHED_INTENT_ACTION_RE.search(last)
    )


@dataclass(frozen=True, slots=True)
class StepOutcome:
    stop_reason: StepStopReason
    assistant_message: Message


type TurnStopReason = StepStopReason


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    stop_reason: TurnStopReason
    final_message: Message | None
    step_count: int


class PythinkerSoul:
    """The soul of Pythinker CLI."""

    def __init__(
        self,
        agent: Agent,
        *,
        context: Context,
    ):
        """
        Initialize the soul.

        Args:
            agent (Agent): The agent to run.
            context (Context): The context of the agent.
        """
        self._agent = agent
        self._runtime = agent.runtime
        self._denwa_renji = agent.runtime.denwa_renji
        self._approval = agent.runtime.approval
        self._context = context
        self._loop_control = agent.runtime.config.loop_control
        self._sleep_inhibitor = SleepInhibitor(enabled=agent.runtime.config.prevent_idle_sleep)
        self._compaction = SimpleCompaction()  # TODO: maybe configurable and composable

        for tool in agent.toolset.tools:
            if tool.name == SendDMail_NAME:
                self._checkpoint_with_user_message = True
                break
        else:
            self._checkpoint_with_user_message = False

        self._steer_queue: asyncio.Queue[str | list[ContentPart]] = asyncio.Queue()
        self._prompt_queue_lock = asyncio.Lock()
        self._plan_mode: bool = self._runtime.session.state.plan_mode
        self._plan_session_id: str | None = self._runtime.session.state.plan_session_id
        # Pre-warm slug cache so the persisted slug survives process restarts
        if self._plan_session_id is not None and self._runtime.session.state.plan_slug is not None:
            from pythinker_code.tools.plan.heroes import seed_slug_cache

            seed_slug_cache(self._plan_session_id, self._runtime.session.state.plan_slug)
        self._pending_plan_activation_injection: bool = False
        if self._plan_mode:
            self._ensure_plan_session_id()
        self._injection_providers: list[DynamicInjectionProvider] = [
            PlanModeInjectionProvider(),
            *(
                []
                if self._runtime.config.skip_auto_prompt_injection
                else [AutoModeInjectionProvider()]
            ),
        ]
        self._hook_engine: HookEngine = HookEngine()
        self._stop_hook_active: bool = False
        if self._runtime.role == "root":
            self._runtime.notifications.ack_ids("llm", extract_notification_ids(context.history))

        # Bind plan mode state to tools that support it
        self._bind_plan_mode_tools()

        self._runtime.rearm_injection = self.rearm_injection

        self._slash_commands = self._build_slash_commands()
        self._slash_command_map = self._index_slash_commands(self._slash_commands)

    @property
    def name(self) -> str:
        return self._agent.name

    @property
    def model_name(self) -> str:
        return self._runtime.llm.chat_provider.model_name if self._runtime.llm else ""

    @property
    def model_capabilities(self) -> set[ModelCapability] | None:
        if self._runtime.llm is None:
            return None
        return self._runtime.llm.capabilities

    @property
    def is_yolo(self) -> bool:
        """Whether explicit yolo mode is active."""
        return self._approval.is_yolo()

    @property
    def is_auto_approve(self) -> bool:
        """Whether tool approvals are bypassed (explicit yolo, or implied by auto mode)."""
        return self._approval.is_auto_approve()

    @property
    def is_auto(self) -> bool:
        """Whether no user is present (auto mode)."""
        return self._approval.is_auto()

    @property
    def is_auto_flag(self) -> bool:
        """Whether persisted auto mode is active."""
        return self._approval.is_auto_flag()

    @property
    def is_subagent(self) -> bool:
        """Whether this soul is running as a subagent rather than the root session."""
        return self._runtime.role == "subagent"

    @property
    def plan_mode(self) -> bool:
        """Whether plan mode (read-only research and planning) is active."""
        return self._plan_mode

    @property
    def hook_engine(self) -> HookEngine:
        return self._hook_engine

    def set_hook_engine(self, engine: HookEngine) -> None:
        self._hook_engine = engine
        if isinstance(self._agent.toolset, PythinkerToolset):
            self._agent.toolset.set_hook_engine(engine)

    def add_injection_provider(self, provider: DynamicInjectionProvider) -> None:
        """Register an additional dynamic injection provider."""
        self._injection_providers.append(provider)

    def rearm_injection(self, key: str) -> None:
        """Re-arm matching dynamic injection providers after related state changes."""
        for provider in self._injection_providers:
            try:
                provider.rearm(key)
            except Exception:
                logger.debug("injection provider rearm failed")

    async def _collect_injections(self) -> list[DynamicInjection]:
        """Collect dynamic injections from all registered providers."""
        injections: list[DynamicInjection] = []
        for provider in self._injection_providers:
            try:
                result = await provider.get_injections(self._context.history, self)
                injections.extend(result)
            except Exception as exc:
                from pythinker_code.telemetry.errors import report_handled_error

                report_handled_error(
                    exc,
                    site="soul.injection.get",
                    provider=type(provider).__name__,
                )
                logger.warning(
                    "injection provider %s failed",
                    type(provider).__name__,
                    exc_info=True,
                )
        memory_config = getattr(self._runtime.config, "memory", None)
        if not getattr(memory_config, "injection_bus", True):
            return injections
        candidates = [dynamic_to_candidate(injection) for injection in injections]
        budget = injection_budget_from_runtime(self._runtime).injection_budget_tokens
        budgeted = collect_within_budget(candidates, budget)
        return [
            DynamicInjection(type=candidate.type, content=candidate.content)
            for candidate in budgeted
        ]

    async def _notify_injection_providers_compacted(self) -> None:
        """Notify all injection providers that the context has been compacted.

        Failures are isolated per-provider so a buggy third-party provider
        cannot abort compaction (which would skip CompactionEnd wire events
        and PostCompact telemetry).
        """
        for provider in self._injection_providers:
            try:
                await provider.on_context_compacted()
            except Exception as exc:
                from pythinker_code.telemetry.errors import report_handled_error

                report_handled_error(
                    exc,
                    site="soul.injection.on_context_compacted",
                    provider=type(provider).__name__,
                )
                logger.warning(
                    "injection provider %s on_context_compacted failed",
                    type(provider).__name__,
                    exc_info=True,
                )

    async def notify_auto_changed(self, enabled: bool) -> None:
        """Notify dynamic injection providers that auto mode changed."""
        for provider in self._injection_providers:
            try:
                await provider.on_auto_changed(enabled)
            except Exception as exc:
                from pythinker_code.telemetry.errors import report_handled_error

                report_handled_error(
                    exc,
                    site="soul.injection.on_auto_changed",
                    provider=type(provider).__name__,
                )
                logger.warning(
                    "injection provider %s on_auto_changed failed",
                    type(provider).__name__,
                    exc_info=True,
                )

    def _bind_plan_mode_tools(self) -> None:
        """Bind plan mode state to tools that support it."""
        if not isinstance(self._agent.toolset, PythinkerToolset):
            return

        def checker() -> bool:
            return self._plan_mode

        def path_getter() -> Path | None:
            return self.get_plan_file_path()

        # WriteFile gets both checker and path_getter (for plan file auto-approve)
        from pythinker_code.tools.file.write import WriteFile

        write_tool = self._agent.toolset.find("WriteFile")
        if isinstance(write_tool, WriteFile):
            write_tool.bind_plan_mode(checker, path_getter)

        from pythinker_code.tools.file.replace import StrReplaceFile

        replace_tool = self._agent.toolset.find("StrReplaceFile")
        if isinstance(replace_tool, StrReplaceFile):
            replace_tool.bind_plan_mode(checker, path_getter)

        # ExitPlanMode has a special bind() method
        from pythinker_code.tools.plan import ExitPlanMode

        exit_tool = self._agent.toolset.find("ExitPlanMode")
        if isinstance(exit_tool, ExitPlanMode):
            exit_tool.bind(
                self.toggle_plan_mode,
                path_getter,
                checker,
                self._approval.is_auto,
            )

        # EnterPlanMode has a special bind() method
        from pythinker_code.tools.plan.enter import EnterPlanMode

        enter_tool = self._agent.toolset.find("EnterPlanMode")
        if isinstance(enter_tool, EnterPlanMode):
            enter_tool.bind(
                self.toggle_plan_mode,
                path_getter,
                checker,
                self._approval.is_auto_approve,
            )

        # AskUserQuestion — bind auto-mode checker for auto-dismiss.
        # Yolo alone keeps the tool live; only auto mode (no user present) dismisses.
        from pythinker_code.tools.ask_user import AskUserQuestion

        ask_tool = self._agent.toolset.find("AskUserQuestion")
        if isinstance(ask_tool, AskUserQuestion):
            ask_tool.bind_auto(
                self._approval.is_auto,
                policy=self._runtime.config.ask_user_question_policy,
            )

    def _ensure_plan_session_id(self) -> None:
        """Allocate a stable plan session ID on first activation."""
        if self._plan_session_id is None:
            import uuid

            self._plan_session_id = uuid.uuid4().hex
            self._runtime.session.state.plan_session_id = self._plan_session_id
            # Compute and persist slug immediately so the path survives process restarts
            from pythinker_code.tools.plan.heroes import get_or_create_slug

            slug = get_or_create_slug(self._plan_session_id)
            self._runtime.session.state.plan_slug = slug
            self._runtime.session.save_state()

    def _set_plan_mode(self, enabled: bool, *, source: Literal["manual", "tool"]) -> bool:
        """Update plan mode state for either manual or tool-driven toggles."""
        if enabled == self._plan_mode:
            return self._plan_mode
        self._plan_mode = enabled
        if enabled:
            self._ensure_plan_session_id()
            self._pending_plan_activation_injection = source == "manual"
        else:
            self._pending_plan_activation_injection = False
            self._plan_session_id = None
            self._runtime.session.state.plan_session_id = None
            self._runtime.session.state.plan_slug = None
        # Persist plan mode to session state so it survives process restarts
        self._runtime.session.state.plan_mode = self._plan_mode
        self._runtime.session.save_state()
        return self._plan_mode

    def get_plan_file_path(self) -> Path | None:
        """Get the plan file path for the current session."""
        if self._plan_session_id is None:
            return None
        from pythinker_code.tools.plan.heroes import get_plan_file_path

        return get_plan_file_path(self._plan_session_id)

    def read_current_plan(self) -> str | None:
        """Read the current plan file content."""
        if self._plan_session_id is None:
            return None
        from pythinker_code.tools.plan.heroes import read_plan_file

        return read_plan_file(self._plan_session_id)

    def clear_current_plan(self) -> None:
        """Delete the current plan file."""
        path = self.get_plan_file_path()
        if path and path.exists():
            path.unlink()

    async def toggle_plan_mode(self) -> bool:
        """Toggle plan mode on/off. Returns the new state.

        Tools are not hidden/unhidden — instead, each tool checks plan mode
        state at call time and rejects if blocked.
        Periodic reminders are handled by the dynamic injection system.
        """
        return self._set_plan_mode(not self._plan_mode, source="tool")

    async def toggle_plan_mode_from_manual(self) -> bool:
        """Toggle plan mode from UI/manual entry points (slash command, keybinding)."""
        return self._set_plan_mode(not self._plan_mode, source="manual")

    async def set_plan_mode_from_manual(self, enabled: bool) -> bool:
        """Set plan mode to a specific state from UI/manual entry points.

        Unlike toggle, this accepts the desired state directly, avoiding
        race conditions when the caller already knows the target value.
        """
        return self._set_plan_mode(enabled, source="manual")

    def schedule_plan_activation_reminder(self) -> None:
        """Schedule a plan-mode activation reminder for the next turn.

        Use this when plan mode is already active (e.g. restored session with
        ``--plan`` flag) and ``_set_plan_mode`` would early-return because the
        state hasn't actually changed.
        """
        if self._plan_mode:
            self._pending_plan_activation_injection = True

    def consume_pending_plan_activation_injection(self) -> bool:
        """Consume the next-step activation reminder scheduled by a manual toggle."""
        if not self._plan_mode or not self._pending_plan_activation_injection:
            return False
        self._pending_plan_activation_injection = False
        return True

    @property
    def thinking(self) -> bool | None:
        """Whether thinking mode is enabled."""
        if self._runtime.llm is None:
            return None
        if thinking_effort := self._runtime.llm.chat_provider.thinking_effort:
            return thinking_effort != "off"
        return None

    @property
    def status(self) -> StatusSnapshot:
        token_count = self._context.token_count
        max_size = self._runtime.llm.max_context_size if self._runtime.llm is not None else 0
        return StatusSnapshot(
            context_usage=self._context_usage,
            yolo_enabled=self._approval.is_yolo_flag(),
            auto_enabled=self._approval.is_auto(),
            plan_mode=self._plan_mode,
            context_tokens=token_count,
            max_context_tokens=max_size,
            mcp_status=self._mcp_status_snapshot(),
        )

    @property
    def agent(self) -> Agent:
        return self._agent

    @property
    def runtime(self) -> Runtime:
        return self._runtime

    @property
    def context(self) -> Context:
        return self._context

    @property
    def _context_usage(self) -> float:
        if self._runtime.llm is None or self._runtime.llm.max_context_size <= 0:
            return 0.0
        return self._context.token_count / self._runtime.llm.max_context_size

    @property
    def wire_file(self) -> WireFile:
        return self._runtime.session.wire_file

    def _mcp_status_snapshot(self):
        if not isinstance(self._agent.toolset, PythinkerToolset):
            return None
        return self._agent.toolset.mcp_status_snapshot()

    async def start_background_mcp_loading(self) -> bool:
        """Start deferred MCP loading, if any, without exposing toolset internals."""
        if not isinstance(self._agent.toolset, PythinkerToolset):
            return False
        return await self._agent.toolset.start_deferred_mcp_tool_loading()

    async def wait_for_background_mcp_loading(self) -> None:
        """Wait for any in-flight MCP startup to finish."""
        if not isinstance(self._agent.toolset, PythinkerToolset):
            return
        await self._agent.toolset.wait_for_mcp_tools()

    async def _checkpoint(self):
        await self._context.checkpoint(self._checkpoint_with_user_message)

    def steer(self, content: str | list[ContentPart]) -> None:
        """Queue a steer message for injection into the current turn."""
        self._steer_queue.put_nowait(content)

    async def _consume_pending_steers(self) -> bool:
        """Drain the steer queue and inject as follow-up user messages.

        Returns True if any steers were consumed.

        Note: /btw is intercepted at the UI layer (``classify_input``) before
        reaching the steer queue, so it never appears here.
        """
        consumed = False
        while True:
            try:
                content = self._steer_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self._inject_steer(content)
            wire_send(SteerInput(user_input=content))
            consumed = True
        return consumed

    async def _inject_steer(self, content: str | list[ContentPart]) -> None:
        """Inject a single steer as a regular follow-up user message."""
        parts = cast(
            list[ContentPart],
            [TextPart(text=content)] if isinstance(content, str) else list(content),
        )
        message = Message(role="user", content=parts)
        if self._runtime.llm is None:
            raise LLMNotSet()
        if missing_caps := check_message(message, self._runtime.llm.capabilities):
            raise LLMNotSupported(self._runtime.llm, list(missing_caps))
        await self._context.append_message(message)

    @property
    def available_slash_commands(self) -> list[SlashCommand[Any]]:
        return self._slash_commands

    async def run(
        self,
        user_input: str | list[ContentPart],
        *,
        skip_user_prompt_hook: bool = False,
    ):
        await self._prompt_queue_lock.acquire()
        approval_source_token = None
        created_approval_source: ApprovalSource | None = None
        turn_started = False
        turn_finished = False
        if get_current_approval_source_or_none() is None:
            created_approval_source = ApprovalSource(kind="foreground_turn", id=uuid.uuid4().hex)
            approval_source_token = set_current_approval_source(created_approval_source)
        try:
            # Refresh OAuth tokens on each turn to avoid idle-time expirations.
            await self._runtime.oauth.ensure_fresh(self._runtime)

            # Set session_id ContextVar for toolset hooks
            from pythinker_code.soul.toolset import set_session_id

            set_session_id(self._runtime.session.id)

            from pythinker_code.hooks import events

            # --- UserPromptSubmit hook ---
            # Synthetic internal prompts (e.g. background-task notification
            # follow-ups injected by ``Print`` after a bg task finishes or
            # the wait ceiling is hit) must bypass ``UserPromptSubmit``:
            # they are not user input, and a user-configured prompt-blocking
            # hook would drop the notification and hang the wait loop.
            if not skip_user_prompt_hook:
                text_input_for_hook = user_input if isinstance(user_input, str) else ""

                hook_results = await self._hook_engine.trigger(
                    "UserPromptSubmit",
                    matcher_value=text_input_for_hook,
                    input_data=events.user_prompt_submit(
                        session_id=self._runtime.session.id,
                        cwd=str(Path.cwd()),
                        prompt=text_input_for_hook,
                    ),
                )
                for result in hook_results:
                    if result.action == "block":
                        wire_send(TurnBegin(user_input=user_input))
                        turn_started = True
                        wire_send(TextPart(text=result.reason or "Prompt blocked by hook."))
                        wire_send(TurnEnd())
                        turn_finished = True
                        return

            wire_send(TurnBegin(user_input=user_input))
            turn_started = True
            user_message = Message(role="user", content=user_input)
            text_input = user_message.extract_text(" ").strip()

            if command_call := parse_slash_command_call(text_input):
                command = self._find_slash_command(command_call.name)
                if command is None:
                    # this should not happen actually, the shell should have filtered it out
                    wire_send(TextPart(text=f'Unknown slash command "/{command_call.name}".'))
                else:
                    ret = command.func(self, command_call.args)
                    if isinstance(ret, Awaitable):
                        await ret
            elif self._loop_control.max_ralph_iterations != 0:
                runner = FlowRunner.ralph_loop(
                    user_message,
                    self._loop_control.max_ralph_iterations,
                )
                await runner.run(self, "")
            else:
                await self._turn(user_message)

            # --- Stop hook (max 1 re-trigger to prevent infinite loop) ---
            if not self._stop_hook_active:
                stop_results = await self._hook_engine.trigger(
                    "Stop",
                    input_data=events.stop(
                        session_id=self._runtime.session.id,
                        cwd=str(Path.cwd()),
                        stop_hook_active=False,
                    ),
                )
                for result in stop_results:
                    if result.action == "block" and result.reason:
                        self._stop_hook_active = True
                        try:
                            await self._turn(Message(role="user", content=result.reason))
                        finally:
                            self._stop_hook_active = False
                        break

            wire_send(TurnEnd())
            turn_finished = True

            # Auto-set title after first real turn (skip slash commands)
            if not command_call:
                session = self._runtime.session
                if session.state.custom_title is None:
                    from pythinker_code.utils.string import shorten

                    title = shorten(
                        Message(role="user", content=user_input).extract_text(" "),
                        width=50,
                    )
                    if title:
                        from pythinker_code.session_state import (
                            load_session_state,
                            save_session_state,
                        )

                        # Read-modify-write: load fresh state to avoid
                        # overwriting concurrent web changes
                        fresh = load_session_state(session.dir)
                        if fresh.custom_title is None:
                            fresh.custom_title = title
                            save_session_state(fresh, session.dir)
                        session.state.custom_title = fresh.custom_title
                        if session.state.custom_title:
                            from pythinker_code.scratchpad import (
                                append_scratch_event_sync,
                                rename_session_scratch,
                            )

                            rename_session_scratch(
                                session.work_dir,
                                session_id=session.id,
                                session_title=session.state.custom_title,
                            )
                            await asyncio.to_thread(
                                append_scratch_event_sync,
                                session.work_dir,
                                session_id=session.id,
                                session_title=session.state.custom_title,
                                title="session title set",
                                details=[f"title: {session.state.custom_title}"],
                                labels=[f"scope:{session.state.custom_title}"],
                            )
        finally:
            if turn_started and not turn_finished:
                wire_send(TurnEnd())
            if created_approval_source is not None and self._runtime.approval_runtime is not None:
                self._runtime.approval_runtime.cancel_by_source(
                    created_approval_source.kind,
                    created_approval_source.id,
                )
            if approval_source_token is not None:
                reset_current_approval_source(approval_source_token)
            self._prompt_queue_lock.release()

    async def _turn(self, user_message: Message) -> TurnOutcome:
        from pythinker_code.extensions import shared_event_bus
        from pythinker_code.telemetry import metrics as _m
        from pythinker_code.telemetry import otel as _otel

        if self._runtime.llm is None:
            raise LLMNotSet()

        if missing_caps := check_message(user_message, self._runtime.llm.capabilities):
            raise LLMNotSupported(self._runtime.llm, list(missing_caps))

        self._sleep_inhibitor.set_turn_running(True)
        try:
            bus = shared_event_bus()
            bus.emit(
                "user.message",
                {
                    "session_id": self._runtime.session.id,
                    "message": user_message,
                },
            )

            with _otel.start_span(
                "pythinker.turn",
                {
                    "session.id": self._runtime.session.id,
                    "agent.role": self._runtime.role,
                    "model": self._runtime.llm.model_name,
                    "plan_mode": self._plan_mode,
                },
            ) as span:
                turn_t0 = time.monotonic()
                await self._checkpoint()  # this creates the checkpoint 0 on first run
                await self._context.append_message(user_message)
                logger.debug("Appended user message to context")
                outcome = await self._agent_loop()
                span.set_attribute("turn.stop_reason", outcome.stop_reason)
                span.set_attribute("turn.step_count", outcome.step_count)
                _m.record_turn(
                    duration_seconds=time.monotonic() - turn_t0,
                    step_count=outcome.step_count,
                    stop_reason=outcome.stop_reason,
                )
                bus.emit(
                    "turn.end",
                    {
                        "session_id": self._runtime.session.id,
                        "stop_reason": outcome.stop_reason,
                        "step_count": outcome.step_count,
                    },
                )
                return outcome
        finally:
            self._sleep_inhibitor.set_turn_running(False)

    def _build_slash_commands(self) -> list[SlashCommand[Any]]:
        commands: list[SlashCommand[Any]] = list(soul_slash_registry.list_commands())
        seen_names = {cmd.name for cmd in commands}

        for template in self._runtime.prompt_templates.values():
            if template.name in seen_names:
                logger.warning(
                    "Skipping prompt template /{name}: name already registered",
                    name=template.name,
                )
                continue
            commands.append(
                SlashCommand(
                    name=template.name,
                    func=self._make_prompt_template_runner(template),
                    description=template.description or "",
                    aliases=[],
                )
            )
            seen_names.add(template.name)

        for skill in self._runtime.skills.values():
            if skill.type not in ("standard", "flow"):
                continue
            name = f"{SKILL_COMMAND_PREFIX}{skill.name}"
            if name in seen_names:
                logger.warning(
                    "Skipping skill slash command /{name}: name already registered",
                    name=name,
                )
                continue
            commands.append(
                SlashCommand(
                    name=name,
                    func=self._make_skill_runner(skill),
                    description=skill.description or "",
                    aliases=[],
                )
            )
            seen_names.add(name)

        for skill in self._runtime.skills.values():
            if skill.type != "flow":
                continue
            if skill.flow is None:
                logger.warning("Flow skill {name} has no flow; skipping", name=skill.name)
                continue
            command_name = f"{FLOW_COMMAND_PREFIX}{skill.name}"
            if command_name in seen_names:
                logger.warning(
                    "Skipping prompt flow slash command /{name}: name already registered",
                    name=command_name,
                )
                continue
            runner = FlowRunner(skill.flow, name=skill.name)
            commands.append(
                SlashCommand(
                    name=command_name,
                    func=runner.run,
                    description=skill.description or "",
                    aliases=[],
                )
            )
            seen_names.add(command_name)

        return commands

    @staticmethod
    def _index_slash_commands(
        commands: list[SlashCommand[Any]],
    ) -> dict[str, SlashCommand[Any]]:
        indexed: dict[str, SlashCommand[Any]] = {}
        for command in commands:
            indexed[command.name] = command
            for alias in command.aliases:
                indexed[alias] = command
        return indexed

    def _find_slash_command(self, name: str) -> SlashCommand[Any] | None:
        return self._slash_command_map.get(name)

    def _make_prompt_template_runner(
        self, template: PromptTemplate
    ) -> Callable[[PythinkerSoul, str], None | Awaitable[None]]:
        async def _run_template(
            soul: PythinkerSoul,
            args: str,
            *,
            _template: PromptTemplate = template,
        ) -> None:
            from pythinker_code.telemetry import track

            track("prompt_template_invoked", template_name=_template.name)
            expanded = expand_prompt_template(_template, args)
            await soul._turn(Message(role="user", content=expanded))

        _run_template.__doc__ = template.description
        return _run_template

    def _record_invoked_skill(self, skill_name: str) -> None:
        """Remember a slash-invoked skill so compaction can restore its instructions."""
        active_skills = self._runtime.session.state.active_skills
        if skill_name in active_skills:
            return
        active_skills.append(skill_name)
        try:
            self._runtime.session.save_state()
        except Exception:
            logger.warning("Failed to persist active skill state", exc_info=True)

    def _make_skill_runner(
        self, skill: Skill
    ) -> Callable[[PythinkerSoul, str], None | Awaitable[None]]:
        async def _run_skill(soul: PythinkerSoul, args: str, *, _skill: Skill = skill) -> None:
            from pythinker_code.telemetry import track

            track("skill_invoked", skill_name=_skill.name)
            skill_text = await read_skill_text_with_local_specialization(
                _skill, soul._runtime.skills
            )
            if skill_text is None:
                wire_send(
                    TextPart(text=f'Failed to load skill "/{SKILL_COMMAND_PREFIX}{_skill.name}".')
                )
                return
            soul._record_invoked_skill(_skill.name)
            extra = args.strip()
            if extra:
                skill_text = f"{skill_text}\n\nUser request:\n{extra}"
            await soul._turn(Message(role="user", content=skill_text))

        _run_skill.__doc__ = skill.description
        return _run_skill

    async def _agent_loop(self) -> TurnOutcome:
        """The main agent loop for one run."""
        assert self._runtime.llm is not None

        # Discard any stale steers from a previous turn.
        while True:
            try:
                self._steer_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        if isinstance(self._agent.toolset, PythinkerToolset):
            await self.start_background_mcp_loading()
            loading = bool((snapshot := self._mcp_status_snapshot()) and snapshot.loading)
            if loading:
                wire_send(StatusUpdate(mcp_status=snapshot))
                wire_send(MCPLoadingBegin())
            try:
                await self.wait_for_background_mcp_loading()
                # Track MCP connection result
                if loading:
                    from pythinker_code.telemetry import track as _track_mcp

                    mcp_snap = self._mcp_status_snapshot()
                    if mcp_snap:
                        if mcp_snap.connected > 0:
                            _track_mcp(
                                "mcp_connected",
                                server_count=mcp_snap.connected,
                                total_count=mcp_snap.total,
                            )
                        _failed = mcp_snap.total - mcp_snap.connected
                        if _failed > 0:
                            _track_mcp(
                                "mcp_failed",
                                failed_count=_failed,
                                total_count=mcp_snap.total,
                            )
            finally:
                if loading:
                    wire_send(StatusUpdate(mcp_status=self._mcp_status_snapshot()))
                    wire_send(MCPLoadingEnd())

        step_no = 0
        self._current_step_no = 0
        # One-shot per turn: nudge at most once when a step ends on a bare
        # statement of intent (see `_looks_like_unfinished_intent`).
        self._intent_nudge_used = False
        while True:
            step_no += 1
            if step_no > self._loop_control.max_steps_per_turn:
                raise MaxStepsReached(self._loop_control.max_steps_per_turn)

            self._current_step_no = step_no
            wire_send(StepBegin(n=step_no))
            back_to_the_future: BackToTheFuture | None = None
            step_outcome: StepOutcome | None = None
            try:
                # compact the context if needed
                if should_auto_compact(
                    self._context.token_count_with_pending,
                    self._runtime.llm.max_context_size,
                    trigger_ratio=self._loop_control.compaction_trigger_ratio,
                    reserved_context_size=self._loop_control.reserved_context_size,
                ):
                    logger.info("Context too long, compacting...")
                    try:
                        await self.compact_context()
                    except Exception as compact_err:
                        from pythinker_code.telemetry.errors import report_handled_error

                        report_handled_error(compact_err, site="soul.context.compact")
                        logger.error(
                            "Context compaction failed at step {step_no}: {error_type}: {error}",
                            step_no=step_no,
                            error_type=type(compact_err).__name__,
                            error=compact_err,
                        )
                        raise

                logger.debug("Beginning step {step_no}", step_no=step_no)
                await self._checkpoint()
                self._denwa_renji.set_n_checkpoints(self._context.n_checkpoints)
                step_outcome = await self._step()
            except BackToTheFuture as e:
                back_to_the_future = e
            except Exception as e:
                from pythinker_code.telemetry.errors import report_handled_error

                report_handled_error(e, site="soul.step.error")
                # any other exception should interrupt the step
                req_id = getattr(e, "request_id", None)
                logger.error(
                    "Agent step {step_no} failed: {error_type}: {error}"
                    + (" (request_id={request_id})" if req_id else ""),
                    step_no=step_no,
                    error_type=type(e).__name__,
                    error=e,
                    request_id=req_id,
                )
                wire_send(StepInterrupted())
                # Track API/step errors
                from pythinker_code.telemetry import track

                error_type, status_code = classify_api_error(e)
                api_error_props: dict[str, bool | int | float | str | None] = {
                    "error_type": error_type,
                    "gen_ai_system": classify_llm_system(self._runtime.llm.chat_provider),
                    "model": self._runtime.llm.chat_provider.model_name,
                }
                if status_code is not None:
                    api_error_props["status_code"] = status_code
                track("api_error", **api_error_props)
                # --- StopFailure hook ---
                from pythinker_code.hooks import events as _hook_events

                self._hook_engine.fire_and_forget_trigger(
                    "StopFailure",
                    matcher_value=type(e).__name__,
                    input_data=_hook_events.stop_failure(
                        session_id=self._runtime.session.id,
                        cwd=str(Path.cwd()),
                        error_type=type(e).__name__,
                        error_message=str(e),
                    ),
                )
                # break the agent loop
                raise

            if step_outcome is not None:
                has_steers = await self._consume_pending_steers()
                if has_steers:
                    continue  # steers injected, force another LLM step

                final_message = (
                    step_outcome.assistant_message
                    if step_outcome.stop_reason == "no_tool_calls"
                    else None
                )
                return TurnOutcome(
                    stop_reason=step_outcome.stop_reason,
                    final_message=final_message,
                    step_count=step_no,
                )

            if back_to_the_future is not None:
                await self._context.revert_to(back_to_the_future.checkpoint_id)
                await self._checkpoint()
                await self._context.append_message(back_to_the_future.messages)

            # Consume any pending steers between steps
            await self._consume_pending_steers()

    async def _step(self) -> StepOutcome | None:
        """Run a single step and return a stop outcome, or None to continue."""
        # already checked in `run`
        assert self._runtime.llm is not None
        chat_provider = self._runtime.llm.chat_provider

        if self._runtime.role == "root":

            async def _append_notification(view: NotificationView) -> None:
                await self._context.append_message(build_notification_message(view, self._runtime))
                # --- Notification hook ---
                from pythinker_code.hooks import events

                self._hook_engine.fire_and_forget_trigger(
                    "Notification",
                    matcher_value=view.event.type,
                    input_data=events.notification(
                        session_id=self._runtime.session.id,
                        cwd=str(Path.cwd()),
                        sink="llm",
                        notification_type=view.event.type,
                        title=view.event.title,
                        body=view.event.body,
                        severity=view.event.severity,
                    ),
                )

            await self._runtime.notifications.deliver_pending(
                "llm",
                limit=4,
                before_claim=self._runtime.background_tasks.reconcile,
                on_notification=_append_notification,
            )

        # Dynamic injection
        injections = await self._collect_injections()
        if injections:
            combined_reminders = "\n".join(system_reminder(inj.content).text for inj in injections)
            await self._context.append_message(
                Message(
                    role="user",
                    content=[TextPart(text=combined_reminders)],
                )
            )

        # Normalize: merge adjacent user messages for clean API input
        effective_history = normalize_history(self._context.history)

        async def _run_step_once() -> StepResult:
            # run an LLM step (may be interrupted)
            from pythinker_code.telemetry import metrics as _m
            from pythinker_code.telemetry import otel as _otel

            # Resolve gen_ai.system once so spans and metrics agree.
            gen_ai_system = classify_llm_system(chat_provider)

            with _otel.start_span(
                "pythinker.llm",
                {
                    "gen_ai.system": gen_ai_system,
                    "gen_ai.request.model": chat_provider.model_name,
                    "session.id": self._runtime.session.id,
                },
            ) as span:
                llm_t0 = time.monotonic()
                try:
                    profile_token = set_step_permission_profile(
                        permission_profile_for_runtime(self._runtime)
                    )
                    try:
                        step_result = await pythinker_core.step(
                            chat_provider,
                            self._agent.system_prompt,
                            self._agent.toolset,
                            effective_history,
                            on_message_part=wire_send,
                            on_tool_result=wire_send,
                        )
                    finally:
                        reset_step_permission_profile(profile_token)
                except Exception as exc:
                    llm_elapsed = time.monotonic() - llm_t0
                    error_type, status_code = classify_api_error(exc)
                    with contextlib.suppress(Exception):
                        span.set_attribute("error.type", error_type)
                        if status_code is not None:
                            span.set_attribute("http.response.status_code", status_code)
                    with contextlib.suppress(Exception):
                        _m.record_llm_call(
                            duration_seconds=llm_elapsed,
                            system=gen_ai_system,
                            model=chat_provider.model_name,
                            success=False,
                        )
                    with contextlib.suppress(Exception):
                        _m.record_error(kind="api_error", error_type=error_type)
                    raise
                llm_elapsed = time.monotonic() - llm_t0
                # Attach response details — usage may be None on partial / cached responses.
                if step_result.id:
                    span.set_attribute("gen_ai.response.id", step_result.id)
                u = step_result.usage
                input_tokens = (
                    int(u.input) if (u and getattr(u, "input", None) is not None) else None
                )
                output_tokens = (
                    int(u.output) if (u and getattr(u, "output", None) is not None) else None
                )
                if input_tokens is not None:
                    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                if output_tokens is not None:
                    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                span.set_attribute("llm.tool_calls", len(step_result.tool_calls))
                _m.record_llm_call(
                    duration_seconds=llm_elapsed,
                    system=gen_ai_system,
                    model=chat_provider.model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=True,
                )
                return step_result

        max_attempts = self._loop_control.max_retries_per_step

        def _before_step_retry_sleep(retry_state: RetryCallState) -> None:
            self._retry_log("step", retry_state)
            self._emit_step_retry(retry_state, max_attempts=max_attempts)

        @tenacity.retry(
            retry=retry_if_exception(self._is_retryable_error),
            before_sleep=_before_step_retry_sleep,
            wait=wait_exponential_jitter(initial=0.3, max=5, jitter=0.5),
            stop=stop_after_attempt(max_attempts),
            reraise=True,
        )
        async def _pythinker_core_step_with_retry() -> StepResult:
            return await self._run_with_connection_recovery(
                "step",
                _run_step_once,
                chat_provider=chat_provider,
            )

        t0 = time.monotonic()
        result = await _pythinker_core_step_with_retry()
        llm_elapsed = time.monotonic() - t0
        usage = result.usage
        logger.info(
            "LLM step completed in {elapsed:.1f}s (input={input_tokens}, output={output_tokens})",
            elapsed=llm_elapsed,
            input_tokens=usage.input if usage else "?",
            output_tokens=usage.output if usage else "?",
        )
        status_update = StatusUpdate(
            token_usage=usage, message_id=result.id, plan_mode=self._plan_mode
        )
        if usage is not None:
            # mark the token count for the context before the step
            await self._context.update_token_count(usage.input)
            snap = self.status
            status_update.context_usage = snap.context_usage
            status_update.context_tokens = snap.context_tokens
            status_update.max_context_tokens = snap.max_context_tokens
        wire_send(status_update)

        # wait for all tool results (may be interrupted)
        plan_mode_before_tools = self._plan_mode
        results = await result.tool_results()
        logger.debug("Got tool results: {results}", results=results)

        # If a tool (EnterPlanMode/ExitPlanMode) changed plan mode during execution,
        # send a corrected StatusUpdate so the client sees the up-to-date state.
        if self._plan_mode != plan_mode_before_tools:
            wire_send(StatusUpdate(plan_mode=self._plan_mode))

        # Shield context manipulation from cancellation, but do not orphan the write task.
        grow_context_task = asyncio.create_task(self._grow_context(result, results))
        try:
            await asyncio.shield(grow_context_task)
        except asyncio.CancelledError:
            await asyncio.shield(grow_context_task)
            raise

        if invalid_summary := _malformed_empty_tool_call_summary(result.tool_calls, results):
            message = Message(
                role="assistant",
                content=[
                    TextPart(
                        text=(
                            "I couldn't continue because the model emitted malformed empty "
                            "tool calls with missing required arguments: "
                            f"{invalid_summary}. Please retry the request, or switch models "
                            "if this repeats."
                        )
                    )
                ],
            )
            await self._context.append_message(message)
            return StepOutcome(stop_reason="no_tool_calls", assistant_message=message)

        rejected_errors = [
            result.return_value
            for result in results
            if isinstance(result.return_value, ToolRejectedError)
        ]
        if (
            rejected_errors
            and not any(e.has_feedback for e in rejected_errors)
            and self._runtime.role != "subagent"
        ):
            # Pure rejection (no user feedback) — stop the turn.
            # Subagents skip this so the LLM can see the rejection and try
            # an alternative approach instead of terminating immediately.
            _ = self._denwa_renji.fetch_pending_dmail()
            return StepOutcome(stop_reason="tool_rejected", assistant_message=result.message)

        # handle pending D-Mail
        if dmail := self._denwa_renji.fetch_pending_dmail():
            assert dmail.checkpoint_id >= 0, "DenwaRenji guarantees checkpoint_id >= 0"
            assert dmail.checkpoint_id < self._context.n_checkpoints, (
                "DenwaRenji guarantees checkpoint_id < n_checkpoints"
            )
            # raise to let the main loop take us back to the future
            raise BackToTheFuture(
                dmail.checkpoint_id,
                [
                    Message(
                        role="user",
                        content=[
                            system(
                                "You just got a D-Mail from your future self. "
                                "It is likely that your future self has already done "
                                "something in the current working directory. Please read "
                                "the D-Mail and decide what to do next. You MUST NEVER "
                                "mention to the user about this information. "
                                f"D-Mail content:\n\n{dmail.message.strip()}"
                            )
                        ],
                    )
                ],
            )

        if result.tool_calls:
            return None

        # A tool-call-free message normally ends the turn. If it is only a
        # restatement of intent ("Let me synthesize the findings…") with no
        # result, nudge the model to actually deliver — but at most once per
        # turn so a stubborn model can still finish.
        if not getattr(self, "_intent_nudge_used", False) and _looks_like_unfinished_intent(
            result.message.extract_text(" ")
        ):
            self._intent_nudge_used = True
            await self._context.append_message(
                Message(
                    role="user",
                    content=[
                        system_reminder(
                            "Your previous message stated an intention to act (for example "
                            "to produce a report or run a tool) but included no tool call and "
                            "no actual result, which would normally end your turn. Either "
                            "produce the promised result now, in full, or make the necessary "
                            "tool call. Do not reply with only a restatement of intent."
                        )
                    ],
                )
            )
            return None

        return StepOutcome(stop_reason="no_tool_calls", assistant_message=result.message)

    async def _grow_context(self, result: StepResult, tool_results: list[ToolResult]):
        from pythinker_code.extensions import shared_event_bus

        logger.debug("Growing context with result: {result}", result=result)

        assert self._runtime.llm is not None
        tool_messages = [tool_result_to_message(tr) for tr in tool_results]
        for tm in tool_messages:
            if missing_caps := check_message(tm, self._runtime.llm.capabilities):
                logger.warning(
                    "Tool result message requires unsupported capabilities: {caps}",
                    caps=missing_caps,
                )
                raise LLMNotSupported(self._runtime.llm, list(missing_caps))

        bus = shared_event_bus()
        bus.emit(
            "assistant.message",
            {
                "session_id": self._runtime.session.id,
                "message": result.message,
                "usage": result.usage,
            },
        )
        for tr in tool_results:
            bus.emit(
                "tool.call.end",
                {
                    "session_id": self._runtime.session.id,
                    "tool_call_id": getattr(tr, "tool_call_id", None),
                    "is_error": getattr(tr, "is_error", False),
                },
            )

        await self._context.append_message(result.message)
        if result.usage is not None:
            await self._context.update_token_count(result.usage.total)

        logger.debug(
            "Appending tool messages to context: {tool_messages}", tool_messages=tool_messages
        )
        await self._context.append_message(tool_messages)
        # token count of tool results are not available yet

    async def compact_context(self, custom_instruction: str = "") -> None:
        """
        Compact the context.

        Raises:
            LLMNotSet: When the LLM is not set.
            ChatProviderError: When the chat provider returns an error.
        """

        chat_provider = self._runtime.llm.chat_provider if self._runtime.llm is not None else None

        async def _run_compaction_once() -> CompactionResult:
            if self._runtime.llm is None:
                raise LLMNotSet()
            return await self._compaction.compact(
                self._context.history, self._runtime.llm, custom_instruction=custom_instruction
            )

        @tenacity.retry(
            retry=retry_if_exception(self._is_retryable_error),
            before_sleep=partial(self._retry_log, "compaction"),
            wait=wait_exponential_jitter(initial=0.3, max=5, jitter=0.5),
            stop=stop_after_attempt(self._loop_control.max_retries_per_step),
            reraise=True,
        )
        async def _compact_with_retry() -> CompactionResult:
            return await self._run_with_connection_recovery(
                "compaction",
                _run_compaction_once,
                chat_provider=chat_provider,
            )

        trigger_reason = "manual" if custom_instruction else "auto"
        before_tokens = self._context.token_count
        history_before_compaction = tuple(self._context.history)
        from pythinker_code.hooks import events

        pre_compact_results = await self._hook_engine.trigger(
            "PreCompact",
            matcher_value=trigger_reason,
            input_data=events.pre_compact(
                session_id=self._runtime.session.id,
                cwd=str(Path.cwd()),
                trigger=trigger_reason,
                token_count=before_tokens,
                custom_instructions=custom_instruction,
            ),
        )
        for result in pre_compact_results:
            if result.action == "block":
                raise RuntimeError(result.reason or "Compaction blocked by PreCompact hook")

        restore_context = await build_compaction_restore_context(
            history_before_compaction,
            work_dir=self._runtime.builtin_args.PYTHINKER_WORK_DIR,
            active_skill_names=getattr(self._runtime.session.state, "active_skills", ()),
            skills_by_name=getattr(self._runtime, "skills", {}),
        )

        if getattr(self._runtime.config.memory, "harvest_on_compaction", False):
            await self._harvest_before_compaction(history_before_compaction, custom_instruction)

        wire_send(CompactionBegin())
        try:
            compaction_result = await _compact_with_retry()
            if not compaction_result.messages:
                raise RuntimeError("Compaction produced no messages; preserving existing history")
        except Exception:
            from pythinker_code.telemetry import track

            track(
                "compaction_triggered",
                trigger_type=trigger_reason,
                before_tokens=before_tokens,
                success=False,
            )
            raise
        await self._context.clear()
        await self._context.write_system_prompt(self._agent.system_prompt)
        await self._checkpoint()
        await self._context.append_message(compaction_result.messages)
        estimated_token_count = compaction_result.estimated_token_count
        summary_text = compact_summary_text(compaction_result.messages)

        if restore_context.messages:
            await self._context.append_message(restore_context.messages)
            estimated_token_count += estimate_text_tokens(restore_context.messages)

        if self._runtime.role == "root":
            active_task_snapshot = build_active_task_snapshot(self._runtime.background_tasks)
            if active_task_snapshot is not None:
                active_task_message = Message(
                    role="user",
                    content=[
                        system(
                            "The following background tasks are still active after compaction. "
                            "Use TaskList if you need to re-enumerate them later."
                        ),
                        TextPart(text=active_task_snapshot),
                    ],
                )
                await self._context.append_message(active_task_message)
                estimated_token_count += estimate_text_tokens([active_task_message])

        post_compact_results = await self._hook_engine.trigger(
            "PostCompact",
            matcher_value=trigger_reason,
            input_data=events.post_compact(
                session_id=self._runtime.session.id,
                cwd=str(Path.cwd()),
                trigger=trigger_reason,
                estimated_token_count=estimated_token_count,
                compact_summary=summary_text,
            ),
        )
        session_start_results = await self._hook_engine.trigger(
            "SessionStart",
            matcher_value="compact",
            input_data=events.session_start(
                session_id=self._runtime.session.id,
                cwd=str(Path.cwd()),
                source="compact",
            ),
        )
        hook_context_message = build_hook_context_message(
            result.additional_context for result in [*post_compact_results, *session_start_results]
        )
        if hook_context_message is not None:
            await self._context.append_message(hook_context_message)
            estimated_token_count += estimate_text_tokens([hook_context_message])

        # Estimate token count so context_usage is not reported as 0%
        await self._context.update_token_count(estimated_token_count)

        # Notify dynamic injection providers that history has been rebuilt so
        # they can reset any one-shot throttling state. Failures are isolated
        # per-provider so compaction completion (wire event + telemetry) is
        # not affected by a buggy provider.
        await self._notify_injection_providers_compacted()

        wire_send(CompactionEnd())
        wire_send(TextPart(text=restore_context.display_text()))

        from pythinker_code.telemetry import track

        track(
            "compaction_triggered",
            trigger_type=trigger_reason,
            before_tokens=before_tokens,
            after_tokens=estimated_token_count,
            success=True,
        )

    async def _harvest_before_compaction(
        self, history: Sequence[Message], custom_instruction: str = ""
    ) -> None:
        try:
            prepared = self._compaction.prepare(history, custom_instruction=custom_instruction)
        except Exception as exc:
            logger.warning("compaction prepare failed during harvest: {!r}", exc)
            return
        dropped_count = max(0, len(history) - len(prepared.to_preserve))
        dropped = list(history[:dropped_count])
        if not dropped:
            return
        try:
            from pythinker_code.memory.harvest import CompactionHarvester
            from pythinker_code.scratchpad import append_scratch_note

            notes = CompactionHarvester().harvest(dropped)
        except Exception as exc:
            logger.warning("compaction harvester crashed: {!r}", exc)
            return
        persisted = 0
        for note in notes:
            try:
                await append_scratch_note(
                    self._runtime.session.work_dir,
                    kind=note.kind,
                    content=note.content,
                    session_id=self._runtime.session.id,
                    session_title=self._runtime.session.title,
                    labels=["source:compaction"],
                )
                persisted += 1
            except Exception as exc:
                logger.warning("append_scratch_note failed for kind={!r}: {!r}", note.kind, exc)
        if persisted:
            try:
                self.rearm_injection("project_memory")
            except Exception as exc:
                logger.warning("rearm_injection(project_memory) failed: {!r}", exc)

    @staticmethod
    def _is_retryable_error(exception: BaseException) -> bool:
        if isinstance(exception, (APIConnectionError, APITimeoutError)):
            return not bool(getattr(exception, "_pythinker_recovery_exhausted", False))
        if isinstance(exception, APIEmptyResponseError):
            return True
        return isinstance(exception, APIStatusError) and exception.status_code in (
            429,  # Too Many Requests
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            504,  # Gateway Timeout
        )

    async def _run_with_connection_recovery(
        self,
        name: str,
        operation: Callable[[], Awaitable[Any]],
        *,
        chat_provider: object | None = None,
        _auth_retried: bool = False,
        _connection_retried: bool = False,
    ) -> Any:
        try:
            return await operation()
        except APIStatusError as error:
            if error.status_code != 401 or _auth_retried:
                raise
            # Only attempt refresh+retry when the active model's provider
            # uses OAuth.  For plain API-key providers there is nothing
            # to refresh and retrying would just add latency.
            active_provider = (
                self._runtime.config.providers.get(self._runtime.llm.model_config.provider)
                if self._runtime.llm and self._runtime.llm.model_config
                else None
            )
            if not (active_provider and active_provider.oauth):
                raise
            logger.warning(
                "Received 401 during {name}, attempting token refresh",
                name=name,
            )
            try:
                await self._runtime.oauth.ensure_fresh(self._runtime, force=True)
            except Exception as refresh_exc:
                logger.exception("Token refresh failed after 401.")
                raise error from refresh_exc
            # Re-enter full recovery so that transient connection errors
            # on the retry are still handled by on_retryable_error.
            return await self._run_with_connection_recovery(
                name,
                operation,
                chat_provider=chat_provider,
                _auth_retried=True,
                _connection_retried=_connection_retried,
            )
        except (APIConnectionError, APITimeoutError) as error:
            if _connection_retried:
                logger.warning(
                    "Chat provider recovery exhausted for {name}: {error_type}: {error}",
                    name=name,
                    error_type=type(error).__name__,
                    error=error,
                )
                error._pythinker_recovery_exhausted = True  # type: ignore[attr-defined]
                raise
            if not isinstance(chat_provider, RetryableChatProvider):
                raise
            try:
                recovered = chat_provider.on_retryable_error(error)
            except Exception as recover_exc:
                from pythinker_code.telemetry.errors import report_handled_error

                report_handled_error(recover_exc, site="soul.chat.recover")
                logger.exception(
                    "Failed to recover chat provider during {name} after {error_type}.",
                    name=name,
                    error_type=type(error).__name__,
                )
                raise
            if not recovered:
                logger.warning(
                    "Chat provider recovery not available for {name} after {error_type}.",
                    name=name,
                    error_type=type(error).__name__,
                )
                raise
            logger.info(
                "Recovered chat provider during {name} after {error_type}; retrying once.",
                name=name,
                error_type=type(error).__name__,
            )
            # Re-enter the full recovery path so a 401 on the retry can still
            # trigger OAuth refresh instead of bubbling straight to the user.
            return await self._run_with_connection_recovery(
                name,
                operation,
                chat_provider=chat_provider,
                _auth_retried=_auth_retried,
                _connection_retried=True,
            )

    @staticmethod
    def _retry_log(name: str, retry_state: RetryCallState):
        error = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "Retrying {name} for the {n} time (last error: {error_type}: {error}). "
            "Waiting {sleep} seconds.",
            name=name,
            n=retry_state.attempt_number,
            error_type=type(error).__name__ if error else "unknown",
            error=error or "unknown",
            sleep=retry_state.next_action.sleep
            if retry_state.next_action is not None
            else "unknown",
        )

    def _emit_step_retry(self, retry_state: RetryCallState, *, max_attempts: int) -> None:
        error = retry_state.outcome.exception() if retry_state.outcome else None
        next_action = retry_state.next_action
        wait_s = next_action.sleep if next_action is not None else 0.0
        wire_send(
            StepRetry(
                n=self._current_step_no,
                next_attempt=retry_state.attempt_number + 1,
                max_attempts=max_attempts,
                wait_s=wait_s,
                error_type=type(error).__name__ if error else "unknown",
                status_code=error.status_code if isinstance(error, APIStatusError) else None,
            )
        )


class BackToTheFuture(Exception):
    """
    Raise when we need to revert the context to a previous checkpoint.
    The main agent loop should catch this exception and handle it.
    """

    def __init__(self, checkpoint_id: int, messages: Sequence[Message]):
        self.checkpoint_id = checkpoint_id
        self.messages = messages


class FlowRunner:
    def __init__(
        self,
        flow: Flow,
        *,
        name: str | None = None,
        max_moves: int = DEFAULT_MAX_FLOW_MOVES,
    ) -> None:
        self._flow = flow
        self._name = name
        self._max_moves = max_moves

    @staticmethod
    def ralph_loop(
        user_message: Message,
        max_ralph_iterations: int,
    ) -> FlowRunner:
        prompt_content = list(user_message.content)
        prompt_text = Message(role="user", content=prompt_content).extract_text(" ").strip()
        total_runs = max_ralph_iterations + 1
        if max_ralph_iterations < 0:
            total_runs = 1000000000000000  # effectively infinite

        nodes: dict[str, FlowNode] = {
            "BEGIN": FlowNode(id="BEGIN", label="BEGIN", kind="begin"),
            "END": FlowNode(id="END", label="END", kind="end"),
        }
        outgoing: dict[str, list[FlowEdge]] = {"BEGIN": [], "END": []}

        nodes["R1"] = FlowNode(id="R1", label=prompt_content, kind="task")
        nodes["R2"] = FlowNode(
            id="R2",
            label=(
                f"{prompt_text}. (You are running in an automated loop where the same "
                "prompt is fed repeatedly. Only choose STOP when the task is fully complete. "
                "Including it will stop further iterations. If you are not 100% sure, "
                "choose CONTINUE.)"
            ).strip(),
            kind="decision",
        )
        outgoing["R1"] = []
        outgoing["R2"] = []

        outgoing["BEGIN"].append(FlowEdge(src="BEGIN", dst="R1", label=None))
        outgoing["R1"].append(FlowEdge(src="R1", dst="R2", label=None))
        outgoing["R2"].append(FlowEdge(src="R2", dst="R2", label="CONTINUE"))
        outgoing["R2"].append(FlowEdge(src="R2", dst="END", label="STOP"))

        flow = Flow(nodes=nodes, outgoing=outgoing, begin_id="BEGIN", end_id="END")
        max_moves = total_runs
        return FlowRunner(flow, max_moves=max_moves)

    async def run(self, soul: PythinkerSoul, args: str) -> None:
        if args.strip():
            command = f"/{FLOW_COMMAND_PREFIX}{self._name}" if self._name else "/flow"
            logger.warning("Agent flow {command} ignores args: {args}", command=command, args=args)
            return
        if self._name:
            from pythinker_code.telemetry import track

            track("flow_invoked", flow_name=self._name)

        current_id = self._flow.begin_id
        moves = 0
        total_steps = 0
        while True:
            node = self._flow.nodes[current_id]
            edges = self._flow.outgoing.get(current_id, [])

            if node.kind == "end":
                logger.info("Agent flow reached END node {node_id}", node_id=current_id)
                return

            if node.kind == "begin":
                if not edges:
                    logger.error(
                        'Agent flow BEGIN node "{node_id}" has no outgoing edges; stopping.',
                        node_id=node.id,
                    )
                    return
                current_id = edges[0].dst
                continue

            if moves >= self._max_moves:
                raise MaxStepsReached(total_steps)
            next_id, steps_used = await self._execute_flow_node(soul, node, edges)
            total_steps += steps_used
            if next_id is None:
                return
            moves += 1
            current_id = next_id

    async def _execute_flow_node(
        self,
        soul: PythinkerSoul,
        node: FlowNode,
        edges: list[FlowEdge],
    ) -> tuple[str | None, int]:
        if not edges:
            logger.error(
                'Agent flow node "{node_id}" has no outgoing edges; stopping.',
                node_id=node.id,
            )
            return None, 0

        base_prompt = self._build_flow_prompt(node, edges)
        prompt = base_prompt
        steps_used = 0
        while True:
            result = await self._flow_turn(soul, prompt)
            steps_used += result.step_count
            if result.stop_reason == "tool_rejected":
                logger.error("Agent flow stopped after tool rejection.")
                return None, steps_used

            if node.kind != "decision":
                return edges[0].dst, steps_used

            choice = (
                parse_choice(result.final_message.extract_text(" "))
                if result.final_message
                else None
            )
            next_id = self._match_flow_edge(edges, choice)
            if next_id is not None:
                return next_id, steps_used

            options = ", ".join(edge.label or "" for edge in edges)
            logger.warning(
                "Agent flow invalid choice. Got: {choice}. Available: {options}.",
                choice=choice or "<missing>",
                options=options,
            )
            prompt = (
                f"{base_prompt}\n\n"
                "Your last response did not include a valid choice. "
                "Reply with one of the choices using <choice>...</choice>."
            )

    @staticmethod
    def _build_flow_prompt(node: FlowNode, edges: list[FlowEdge]) -> str | list[ContentPart]:
        if node.kind != "decision":
            return node.label

        if not isinstance(node.label, str):
            label_text = Message(role="user", content=node.label).extract_text(" ")
        else:
            label_text = node.label
        choices = [edge.label for edge in edges if edge.label]
        lines = [
            label_text,
            "",
            "Available branches:",
            *(f"- {choice}" for choice in choices),
            "",
            "Reply with a choice using <choice>...</choice>.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _match_flow_edge(edges: list[FlowEdge], choice: str | None) -> str | None:
        if not choice:
            return None
        for edge in edges:
            if edge.label == choice:
                return edge.dst
        return None

    @staticmethod
    async def _flow_turn(
        soul: PythinkerSoul,
        prompt: str | list[ContentPart],
    ) -> TurnOutcome:
        wire_send(TurnBegin(user_input=prompt))
        res = await soul._turn(Message(role="user", content=prompt))  # type: ignore[reportPrivateUsage]
        wire_send(TurnEnd())
        return res
