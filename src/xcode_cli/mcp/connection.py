from __future__ import annotations

import asyncio
import re
import threading
import time
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from xcode_cli.mcp.config import MCPConfig, MCPServerConfig
from xcode_cli.mcp.events import MCPEvent, MCPEventLog
from xcode_cli.mcp.status import MCPServerStatus
from xcode_cli.mcp.trust import MCPTrustStore, compute_server_fingerprint

_CANCEL_CLEANUP_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class MCPDiscoveredTool:
    server_name: str
    name: str
    description: str
    input_schema: object


@dataclass
class _ConnectionRecord:
    server: MCPServerConfig
    session: Any
    tools: list[MCPDiscoveredTool] = field(default_factory=list)


class MCPConnectionManager:
    def __init__(
        self,
        *,
        config: MCPConfig,
        trust_store: MCPTrustStore,
        project_key: str,
        client_factory: Any | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.config = config
        self.trust_store = trust_store
        self.project_key = project_key
        self.client_factory = client_factory or SDKStdioClientFactory(on_tools_changed=self.mark_tools_changed)
        self.timeout_seconds = timeout_seconds
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="xcode-mcp", daemon=True)
        self._thread.start()
        self._records: dict[str, _ConnectionRecord] = {}
        self._statuses: dict[str, MCPServerStatus] = {}
        self._pending_refresh_servers: set[str] = set()
        self._events = MCPEventLog()
        self._event_lock = threading.Lock()
        self._shutdown = False

    def start_trusted_servers(self) -> None:
        for server in self.config.servers:
            self._start_server(server)

    def list_connected_tools(self) -> list[MCPDiscoveredTool]:
        tools: list[MCPDiscoveredTool] = []
        for record in self._records.values():
            tools.extend(record.tools)
        return tools

    def pending_refresh_servers(self) -> set[str]:
        with self._event_lock:
            return set(self._pending_refresh_servers)

    def mark_tools_changed(self, server_name: str) -> None:
        with self._event_lock:
            self._pending_refresh_servers.add(server_name)
            self._events.append(
                server_name=server_name,
                kind="list_changed",
                message=f"MCP server '{server_name}' reported tool list change.",
            )

    def refresh_tools_sync(self, server_name: str) -> None:
        record = self._records.get(server_name)
        if record is None:
            with self._event_lock:
                self._pending_refresh_servers.discard(server_name)
                self._events.append(
                    server_name=server_name,
                    kind="failed",
                    message=f"MCP server '{server_name}' is not connected; refresh skipped.",
                )
            return
        try:
            self._run_sync(self._refresh_tools(server_name))
        except Exception as exc:
            with self._event_lock:
                self._pending_refresh_servers.discard(server_name)
            self._records.pop(server_name, None)
            fingerprint = compute_server_fingerprint(self.project_key, record.server)
            summary = _sanitize_error_message(str(exc), record.server)
            self._statuses[server_name] = MCPServerStatus(
                name=server_name,
                status="failed",
                fingerprint=fingerprint,
                error_summary=summary,
            )
            with self._event_lock:
                self._events.append(
                    server_name=server_name,
                    kind="failed",
                    message=f"MCP server '{server_name}' tool refresh failed: {summary}",
                )
            with suppress(Exception):
                self._run_sync(_close_session(record.session))

    def drain_events(self) -> list[MCPEvent]:
        with self._event_lock:
            return self._events.drain()

    def reconnect_sync(self, server_name: str | None = None) -> None:
        servers = [server for server in self.config.servers if server_name is None or server.name == server_name]
        if server_name is not None and not servers:
            with self._event_lock:
                self._events.append(
                    server_name=server_name,
                    kind="failed",
                    message=f"MCP server '{server_name}' is not configured; reconnect skipped.",
                )
            return
        for server in servers:
            self._close_record_sync(server.name)
            with self._event_lock:
                self._pending_refresh_servers.discard(server.name)
                self._events.append(
                    server_name=server.name,
                    kind="reconnect",
                    message=f"MCP server '{server.name}' reconnect requested.",
                )
            self._start_server(server, reconnect=True)

    def call_tool_sync(self, server_name: str, tool_name: str, arguments: dict) -> object:
        record = self._records.get(server_name)
        if record is None:
            return _tool_error(f"MCP server '{server_name}' is not connected.")
        try:
            return self._run_sync(self._call_tool(record.session, tool_name, arguments))
        except FutureTimeoutError:
            return _tool_error(f"Tool error: MCP tool '{server_name}.{tool_name}' timed out.")
        except Exception as exc:
            summary = _sanitize_error_message(str(exc), record.server)
            return _tool_error(f"Tool error: {summary}")

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        try:
            self._run_sync(self._shutdown_async())
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=1.0)

    def statuses(self) -> list[MCPServerStatus]:
        return [self._statuses[name] for name in self._statuses]

    def _start_server(self, server: MCPServerConfig, *, reconnect: bool = False) -> None:
        fingerprint = compute_server_fingerprint(self.project_key, server)
        if not server.enabled:
            self._statuses[server.name] = MCPServerStatus(
                name=server.name,
                status="disabled",
                fingerprint=fingerprint,
                disabled_reason="disabled by config or local state",
                event_count=self._event_count(server.name),
            )
            if reconnect:
                with self._event_lock:
                    self._events.append(
                        server_name=server.name,
                        kind="warning",
                        message=f"MCP server '{server.name}' is disabled; reconnect skipped.",
                    )
            return
        if not self.trust_store.is_trusted(self.project_key, server):
            self._statuses[server.name] = MCPServerStatus(
                name=server.name,
                status="untrusted",
                fingerprint=fingerprint,
                event_count=self._event_count(server.name),
            )
            if reconnect:
                with self._event_lock:
                    self._events.append(
                        server_name=server.name,
                        kind="warning",
                        message=f"MCP server '{server.name}' is untrusted; reconnect skipped.",
                    )
            return
        try:
            self._run_sync(self._connect_server(server))
            if reconnect:
                with self._event_lock:
                    self._events.append(
                        server_name=server.name,
                        kind="reconnect",
                        message=f"MCP server '{server.name}' reconnected.",
                    )
        except FutureTimeoutError:
            self._statuses[server.name] = MCPServerStatus(
                name=server.name,
                status="failed",
                fingerprint=fingerprint,
                error_summary=f"MCP server '{server.name}' connection timed out.",
                last_failed_at=time.time(),
                event_count=self._event_count(server.name),
            )
            with self._event_lock:
                self._events.append(
                    server_name=server.name,
                    kind="failed",
                    message=f"MCP server '{server.name}' connection timed out.",
                )
        except Exception as exc:
            summary = _sanitize_error_message(str(exc), server)
            self._statuses[server.name] = MCPServerStatus(
                name=server.name,
                status="failed",
                fingerprint=fingerprint,
                error_summary=summary,
                last_failed_at=time.time(),
                event_count=self._event_count(server.name),
            )
            with self._event_lock:
                self._events.append(
                    server_name=server.name,
                    kind="failed",
                    message=f"MCP server '{server.name}' connection failed: {summary}",
                )

    async def _connect_server(self, server: MCPServerConfig) -> None:
        fingerprint = compute_server_fingerprint(self.project_key, server)
        session = await _maybe_await(self.client_factory.connect(server))
        try:
            raw_tools = await _call_method(session, "list_tools")
            tools = [_coerce_discovered_tool(server.name, item) for item in _extract_tools(raw_tools)]
        except Exception:
            with suppress(Exception):
                await _close_session(session)
            raise
        self._records[server.name] = _ConnectionRecord(server=server, session=session, tools=tools)
        self._statuses[server.name] = MCPServerStatus(
            name=server.name,
            status="connected",
            fingerprint=fingerprint,
            tool_count=len(tools),
            last_connected_at=time.time(),
            event_count=self._event_count(server.name),
        )

    async def _call_tool(self, session: Any, tool_name: str, arguments: dict) -> object:
        return await _call_method(session, "call_tool", tool_name, arguments)

    async def _refresh_tools(self, server_name: str) -> None:
        record = self._records[server_name]
        raw_tools = await _call_method(record.session, "list_tools")
        tools = [_coerce_discovered_tool(server_name, item) for item in _extract_tools(raw_tools)]
        record.tools = tools
        with self._event_lock:
            self._pending_refresh_servers.discard(server_name)
        self._statuses[server_name] = MCPServerStatus(
            name=server_name,
            status="connected",
            fingerprint=compute_server_fingerprint(self.project_key, record.server),
            tool_count=len(tools),
            last_connected_at=self._statuses.get(server_name, MCPServerStatus(server_name, "connected", "")).last_connected_at,
            last_refreshed_at=time.time(),
            event_count=self._event_count(server_name),
        )
        with self._event_lock:
            self._events.append(
                server_name=server_name,
                kind="refresh",
                message=f"MCP server '{server_name}' tool list refreshed.",
            )

    async def _shutdown_async(self) -> None:
        for server_name, record in list(self._records.items()):
            await _close_session(record.session)
            with self._event_lock:
                self._events.append(
                    server_name=server_name,
                    kind="shutdown",
                    message=f"MCP server '{server_name}' session closed.",
                )
        self._records.clear()

    def _close_record_sync(self, server_name: str) -> None:
        record = self._records.pop(server_name, None)
        if record is None:
            return
        with suppress(Exception):
            self._run_sync(_close_session(record.session))
        with self._event_lock:
            self._events.append(
                server_name=server_name,
                kind="reconnect",
                message=f"MCP server '{server_name}' previous session closed.",
            )

    def _event_count(self, server_name: str) -> int:
        with self._event_lock:
            return sum(1 for event in self._events.snapshot() if event.server_name == server_name)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_sync(self, coro):
        cleanup_done = threading.Event()
        future = asyncio.run_coroutine_threadsafe(_signal_when_done(coro, cleanup_done), self._loop)
        try:
            return future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            cleanup_done.wait(timeout=_CANCEL_CLEANUP_TIMEOUT_SECONDS)
            with suppress(FutureCancelledError, FutureTimeoutError):
                future.result(timeout=0)
            raise


