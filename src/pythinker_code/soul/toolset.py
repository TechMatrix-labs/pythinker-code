from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import json
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, overload

from pythinker_core.tooling import (
    CallableTool,
    CallableTool2,
    HandleResult,
    Tool,
    ToolError,
    ToolOk,
    Toolset,
)
from pythinker_core.tooling.error import (
    ToolNotFoundError,
    ToolParseError,
    ToolRuntimeError,
)
from pythinker_core.tooling.mcp import convert_mcp_content
from pythinker_core.utils.typing import JsonType

from pythinker_code.exception import InvalidToolError, MCPRuntimeError
from pythinker_code.hooks.engine import HookEngine
from pythinker_code.tools import SkipThisTool
from pythinker_code.utils.logging import logger
from pythinker_code.wire.types import (
    AudioURLPart,
    ContentPart,
    ImageURLPart,
    MCPServerSnapshot,
    MCPStatusSnapshot,
    TextPart,
    ToolCall,
    ToolCallRequest,
    ToolExecutionStarted,
    ToolResult,
    ToolReturnValue,
    VideoURLPart,
)

if TYPE_CHECKING:
    import fastmcp
    import mcp
    from fastmcp.client.client import CallToolResult
    from fastmcp.client.transports import ClientTransport
    from fastmcp.mcp_config import MCPConfig

    from pythinker_code.soul.agent import Runtime

current_tool_call = ContextVar[ToolCall | None]("current_tool_call", default=None)
_current_tool_execution_started_ids: ContextVar[set[str] | None] = ContextVar(
    "current_tool_execution_started_ids", default=None
)

_current_session_id: ContextVar[str] = ContextVar("_current_session_id", default="")
_MCP_LOG_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def set_session_id(sid: str) -> None:
    _current_session_id.set(sid)


def get_session_id() -> str:
    return _current_session_id.get()


def _get_session_id() -> str:
    return _current_session_id.get()


def get_current_tool_call_or_none() -> ToolCall | None:
    """
    Get the current tool call or None.
    Expect to be not None when called from a `__call__` method of a tool.
    """
    return current_tool_call.get()


def emit_current_tool_execution_started() -> None:
    """Emit ToolExecutionStarted once for the current tool call, if wire is active."""
    tool_call = get_current_tool_call_or_none()
    if tool_call is None:
        return

    started_ids = _current_tool_execution_started_ids.get()
    if started_ids is None:
        started_ids = set[str]()
        _current_tool_execution_started_ids.set(started_ids)
    if tool_call.id in started_ids:
        return
    started_ids.add(tool_call.id)

    try:
        from pythinker_code.soul import get_wire_or_none

        if wire := get_wire_or_none():
            wire.soul_side.send(ToolExecutionStarted(tool_call_id=tool_call.id))
    except Exception as exc:  # noqa: BLE001 - lifecycle events must not break tool execution
        logger.debug(
            "Failed to emit tool execution start: {tool_name} (call_id={call_id}): {error}",
            tool_name=tool_call.function.name,
            call_id=tool_call.id,
            error=exc,
        )


def _tool_defers_execution_started(tool: ToolType) -> bool:
    return bool(
        getattr(tool, "emits_tool_execution_started_after_approval", False)
        or hasattr(tool, "_approval")
    )


def _mcp_stderr_log_path(runtime: Runtime, server_name: str) -> Path:
    safe_name = _MCP_LOG_NAME_RE.sub("_", server_name).strip("._-") or "server"
    log_dir = runtime.session.dir / "mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{safe_name}.stderr.log"


def _configure_mcp_client_stderr_log(client: Any, runtime: Runtime, server_name: str) -> None:
    """Route stdio MCP child stderr to a session log file instead of the TUI."""
    log_path = _mcp_stderr_log_path(runtime, server_name)

    def _set_transport_log_file(transport: Any) -> None:
        if hasattr(transport, "log_file"):
            transport.log_file = log_path
        nested = getattr(transport, "transport", None)
        if nested is not None:
            _set_transport_log_file(nested)
        for child in getattr(transport, "_transports", ()) or ():
            _set_transport_log_file(child)

    _set_transport_log_file(getattr(client, "transport", None))


type ToolType = CallableTool | CallableTool2[Any]


