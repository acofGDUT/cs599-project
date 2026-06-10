from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from xcode_cli.mcp.config import MCPConfig, MCPServerConfig
from xcode_cli.mcp.connection import MCPConnectionManager, SDKStdioSession
from xcode_cli.mcp.trust import MCPTrustStore


class FakeSession:
    def __init__(self, *, tools=None, calls=None, list_error: Exception | None = None, call_delay: float = 0) -> None:
        self.tools = tools or []
        self.calls = calls or {}
        self.list_error = list_error
        self.call_delay = call_delay
        self.closed = False

    async def list_tools(self):
        if self.list_error:
            raise self.list_error
        return self.tools

    async def call_tool(self, name: str, arguments: dict):
        if self.call_delay:
            await asyncio.sleep(self.call_delay)
        value = self.calls.get(name)
        if isinstance(value, Exception):
            raise value
        return value or {"content": [{"type": "text", "text": "ok"}]}

    async def close(self):
        self.closed = True


class FakeClientFactory:
    def __init__(self, sessions: dict[str, FakeSession | Exception | list[FakeSession | Exception]]) -> None:
        self.sessions = sessions
        self.started: list[str] = []

    async def connect(self, server: MCPServerConfig) -> FakeSession:
        self.started.append(server.name)
        value = self.sessions[server.name]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class SlowConnectFactory:
    def __init__(self) -> None:
        self.cleanup_finished = False

    async def connect(self, server: MCPServerConfig) -> FakeSession:
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0)
            self.cleanup_finished = True


def _server(name: str = "filesystem", enabled: bool = True, env: dict[str, str] | None = None) -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        type="stdio",
        command="python",
        args=("server.py",),
        cwd=Path.cwd(),
        env=env or {},
        enabled=enabled,
    )


def test_untrusted_server_does_not_connect(tmp_path: Path) -> None:
    server = _server()
    factory = FakeClientFactory({server.name: FakeSession()})
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=MCPTrustStore(tmp_path / "trust.json"),
        project_key="project",
        client_factory=factory,
    )

    manager.start_trusted_servers()

    assert factory.started == []
    assert manager.statuses()[0].status == "untrusted"
    manager.shutdown()


def test_trusted_server_connects_and_lists_tools(tmp_path: Path) -> None:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    session = FakeSession(tools=[{"name": "read_file", "description": "Read", "inputSchema": {}}])
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=FakeClientFactory({server.name: session}),
    )

    manager.start_trusted_servers()

    assert manager.statuses()[0].status == "connected"
    assert manager.statuses()[0].tool_count == 1
    assert manager.list_connected_tools()[0].name == "read_file"
    manager.shutdown()


def test_tools_changed_requires_explicit_refresh(tmp_path: Path) -> None:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    session = FakeSession(tools=[{"name": "old", "inputSchema": {}}])
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=FakeClientFactory({server.name: session}),
    )
    manager.start_trusted_servers()

    session.tools = [{"name": "new", "inputSchema": {}}]
    manager.mark_tools_changed("filesystem")

    assert manager.pending_refresh_servers() == {"filesystem"}
    assert [tool.name for tool in manager.list_connected_tools()] == ["old"]

    manager.refresh_tools_sync("filesystem")

    assert manager.pending_refresh_servers() == set()
    assert [tool.name for tool in manager.list_connected_tools()] == ["new"]
    manager.shutdown()


def test_start_failure_sets_failed_status(tmp_path: Path) -> None:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=FakeClientFactory({server.name: RuntimeError("spawn failed")}),
    )

    manager.start_trusted_servers()

    status = manager.statuses()[0]
    assert status.status == "failed"
    assert "spawn failed" in status.error_summary
    manager.shutdown()


