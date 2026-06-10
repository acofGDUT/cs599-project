from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from xcode_cli.core.agent import AgentRuntime
from xcode_cli.core.llm import LLMResponse
from xcode_cli.mcp.config import MCPConfig, MCPServerConfig, load_mcp_config
from xcode_cli.mcp.connection import MCPConnectionManager, MCPDiscoveredTool
from xcode_cli.mcp.trust import MCPTrustStore


def _server(name: str = "filesystem") -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        type="stdio",
        command="python",
        args=("server.py",),
        cwd=Path.cwd(),
        env={},
    )


def _raw_tool(name: str, schema: object | None = None) -> dict:
    return {
        "name": name,
        "description": f"{name} desc",
        "inputSchema": schema if schema is not None else {"properties": {"path": {"type": "string"}}, "required": ["path"]},
    }


class RefreshSession:
    def __init__(self, tools: list[dict], *, list_error: Exception | None = None) -> None:
        self.tools = tools
        self.list_error = list_error
        self.closed = False

    async def list_tools(self):
        if self.list_error:
            raise self.list_error
        return self.tools

    async def call_tool(self, name: str, arguments: dict):
        return {"content": [{"type": "text", "text": "ok"}]}

    async def close(self):
        self.closed = True


class RefreshFactory:
    def __init__(self, session: RefreshSession) -> None:
        self.session = session

    async def connect(self, server: MCPServerConfig) -> RefreshSession:
        return self.session


def _trusted_manager(tmp_path: Path, session: RefreshSession) -> MCPConnectionManager:
    server = _server()
    trust = MCPTrustStore(tmp_path / "trust.json")
    trust.trust("project", server)
    manager = MCPConnectionManager(
        config=MCPConfig(servers=(server,)),
        trust_store=trust,
        project_key="project",
        client_factory=RefreshFactory(session),
    )
    manager.start_trusted_servers()
    return manager


def test_manager_list_changed_marks_pending_without_refreshing_tools(tmp_path: Path) -> None:
    session = RefreshSession([_raw_tool("old")])
    manager = _trusted_manager(tmp_path, session)

    session.tools = [_raw_tool("new")]
    manager.mark_tools_changed("filesystem")

    assert manager.pending_refresh_servers() == {"filesystem"}
    assert [tool.name for tool in manager.list_connected_tools()] == ["old"]
    manager.shutdown()


def test_manager_refresh_updates_tool_list_and_clears_pending(tmp_path: Path) -> None:
    session = RefreshSession([_raw_tool("old")])
    manager = _trusted_manager(tmp_path, session)

    session.tools = [_raw_tool("new")]
    manager.mark_tools_changed("filesystem")
    manager.refresh_tools_sync("filesystem")

    assert manager.pending_refresh_servers() == set()
    assert [tool.name for tool in manager.list_connected_tools()] == ["new"]
    assert manager.statuses()[0].status == "connected"
    assert manager.statuses()[0].tool_count == 1
    assert any(event.kind == "refresh" for event in manager.drain_events())
    manager.shutdown()


def test_manager_refresh_failure_marks_failed_and_removes_tools(tmp_path: Path) -> None:
    session = RefreshSession([_raw_tool("old")])
    manager = _trusted_manager(tmp_path, session)

    session.list_error = RuntimeError("list failed with SECRET_VALUE")
    manager.mark_tools_changed("filesystem")
    manager.refresh_tools_sync("filesystem")

    assert manager.pending_refresh_servers() == set()
    assert manager.list_connected_tools() == []
    status = manager.statuses()[0]
    assert status.status == "failed"
    assert "list failed" in status.error_summary
    assert "SECRET_VALUE" not in "\n".join(event.message for event in manager.drain_events())
    assert session.closed is True
    manager.shutdown()


class DynamicFakeMCPManager:
    instances: list["DynamicFakeMCPManager"] = []

    def __init__(self, *, config, trust_store, project_key, **kwargs) -> None:
        self.config = config
        self.trust_store = trust_store
        self.project_key = project_key
        self.tools = [
            MCPDiscoveredTool(
                server_name="filesystem",
                name="old",
                description="old desc",
                input_schema={"properties": {"path": {"type": "string"}}, "required": ["path"]},
            )
        ]
        self.next_tools = list(self.tools)
        self.pending: set[str] = set()
        self.refresh_calls: list[str] = []
        DynamicFakeMCPManager.instances.append(self)

    def start_trusted_servers(self) -> None:
        return None

    def list_connected_tools(self):
        return list(self.tools)

    def mark_tools_changed(self, server_name: str) -> None:
        self.pending.add(server_name)

    def pending_refresh_servers(self) -> set[str]:
        return set(self.pending)

    def refresh_tools_sync(self, server_name: str) -> None:
        self.refresh_calls.append(server_name)
        self.tools = list(self.next_tools)
        self.pending.discard(server_name)

    def drain_events(self):
        return []

    def call_tool_sync(self, server_name: str, tool_name: str, arguments: dict):
        return {"content": [{"type": "text", "text": f"{tool_name} ok"}]}

    def statuses(self):
        return []

    def shutdown(self) -> None:
        return None