if TYPE_CHECKING:

    def type_check(pythinker_toolset: PythinkerToolset):
        _: Toolset = pythinker_toolset


class PythinkerToolset:
    def __init__(self, runtime: Runtime | None = None) -> None:
        self._runtime = runtime
        self._tool_dict: dict[str, ToolType] = {}
        self._hidden_tools: set[str] = set()
        self._mcp_servers: dict[str, MCPServerInfo] = {}
        self._mcp_loading_task: asyncio.Task[None] | None = None
        self._deferred_mcp_load: tuple[list[MCPConfig], Runtime] | None = None
        self._hook_engine: HookEngine = HookEngine()

    def set_hook_engine(self, engine: HookEngine) -> None:
        self._hook_engine = engine

    def add(self, tool: ToolType) -> None:
        self._tool_dict[tool.name] = tool

    def hide(self, tool_name: str) -> bool:
        """Hide a tool from the LLM tool list. Returns True if the tool exists."""
        if tool_name in self._tool_dict:
            self._hidden_tools.add(tool_name)
            return True
        return False

    def unhide(self, tool_name: str) -> None:
        """Restore a hidden tool to the LLM tool list."""
        self._hidden_tools.discard(tool_name)

    @overload
    def find(self, tool_name_or_type: str) -> ToolType | None: ...
    @overload
    def find[T: ToolType](self, tool_name_or_type: type[T]) -> T | None: ...
    def find(self, tool_name_or_type: str | type[ToolType]) -> ToolType | None:
        if isinstance(tool_name_or_type, str):
            return self._tool_dict.get(tool_name_or_type)
        else:
            for tool in self._tool_dict.values():
                if isinstance(tool, tool_name_or_type):
                    return tool
        return None

    @property
    def tools(self) -> list[Tool]:
        return [
            tool.base for tool in self._tool_dict.values() if tool.name not in self._hidden_tools
        ]

    def handle(self, tool_call: ToolCall) -> HandleResult:
        token = current_tool_call.set(tool_call)
        try:
            if tool_call.function.name not in self._tool_dict:
                return ToolResult(
                    tool_call_id=tool_call.id,
                    return_value=ToolNotFoundError(tool_call.function.name),
                )

            tool = self._tool_dict[tool_call.function.name]

            try:
                arguments: JsonType = json.loads(tool_call.function.arguments or "{}", strict=False)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Tool call JSON parse error: {tool_name} (call_id={call_id}): {error}",
                    tool_name=tool_call.function.name,
                    call_id=tool_call.id,
                    error=e,
                )
                return ToolResult(tool_call_id=tool_call.id, return_value=ToolParseError(str(e)))

            async def _call():
                started_ids_token = _current_tool_execution_started_ids.set(set[str]())
                try:
                    return await _call_with_lifecycle()
                finally:
                    _current_tool_execution_started_ids.reset(started_ids_token)

            async def _call_with_lifecycle():
                tool_input_dict = arguments if isinstance(arguments, dict) else {}

                if self._runtime is not None:
                    from pythinker_code.soul.permission import check_tool_call_allowed

                    if err := check_tool_call_allowed(
                        self._runtime,
                        tool_call.function.name,
                        tool_input_dict,
                        tool=tool,
                    ):
                        return ToolResult(tool_call_id=tool_call.id, return_value=err)

                # --- PreToolUse ---
                from pythinker_code.hooks import events

                results = await self._hook_engine.trigger(
                    "PreToolUse",
                    matcher_value=tool_call.function.name,
                    input_data=events.pre_tool_use(
                        session_id=_get_session_id(),
                        cwd=str(Path.cwd()),
                        tool_name=tool_call.function.name,
                        tool_input=tool_input_dict,
                        tool_call_id=tool_call.id,
                    ),
                )
                for result in results:
                    if result.action == "block":
                        return ToolResult(
                            tool_call_id=tool_call.id,
                            return_value=ToolError(
                                message=result.reason or "Blocked by PreToolUse hook",
                                brief="Hook blocked",
                            ),
                        )

                # --- Execute tool ---
                from pythinker_code.telemetry import metrics as _m
                from pythinker_code.telemetry import otel as _otel

                if not _tool_defers_execution_started(tool):
                    emit_current_tool_execution_started()

                t0 = time.monotonic()
                _tool_span_cm = _otel.start_span(
                    "pythinker.tool",
                    {"tool.name": tool_call.function.name, "tool.call_id": tool_call.id},
                )
                _tool_span = _tool_span_cm.__enter__()
                try:
                    ret = await tool.call(arguments)
                except Exception as e:
                    tool_elapsed = time.monotonic() - t0
                    _tool_span.set_attribute("tool.success", False)
                    _tool_span.set_attribute("tool.error_type", type(e).__name__)
                    _tool_span.set_attribute("tool.duration_ms", int(tool_elapsed * 1000))
                    _tool_span_cm.__exit__(type(e), e, e.__traceback__)
                    _m.record_tool_call(
                        tool_name=tool_call.function.name,
                        duration_seconds=tool_elapsed,
                        success=False,
                        error_type=type(e).__name__,
                    )
                    _m.record_error(kind="tool_error", error_type=type(e).__name__)
                    logger.exception(
                        "Tool execution failed: {tool_name} (call_id={call_id})",
                        tool_name=tool_call.function.name,
                        call_id=tool_call.id,
                    )
                    # --- PostToolUseFailure (fire-and-forget) ---
                    self._hook_engine.fire_and_forget_trigger(
                        "PostToolUseFailure",
                        matcher_value=tool_call.function.name,
                        input_data=events.post_tool_use_failure(
                            session_id=_get_session_id(),
                            cwd=str(Path.cwd()),
                            tool_name=tool_call.function.name,
                            tool_input=tool_input_dict,
                            error=str(e),
                            tool_call_id=tool_call.id,
                        ),
                    )
                    from pythinker_code.telemetry import track

                    _error_type = type(e).__name__
                    track(
                        "tool_error",
                        tool_name=tool_call.function.name,
                        error_type=_error_type,
                    )
                    track(
                        "tool_call",
                        tool_name=tool_call.function.name,
                        success=False,
                        duration_ms=int(tool_elapsed * 1000),
                        error_type=_error_type,
                    )
                    return ToolResult(
                        tool_call_id=tool_call.id,
                        return_value=ToolRuntimeError(str(e)),
                    )

                tool_elapsed = time.monotonic() - t0
                _tool_succeeded = not isinstance(ret, ToolError)
                _tool_span.set_attribute("tool.success", _tool_succeeded)
                if isinstance(ret, ToolError):
                    _tool_span.set_attribute("tool.error_brief", ret.brief or "")
                _tool_span.set_attribute("tool.duration_ms", int(tool_elapsed * 1000))
                _tool_span_cm.__exit__(None, None, None)
                _m.record_tool_call(
                    tool_name=tool_call.function.name,
                    duration_seconds=tool_elapsed,
                    success=_tool_succeeded,
                )
                logger.info(
                    "Tool {tool_name} completed in {elapsed:.1f}s (call_id={call_id})",
                    tool_name=tool_call.function.name,
                    elapsed=tool_elapsed,
                    call_id=tool_call.id,
                )
                from pythinker_code.telemetry import track as _track_tool_call

                _track_tool_call(
                    "tool_call",
                    tool_name=tool_call.function.name,
                    success=not isinstance(ret, ToolError),
                    duration_ms=int(tool_elapsed * 1000),
                )

                # --- PostToolUse (fire-and-forget) ---
                self._hook_engine.fire_and_forget_trigger(
                    "PostToolUse",
                    matcher_value=tool_call.function.name,
                    input_data=events.post_tool_use(
                        session_id=_get_session_id(),
                        cwd=str(Path.cwd()),
                        tool_name=tool_call.function.name,
                        tool_input=tool_input_dict,
                        tool_output=str(ret)[:2000],
                        tool_call_id=tool_call.id,
                    ),
                )

                return ToolResult(tool_call_id=tool_call.id, return_value=ret)

            return asyncio.create_task(_call())
        finally:
            current_tool_call.reset(token)

    def register_external_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> tuple[bool, str | None]:
        if name in self._tool_dict:
            existing = self._tool_dict[name]
            if not isinstance(existing, WireExternalTool):
                return False, "tool name conflicts with existing tool"
        try:
            tool = WireExternalTool(
                name=name,
                description=description,
                parameters=parameters,
            )
        except Exception as e:
            from pythinker_code.telemetry.errors import report_handled_error

            report_handled_error(e, site="soul.toolset.register_external")
            return False, str(e)
        self.add(tool)
        return True, None

    @property
    def mcp_servers(self) -> dict[str, MCPServerInfo]:
        """Get MCP servers info."""
        return self._mcp_servers

    def mcp_status_snapshot(self) -> MCPStatusSnapshot | None:
        """Return a read-only snapshot of current MCP startup state."""
        if not self._mcp_servers:
            return None

        servers = tuple(
            MCPServerSnapshot(
                name=name,
                status=info.status,
                tools=tuple(tool.name for tool in info.tools),
            )
            for name, info in self._mcp_servers.items()
        )
        return MCPStatusSnapshot(
            loading=self.has_pending_mcp_tools(),
            connected=sum(1 for server in servers if server.status == "connected"),
            total=len(servers),
            tools=sum(len(server.tools) for server in servers),
            servers=servers,
        )

    def defer_mcp_tool_loading(self, mcp_configs: list[MCPConfig], runtime: Runtime) -> None:
        """Store MCP configs for a later background startup."""
        self._deferred_mcp_load = (list(mcp_configs), runtime)

    def has_deferred_mcp_tools(self) -> bool:
        """Return True when MCP loading is configured but has not started yet."""
        return self._deferred_mcp_load is not None

    async def start_deferred_mcp_tool_loading(self) -> bool:
        """Start any deferred MCP loading in the background."""
        if self._deferred_mcp_load is None:
            return False
        if self._mcp_loading_task is not None or self._mcp_servers:
            self._deferred_mcp_load = None
            return False

        mcp_configs, runtime = self._deferred_mcp_load
        self._deferred_mcp_load = None
        await self.load_mcp_tools(mcp_configs, runtime, in_background=True)
        return True

    def load_tools(self, tool_paths: list[str], dependencies: dict[type[Any], Any]) -> None:
        """
        Load tools from paths like `pythinker_code.tools.shell:Shell`.

        Raises:
            InvalidToolError(PythinkerCLIException, ValueError): When any tool cannot be loaded.
        """

        good_tools: list[str] = []
        bad_tools: list[str] = []

        for tool_path in tool_paths:
            try:
                tool = self._load_tool(tool_path, dependencies)
            except SkipThisTool:
                logger.info("Skipping tool: {tool_path}", tool_path=tool_path)
                continue
            if tool:
                self.add(tool)
                good_tools.append(tool_path)
            else:
                bad_tools.append(tool_path)
        logger.info("Loaded tools: {good_tools}", good_tools=good_tools)
        if bad_tools:
            raise InvalidToolError(f"Invalid tools: {bad_tools}")

    @staticmethod
    def _load_tool(tool_path: str, dependencies: dict[type[Any], Any]) -> ToolType | None:
        logger.debug("Loading tool: {tool_path}", tool_path=tool_path)
        module_name, class_name = tool_path.rsplit(":", 1)
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            logger.warning(
                "Tool module import failed: {module_name}: {error}",
                module_name=module_name,
                error=e,
            )
            return None
        tool_cls = getattr(module, class_name, None)
        if tool_cls is None:
            logger.warning(
                "Tool class not found: {class_name} in {module_name}",
                class_name=class_name,
                module_name=module_name,
            )
            return None
        args: list[Any] = []
        if "__init__" in tool_cls.__dict__:
            # the tool class overrides the `__init__` of base class
            for param in inspect.signature(tool_cls).parameters.values():
                if param.kind == inspect.Parameter.KEYWORD_ONLY:
                    # once we encounter a keyword-only parameter, we stop injecting dependencies
                    break
                # all positional parameters should be dependencies to be injected
                if param.annotation not in dependencies:
                    raise ValueError(f"Tool dependency not found: {param.annotation}")
                args.append(dependencies[param.annotation])
        return tool_cls(*args)

    # TODO(rc): remove `in_background` parameter and always load in background
    async def load_mcp_tools(
        self, mcp_configs: list[MCPConfig], runtime: Runtime, in_background: bool = True
    ) -> None:
        """
        Load MCP tools from specified MCP configs.

        Raises:
            MCPRuntimeError(PythinkerCLIException, RuntimeError): When any MCP server cannot be
                connected.
        """
        import fastmcp
        from fastmcp.mcp_config import MCPConfig, RemoteMCPServer

        from pythinker_code.ui.shell.prompt import toast

        async def _check_oauth_tokens(server_url: str) -> bool:
            """Check if OAuth tokens exist for the server."""
            try:
                from fastmcp.client.auth import oauth as fastmcp_oauth

                file_token_storage = getattr(fastmcp_oauth, "FileTokenStorage", None)
                if file_token_storage is not None:
                    storage: Any = file_token_storage(server_url=server_url)
                else:
                    provider = fastmcp_oauth.OAuth(mcp_url=server_url)
                    storage = provider.token_storage_adapter
                tokens = await storage.get_tokens()
                return tokens is not None
            except Exception:
                return False

        def _toast_mcp(message: str) -> None:
            if in_background:
                toast(
                    message,
                    duration=10.0,
                    topic="mcp",
                    immediate=True,
                    position="right",
                )

        oauth_servers: dict[str, str] = {}

        async def _connect_server(
            server_name: str, server_info: MCPServerInfo
        ) -> tuple[str, Exception | None]:
            if server_info.status != "pending":
                return server_name, None

            server_info.status = "connecting"
            try:
                async with server_info.client as client:
                    for tool in await client.list_tools():
                        server_info.tools.append(
                            MCPTool(server_name, tool, client, runtime=runtime)
                        )

                for tool in server_info.tools:
                    self.add(tool)

                server_info.status = "connected"
                logger.info("Connected MCP server: {server_name}", server_name=server_name)
                return server_name, None
            except Exception as e:
                from pythinker_code.telemetry.errors import report_handled_error

                report_handled_error(e, site="soul.toolset.mcp.connect")
                logger.error(
                    "Failed to connect MCP server: {server_name}, error: {error}",
                    server_name=server_name,
                    error=e,
                )
                server_info.status = "failed"
                return server_name, e

        async def _connect():
            _toast_mcp("connecting to mcp servers...")
            unauthorized_servers: dict[str, str] = {}
            for server_name, server_info in self._mcp_servers.items():
                server_url = oauth_servers.get(server_name)
                if not server_url:
                    continue
                if not await _check_oauth_tokens(server_url):
                    logger.warning(
                        "Skipping OAuth MCP server '{server_name}': not authorized. "
                        "Run 'pythinker mcp auth {server_name}' first.",
                        server_name=server_name,
                    )
                    server_info.status = "unauthorized"
                    unauthorized_servers[server_name] = server_url

            tasks = [
                asyncio.create_task(_connect_server(server_name, server_info))
                for server_name, server_info in self._mcp_servers.items()
                if server_info.status == "pending"
            ]
            results = await asyncio.gather(*tasks) if tasks else []
            failed_servers = {name: error for name, error in results if error is not None}

            for mcp_config in mcp_configs:
                # Skip empty MCP configs (no servers defined)
                if not mcp_config.mcpServers:
                    logger.debug("Skipping empty MCP config: {mcp_config}", mcp_config=mcp_config)
                    continue

            if failed_servers:
                _toast_mcp("mcp connection failed")
                raise MCPRuntimeError(f"Failed to connect MCP servers: {failed_servers}")
            if unauthorized_servers:
                _toast_mcp("mcp authorization needed")
            else:
                _toast_mcp("mcp servers connected")

        for mcp_config in mcp_configs:
            if not mcp_config.mcpServers:
                logger.debug("Skipping empty MCP config: {mcp_config}", mcp_config=mcp_config)
                continue

            for server_name, server_config in mcp_config.mcpServers.items():
                if isinstance(server_config, RemoteMCPServer) and server_config.auth == "oauth":
                    oauth_servers[server_name] = server_config.url

                client = fastmcp.Client(MCPConfig(mcpServers={server_name: server_config}))
                _configure_mcp_client_stderr_log(client, runtime, server_name)
                self._mcp_servers[server_name] = MCPServerInfo(
                    status="pending", client=client, tools=[]
                )

        if in_background:
            self._mcp_loading_task = asyncio.create_task(_connect())
        else:
            await _connect()

    def has_pending_mcp_tools(self) -> bool:
        """Return True if the background MCP tool-loading task is still running."""
        return self._mcp_loading_task is not None and not self._mcp_loading_task.done()

    async def wait_for_mcp_tools(self) -> None:
        """Wait for background MCP tool loading to finish."""
        task = self._mcp_loading_task
        if not task:
            return
        try:
            await task
        finally:
            if self._mcp_loading_task is task and task.done():
                self._mcp_loading_task = None

    async def cleanup(self) -> None:
        """Cleanup any resources held by the toolset."""
        self._deferred_mcp_load = None
        if self._mcp_loading_task:
            self._mcp_loading_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._mcp_loading_task
        for server_info in self._mcp_servers.values():
            await server_info.client.close()