def test_tools_list_failure_sets_failed_without_affecting_other_server(tmp_path: Path) -> None:
    bad = _server("bad")
    good = _server("good")
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", bad)
    trust.trust("project", good)
    bad_session = FakeSession(list_error=RuntimeError("list failed"))
    good_session = FakeSession(tools=[{"name": "ok", "inputSchema": {}}])
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(bad, good)),
        trust_store=trust,
        project_key="project",
        client_factory=FakeClientFactory(
            {
                "bad": bad_session,
                "good": good_session,
            }
        ),
    )

    manager.start_trusted_servers()

    statuses = {status.name: status for status in manager.statuses()}
    assert statuses["bad"].status == "failed"
    assert statuses["good"].status == "connected"
    assert bad_session.closed is True
    assert good_session.closed is False
    manager.shutdown()


def test_shutdown_closes_connected_sessions(tmp_path: Path) -> None:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    session = FakeSession()
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=FakeClientFactory({server.name: session}),
    )
    manager.start_trusted_servers()

    manager.shutdown()
    manager.shutdown()

    assert session.closed


def test_reconnect_closes_old_session_and_connects_again(tmp_path: Path) -> None:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    old_session = FakeSession(tools=[{"name": "old", "inputSchema": {}}])
    new_session = FakeSession(tools=[{"name": "new", "inputSchema": {}}])
    factory = FakeClientFactory({server.name: [old_session, new_session]})
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=factory,
    )
    manager.start_trusted_servers()

    manager.reconnect_sync("filesystem")

    assert old_session.closed is True
    assert new_session.closed is False
    assert factory.started == ["filesystem", "filesystem"]
    assert [tool.name for tool in manager.list_connected_tools()] == ["new"]
    assert any(event.kind == "reconnect" for event in manager.drain_events())
    manager.shutdown()


def test_reconnect_all_only_starts_trusted_enabled_servers(tmp_path: Path) -> None:
    trusted = _server("trusted")
    untrusted = _server("untrusted")
    disabled = _server("disabled", enabled=False)
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", trusted)
    factory = FakeClientFactory({
        "trusted": [FakeSession(), FakeSession()],
        "untrusted": FakeSession(),
        "disabled": FakeSession(),
    })
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(trusted, untrusted, disabled)),
        trust_store=trust,
        project_key="project",
        client_factory=factory,
    )
    manager.start_trusted_servers()
    factory.started.clear()

    manager.reconnect_sync()

    assert factory.started == ["trusted"]
    statuses = {status.name: status.status for status in manager.statuses()}
    assert statuses["trusted"] == "connected"
    assert statuses["untrusted"] == "untrusted"
    assert statuses["disabled"] == "disabled"
    manager.shutdown()


def test_reconnect_failure_removes_old_tools_and_redacts_env_value(tmp_path: Path) -> None:
    server = _server(env={"TOKEN": "secret-value"})
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    old_session = FakeSession(tools=[{"name": "old", "inputSchema": {}}])
    factory = FakeClientFactory({server.name: [old_session, RuntimeError("spawn failed: secret-value")]})
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=factory,
    )
    manager.start_trusted_servers()

    manager.reconnect_sync("filesystem")

    assert old_session.closed is True
    assert manager.list_connected_tools() == []
    status = manager.statuses()[0]
    assert status.status == "failed"
    assert "secret-value" not in status.error_summary
    assert "secret-value" not in "\n".join(event.message for event in manager.drain_events())
    manager.shutdown()


def test_reconnect_untrusted_server_does_not_connect(tmp_path: Path) -> None:
    server = _server()
    factory = FakeClientFactory({server.name: FakeSession()})
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=MCPTrustStore(tmp_path / "trust.json"),
        project_key="project",
        client_factory=factory,
    )

    manager.reconnect_sync("filesystem")

    assert factory.started == []
    assert manager.statuses()[0].status == "untrusted"
    manager.shutdown()


def test_repeated_reconnect_closes_each_previous_session(tmp_path: Path) -> None:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    first = FakeSession()
    second = FakeSession()
    third = FakeSession()
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=FakeClientFactory({server.name: [first, second, third]}),
    )
    manager.start_trusted_servers()

    manager.reconnect_sync("filesystem")
    manager.reconnect_sync("filesystem")

    assert first.closed is True
    assert second.closed is True
    assert third.closed is False

    manager.shutdown()

    assert third.closed is True