def _setup_home(tmp_path: Path, monkeypatch) -> Path:
    import xcode_cli.paths as xcode_paths

    home = tmp_path / "home" / ".xcode"
    monkeypatch.setattr(xcode_paths, "XCODE_DIR", home, raising=True)
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({"model": "test"}), encoding="utf-8")
    for sub in ("sessions", "skills", "bin"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    return home


def _write_mcp(project_dir: Path) -> None:
    mcp_dir = project_dir / ".xcode"
    mcp_dir.mkdir()
    (mcp_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"filesystem": {"command": "python", "args": ["server.py"]}}}),
        encoding="utf-8",
    )


def _make_dynamic_agent(tmp_path: Path, monkeypatch) -> AgentRuntime:
    import xcode_cli.core.agent as agent_mod

    DynamicFakeMCPManager.instances.clear()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _write_mcp(project_dir)
    _setup_home(tmp_path, monkeypatch)
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "resolve_project_root", MagicMock(return_value=str(project_dir)), raising=True)
    monkeypatch.setattr(agent_mod, "MCPConnectionManager", DynamicFakeMCPManager, raising=True)
    project_key = str(project_dir.resolve()).replace(":", "").replace("\\", "--").replace("/", "--")
    while project_key.startswith("-"):
        project_key = project_key[1:]
    cfg = load_mcp_config(project_dir)
    MCPTrustStore().trust(project_key, cfg.servers[0])
    agent = AgentRuntime()
    agent._session_id = "session"
    return agent


def test_agent_safe_point_refreshes_registry_before_llm_schema(tmp_path: Path, monkeypatch) -> None:
    agent = _make_dynamic_agent(tmp_path, monkeypatch)
    manager = DynamicFakeMCPManager.instances[0]
    manager.next_tools = [
        MCPDiscoveredTool(
            server_name="filesystem",
            name="new",
            description="new desc",
            input_schema={"properties": {"path": {"type": "string"}}, "required": ["path"]},
        )
    ]
    manager.mark_tools_changed("filesystem")
    seen_schema_names: list[str] = []

    def complete(**kwargs):
        seen_schema_names.extend(schema["function"]["name"] for schema in kwargs["tool_schemas"])
        return LLMResponse(content="done", tool_calls=[])

    agent.llm.complete = complete

    result = agent._run_llm_loop([], "system", render_output=False)

    assert result == "done"
    assert manager.refresh_calls == ["filesystem"]
    assert "mcp__filesystem__new" in seen_schema_names
    assert "mcp__filesystem__old" not in seen_schema_names
    assert "mcp__filesystem__old" not in agent.tools.list_names()


def test_removed_mcp_tool_executes_as_unknown_after_safe_point_refresh(tmp_path: Path, monkeypatch) -> None:
    agent = _make_dynamic_agent(tmp_path, monkeypatch)
    manager = DynamicFakeMCPManager.instances[0]
    manager.next_tools = []
    manager.mark_tools_changed("filesystem")

    agent._drain_mcp_refresh_events()
    output = agent.tools.execute("mcp__filesystem__old", {})

    assert output.content == "Error: unknown tool 'mcp__filesystem__old'"


def test_refresh_schema_warning_disappears_after_schema_is_fixed(tmp_path: Path, monkeypatch) -> None:
    agent = _make_dynamic_agent(tmp_path, monkeypatch)
    manager = DynamicFakeMCPManager.instances[0]
    manager.next_tools = [
        MCPDiscoveredTool(
            server_name="filesystem",
            name="bad",
            description="bad desc",
            input_schema="not a schema",
        )
    ]
    manager.mark_tools_changed("filesystem")

    agent._drain_mcp_refresh_events()

    assert any("bad" in warning for warning in agent._mcp_tool_warnings)
    assert "mcp__filesystem__bad" not in agent.tools.list_names()

    manager.next_tools = [
        MCPDiscoveredTool(
            server_name="filesystem",
            name="good",
            description="good desc",
            input_schema={"properties": {"path": {"type": "string"}}, "required": ["path"]},
        )
    ]
    manager.mark_tools_changed("filesystem")
    agent._drain_mcp_refresh_events()

    assert not any("bad" in warning for warning in agent._mcp_tool_warnings)
    assert "mcp__filesystem__good" in agent.tools.list_names()