@dataclass(slots=True)
class MCPServerInfo:
    status: Literal["pending", "connecting", "connected", "failed", "unauthorized"]
    client: fastmcp.Client[Any]
    tools: list[MCPTool[Any]]


class MCPTool[T: ClientTransport](CallableTool):
    def __init__(
        self,
        server_name: str,
        mcp_tool: mcp.Tool,
        client: fastmcp.Client[T],
        *,
        runtime: Runtime,
        **kwargs: Any,
    ):
        super().__init__(
            name=mcp_tool.name,
            description=(
                f"This is an MCP tool from the already-connected MCP server `{server_name}`. "
                "Call it directly like any built-in tool — do NOT pip install it, import it as a "
                "Python module, or search the repo for its configuration; the server is already "
                "wired into your toolset.\n\n"
                f"{mcp_tool.description or 'No description provided.'}"
            ),
            parameters=mcp_tool.inputSchema,
            **kwargs,
        )
        self._mcp_tool = mcp_tool
        self._mcp_server_name = server_name
        self._client = client
        self._runtime = runtime
        self._timeout = timedelta(milliseconds=runtime.config.mcp.client.tool_call_timeout_ms)
        self._action_name = f"mcp:{mcp_tool.name}"

    async def __call__(self, *args: Any, **kwargs: Any) -> ToolReturnValue:
        description = f"Call MCP tool `{self._mcp_tool.name}`."
        result = await self._runtime.approval.request(self.name, self._action_name, description)
        if not result:
            return result.rejection_error()

        from pythinker_code.telemetry import otel as _otel

        # `start_span` returns a sync context manager (the OTel SDK uses
        # `_AgnosticContextManager`, which intentionally has no __aenter__).
        # Keep it as a sync `with` and use `async with` only on the fastmcp
        # client.
        try:
            with _otel.start_span(
                "pythinker.mcp.call",
                {
                    "mcp.server": self._mcp_server_name,
                    "mcp.tool": self._mcp_tool.name,
                    "mcp.timeout_ms": int(self._timeout.total_seconds() * 1000),
                },
            ) as span:
                async with self._client as client:
                    result = await client.call_tool(
                        self._mcp_tool.name,
                        kwargs,
                        timeout=self._timeout,
                        raise_on_error=False,
                    )
                    span.set_attribute("mcp.is_error", bool(result.is_error))
                    if result.is_error:
                        logger.warning(
                            "MCP tool returned error: {tool_name}: {content}",
                            tool_name=self._mcp_tool.name,
                            content=[str(p) for p in result.content][:3],
                        )
                    return convert_mcp_tool_result(result)
        except Exception as e:
            from pythinker_code.telemetry.errors import report_handled_error

            # fastmcp raises `RuntimeError` on timeout and we cannot tell it from other errors
            exc_msg = str(e).lower()
            if "timeout" in exc_msg or "timed out" in exc_msg:
                report_handled_error(e, site="soul.toolset.mcp.call.timeout", tool="MCP")
                logger.warning(
                    "MCP tool call timed out: {tool_name}: {error}",
                    tool_name=self._mcp_tool.name,
                    error=e,
                )
                return ToolError(
                    message=(
                        f"Timeout while calling MCP tool `{self._mcp_tool.name}`. "
                        "You may explain to the user that the timeout config is set too low."
                    ),
                    brief="Timeout",
                )
            report_handled_error(e, site="soul.toolset.mcp.call", tool="MCP")
            logger.error(
                "MCP tool call failed: {tool_name}: {error}",
                tool_name=self._mcp_tool.name,
                error=e,
            )
            raise