def test_call_tool_timeout_returns_tool_error(tmp_path: Path) -> None:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=FakeClientFactory({"filesystem": FakeSession(call_delay=0.2)}),
        timeout_seconds=0.01,
    )
    manager.start_trusted_servers()

    result = manager.call_tool_sync("filesystem", "read_file", {})

    assert isinstance(result, dict)
    assert result["isError"] is True
    assert "Tool error:" in result["content"][0]["text"]
    manager.shutdown()


def test_call_tool_exception_redacts_server_env_value(tmp_path: Path) -> None:
    server = _server(env={"TOKEN": "secret-value"})
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=FakeClientFactory({
            "filesystem": FakeSession(calls={"read_file": RuntimeError("boom secret-value token=abc123")})
        }),
    )
    manager.start_trusted_servers()

    result = manager.call_tool_sync("filesystem", "read_file", {})

    assert isinstance(result, dict)
    text = result["content"][0]["text"]
    assert result["isError"] is True
    assert "secret-value" not in text
    assert "abc123" not in text
    assert "[redacted]" in text
    manager.shutdown()


def test_connect_timeout_waits_for_cancellation_cleanup(tmp_path: Path) -> None:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    factory = SlowConnectFactory()
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=factory,
        timeout_seconds=0.01,
    )

    manager.start_trusted_servers()

    status = manager.statuses()[0]
    assert status.status == "failed"
    assert "timed out" in status.error_summary
    assert factory.cleanup_finished is True
    manager.shutdown()


def test_sdk_stdio_open_closes_partial_stack_when_initialize_is_cancelled(monkeypatch) -> None:
    closed: list[str] = []

    class FakeStdioContext:
        async def __aenter__(self):
            return "read", "write"

        async def __aexit__(self, exc_type, exc, tb):
            closed.append("stdio")

    class FakeClientSession:
        def __init__(self, read, write, **kwargs) -> None:
            self.read = read
            self.write = write

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            closed.append("session")

        async def initialize(self) -> None:
            raise asyncio.CancelledError

    fake_mcp = types.ModuleType("mcp")
    fake_client = types.ModuleType("mcp.client")
    fake_stdio = types.ModuleType("mcp.client.stdio")
    fake_mcp.StdioServerParameters = lambda **kwargs: kwargs
    fake_mcp.ClientSession = FakeClientSession
    fake_stdio.stdio_client = lambda params: FakeStdioContext()
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.client", fake_client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", fake_stdio)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(SDKStdioSession.open(_server()))
    assert closed == ["session", "stdio"]


def test_sdk_stdio_open_maps_tools_list_changed_notification(monkeypatch) -> None:
    captured_handler = None
    changed: list[str] = []

    class FakeStdioContext:
        async def __aenter__(self):
            return "read", "write"

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeClientSession:
        def __init__(self, read, write, **kwargs) -> None:
            nonlocal captured_handler
            captured_handler = kwargs.get("message_handler")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize(self) -> None:
            return None

    fake_mcp = types.ModuleType("mcp")
    fake_client = types.ModuleType("mcp.client")
    fake_stdio = types.ModuleType("mcp.client.stdio")
    fake_mcp.StdioServerParameters = lambda **kwargs: kwargs
    fake_mcp.ClientSession = FakeClientSession
    fake_stdio.stdio_client = lambda params: FakeStdioContext()
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.client", fake_client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", fake_stdio)

    async def run() -> None:
        await SDKStdioSession.open(_server(), on_tools_changed=changed.append)
        assert captured_handler is not None
        await captured_handler(types.SimpleNamespace(root=types.SimpleNamespace(method="notifications/tools/list_changed")))

    asyncio.run(run())

    assert changed == ["filesystem"]