class SDKStdioClientFactory:
    def __init__(self, on_tools_changed: Callable[[str], None] | None = None) -> None:
        self._on_tools_changed = on_tools_changed

    async def connect(self, server: MCPServerConfig) -> Any:
        return await SDKStdioSession.open(server, on_tools_changed=self._on_tools_changed)


class SDKStdioSession:
    def __init__(self, stack: AsyncExitStack, session: Any) -> None:
        self._stack = stack
        self._session = session

    @classmethod
    async def open(
        cls,
        server: MCPServerConfig,
        *,
        on_tools_changed: Callable[[str], None] | None = None,
    ) -> "SDKStdioSession":
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            raise RuntimeError(f"MCP SDK is not available: {exc}") from exc

        stack = AsyncExitStack()
        params = StdioServerParameters(
            command=server.command,
            args=list(server.args),
            cwd=str(server.cwd),
            env=dict(server.env) if server.env else None,
        )
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    message_handler=_make_sdk_message_handler(server.name, on_tools_changed),
                )
            )
            await session.initialize()
            return cls(stack, session)
        except BaseException:
            await stack.aclose()
            raise

    async def list_tools(self) -> object:
        return await self._session.list_tools()

    async def call_tool(self, name: str, arguments: dict) -> object:
        return await self._session.call_tool(name, arguments)

    async def close(self) -> None:
        await self._stack.aclose()


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