class WireExternalTool(CallableTool):
    def __init__(self, *, name: str, description: str, parameters: dict[str, Any]) -> None:
        super().__init__(
            name=name,
            description=description or "No description provided.",
            parameters=parameters,
        )

    async def __call__(self, *args: Any, **kwargs: Any) -> ToolReturnValue:
        tool_call = get_current_tool_call_or_none()
        if tool_call is None:
            return ToolError(
                message="External tool calls must be invoked from a tool call context.",
                brief="Invalid tool call",
            )

        from pythinker_code.soul import get_wire_or_none

        wire = get_wire_or_none()
        if wire is None:
            logger.error(
                "Wire is not available for external tool call: {tool_name}", tool_name=self.name
            )
            return ToolError(
                message="Wire is not available for external tool calls.",
                brief="Wire unavailable",
            )

        external_tool_call = ToolCallRequest.from_tool_call(tool_call)
        wire.soul_side.send(external_tool_call)
        try:
            return await external_tool_call.wait()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            from pythinker_code.telemetry.errors import report_handled_error

            report_handled_error(e, site="soul.toolset.external_tool", tool="External")
            logger.exception("External tool call failed: {tool_name}:", tool_name=self.name)
            return ToolError(
                message=f"External tool call failed: {e}",
                brief="External tool error",
            )


