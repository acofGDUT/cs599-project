from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import xcode_cli.paths as xcode_paths
from xcode_cli.core.agent import AgentRuntime
from xcode_cli.core.llm import LLMResponse, ToolCall
from xcode_cli.mcp.config import load_mcp_config
from xcode_cli.mcp.connection import MCPDiscoveredTool
from xcode_cli.mcp.trust import MCPTrustStore


class FakeMCPManager:
    instances: list["FakeMCPManager"] = []
    fail_start = False

    def __init__(self, *, config, trust_store, project_key, **kwargs) -> None:
        self.config = config
        self.trust_store = trust_store
        self.project_key = project_key
        self.started = False
        self.shutdown_called = False
        FakeMCPManager.instances.append(self)

    def start_trusted_servers(self) -> None:
        self.started = True
        if FakeMCPManager.fail_start:
            raise RuntimeError("mcp failed")

    def list_connected_tools(self):
        tools = []
        for server in self.config.servers:
            if self.trust_store.is_trusted(self.project_key, server):
                tools.append(
                    MCPDiscoveredTool(
                        server_name=server.name,
                        name="read_file",
                        description="MCP read",
                        input_schema={"properties": {"path": {"type": "string"}}, "required": ["path"]},
                    )
                )
        return tools

    def call_tool_sync(self, server_name: str, tool_name: str, arguments: dict):
        return {"content": [{"type": "text", "text": f"{server_name}:{tool_name}:{arguments['path']}"}]}

    def shutdown(self):
        self.shutdown_called = True

    def statuses(self):
        return []


def _setup_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home" / ".xcode"
    monkeypatch.setattr(xcode_paths, "XCODE_DIR", home, raising=True)
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({"model": "test"}), encoding="utf-8")
    for sub in ("sessions", "skills", "bin"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    return home


def _write_mcp(project_dir: Path, *, read_only: bool = False) -> None:
    mcp_dir = project_dir / ".xcode"
    mcp_dir.mkdir()
    payload = {
        "mcpServers": {
            "filesystem": {
                "command": "python",
                "args": ["server.py"],
                "cwd": "${workspace}",
                "read_only_tools": ["read_file"] if read_only else [],
            }
        }
    }
    (mcp_dir / "mcp.json").write_text(json.dumps(payload), encoding="utf-8")


def _make_agent(tmp_path: Path, monkeypatch, *, trusted: bool = False, read_only: bool = False) -> AgentRuntime:
    import xcode_cli.core.agent as agent_mod

    FakeMCPManager.instances.clear()
    FakeMCPManager.fail_start = False
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _write_mcp(project_dir, read_only=read_only)
    _setup_home(tmp_path, monkeypatch)
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "resolve_project_root", MagicMock(return_value=str(project_dir)), raising=True)
    monkeypatch.setattr(agent_mod, "MCPConnectionManager", FakeMCPManager, raising=True)
    if trusted:
        sessions_key = str(project_dir.resolve()).replace(":", "").replace("\\", "--").replace("/", "--")
        while sessions_key.startswith("-"):
            sessions_key = sessions_key[1:]
        cfg = load_mcp_config(project_dir)
        MCPTrustStore().trust(sessions_key, cfg.servers[0])
    agent = AgentRuntime()
    agent._session_id = "session"
    return agent


def test_agent_runtime_creates_mcp_manager_for_untrusted_config(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch, trusted=False)

    assert agent.mcp_manager is FakeMCPManager.instances[0]
    assert FakeMCPManager.instances[0].started is True
    assert "mcp__filesystem__read_file" not in agent.tools.list_names()


def test_trusted_mcp_tool_registers_to_runtime_tools(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch, trusted=True)

    assert "mcp__filesystem__read_file" in agent.tools.list_names()


def test_mcp_tool_default_not_read_only_and_permission_asks(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch, trusted=True)

    assert agent.tools.is_read_only("mcp__filesystem__read_file") is False
    assert agent.permissions.check("mcp__filesystem__read_file", is_read_only=False) == "ask"


def test_read_only_config_allows_mcp_tool_by_default(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch, trusted=True, read_only=True)

    assert agent.tools.is_read_only("mcp__filesystem__read_file") is True
    assert agent.permissions.check("mcp__filesystem__read_file", is_read_only=True) == "allow"


def test_explicit_deny_overrides_read_only_mcp_tool(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch, trusted=True, read_only=True)
    settings_dir = Path(agent.cwd) / ".xcode"
    (settings_dir / "settings.json").write_text(
        json.dumps({"permissions": {"mcp__filesystem__read_file": "deny"}}),
        encoding="utf-8",
    )
    agent.permissions = agent.permissions.__class__(agent.cwd)

    assert agent.permissions.check("mcp__filesystem__read_file", is_read_only=True) == "deny"


def test_explicit_deny_blocks_mcp_tool(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch, trusted=True)
    settings_dir = Path(agent.cwd) / ".xcode"
    (settings_dir / "settings.json").write_text(
        json.dumps({"permissions": {"mcp__filesystem__read_file": "deny"}}),
        encoding="utf-8",
    )
    agent.permissions = agent.permissions.__class__(agent.cwd)
    calls = [0]

    def complete(**kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="mcp__filesystem__read_file", args={"path": "README.md"})],
            )
        assert any("Permission denied" in str(msg.get("content", "")) for msg in kwargs["messages"])
        return LLMResponse(content="blocked", tool_calls=[])

    agent.llm.complete = complete
    result = agent._run_llm_loop([], "system", render_output=False)

    assert result == "blocked"


def test_runtime_shutdown_calls_mcp_manager_shutdown(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch, trusted=False)

    agent._shutdown_mcp_manager()

    assert FakeMCPManager.instances[0].shutdown_called


def test_mcp_start_failure_does_not_break_agent_construction(tmp_path: Path, monkeypatch) -> None:
    import xcode_cli.core.agent as agent_mod

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _write_mcp(project_dir)
    _setup_home(tmp_path, monkeypatch)
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "resolve_project_root", MagicMock(return_value=str(project_dir)), raising=True)
    monkeypatch.setattr(agent_mod, "MCPConnectionManager", FakeMCPManager, raising=True)
    FakeMCPManager.instances.clear()
    FakeMCPManager.fail_start = True

    agent = AgentRuntime()

    assert agent.mcp_manager is None
    assert any("mcp failed" in warning for warning in agent._mcp_tool_warnings)