async def _signal_when_done(coro, event: threading.Event) -> Any:
    try:
        return await coro
    finally:
        event.set()


async def _call_method(obj: Any, method_name: str, *args) -> Any:
    method = getattr(obj, method_name)
    return await _maybe_await(method(*args))


async def _close_session(session: Any) -> None:
    close = getattr(session, "close", None)
    if close is not None:
        await _maybe_await(close())


def _extract_tools(raw_tools: object) -> list[object]:
    if isinstance(raw_tools, list):
        return raw_tools
    tools = getattr(raw_tools, "tools", None)
    if isinstance(tools, list):
        return tools
    if isinstance(raw_tools, dict) and isinstance(raw_tools.get("tools"), list):
        return raw_tools["tools"]
    return []


def _coerce_discovered_tool(server_name: str, raw_tool: object) -> MCPDiscoveredTool:
    name = _get(raw_tool, "name", "")
    description = _get(raw_tool, "description", "")
    input_schema = _get(raw_tool, "inputSchema", _get(raw_tool, "input_schema", {}))
    return MCPDiscoveredTool(
        server_name=server_name,
        name=str(name),
        description=str(description or ""),
        input_schema=input_schema,
    )


def _get(value: object, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _tool_error(message: str) -> dict[str, object]:
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def _make_sdk_message_handler(server_name: str, on_tools_changed: Callable[[str], None] | None):
    async def handle_message(message: object) -> None:
        if on_tools_changed is not None and _is_tools_list_changed_notification(message):
            on_tools_changed(server_name)

    return handle_message


def _is_tools_list_changed_notification(message: object) -> bool:
    root = getattr(message, "root", message)
    method = getattr(root, "method", None)
    if method == "notifications/tools/list_changed":
        return True
    if isinstance(root, dict) and root.get("method") == "notifications/tools/list_changed":
        return True
    return type(root).__name__ == "ToolListChangedNotification"


def _sanitize_error_message(message: str, server: MCPServerConfig | None = None) -> str:
    sanitized = message
    if server is not None:
        for value in server.env.values():
            if value:
                sanitized = sanitized.replace(value, "[redacted]")
    sanitized = re.sub(r"(?i)(authorization|token|secret)[=: ]+\S+", r"\1=[redacted]", sanitized)
    sanitized = re.sub(r"(?i)secret[_-]?\w*", "[redacted]", sanitized)
    return sanitized