# Maximum characters allowed in MCP tool output before truncation.
# Built-in tools use 50K via ToolResultBuilder; MCP gets a wider budget because
# multi-part results (e.g. text + image) are common, but still needs a cap to
# prevent context overflow from tools like Playwright that return full DOMs.
MCP_MAX_OUTPUT_CHARS = 100_000


def _media_part_size(part: ContentPart) -> int | None:
    """Return the payload size of a media part, or ``None`` for non-media parts."""
    if isinstance(part, ImageURLPart):
        return len(part.image_url.url)
    if isinstance(part, AudioURLPart):
        return len(part.audio_url.url)
    if isinstance(part, VideoURLPart):
        return len(part.video_url.url)
    return None


def convert_mcp_tool_result(result: CallToolResult) -> ToolReturnValue:
    """Convert MCP tool result to Pythinker Core tool return value.

    All content — text *and* inline media (``data:`` URLs) — is subject to
    a shared *MCP_MAX_OUTPUT_CHARS* character budget.  Text parts are
    truncated in-place; media parts that exceed the remaining budget are
    dropped and replaced with a descriptive placeholder.

    Unsupported content types are caught and replaced with a ``TextPart``
    placeholder instead of crashing the turn.
    """
    content: list[ContentPart] = []
    char_budget = MCP_MAX_OUTPUT_CHARS
    truncated = False

    for part in result.content:
        try:
            converted = convert_mcp_content(part)
        except ValueError as exc:
            logger.warning(
                "Skipping unsupported MCP content part: {error}",
                error=exc,
            )
            converted = TextPart(text=f"[Unsupported content: {exc}]")

        # --- budget enforcement (text) ---
        if isinstance(converted, TextPart):
            if char_budget <= 0:
                truncated = True
                continue
            if len(converted.text) > char_budget:
                converted = TextPart(text=converted.text[:char_budget])
                truncated = True
            char_budget -= len(converted.text)
            content.append(converted)
            continue

        # --- budget enforcement (media: image / audio / video) ---
        media_size = _media_part_size(converted)
        if media_size is not None:
            if media_size > char_budget:
                truncated = True
                continue  # drop the oversized media part silently
            char_budget -= media_size
            content.append(converted)
            continue

        # Unknown ContentPart subclass — pass through without budget impact
        content.append(converted)

    if truncated:
        content.append(
            TextPart(
                text=(
                    f"\n\n[Output truncated: exceeded {MCP_MAX_OUTPUT_CHARS} character limit. "
                    "Use pagination or more specific queries to get remaining content.]"
                )
            )
        )

    if result.is_error:
        return ToolError(
            output=content,
            message="Tool returned an error. The output may be error message or incomplete output",
            brief="",
        )
    else:
        return ToolOk(output=content)
