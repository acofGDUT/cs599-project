from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.document import Document
from rich.console import Console

from xcode_cli.core.agent import AgentRuntime
from xcode_cli.core.commands.slash import SlashCompleter
from xcode_cli.core.tool_registry import ToolRegistry
from xcode_cli.mcp.config import MCPConfig, MCPServerConfig
from xcode_cli.mcp.connection import MCPDiscoveredTool
from xcode_cli.mcp.events import MCPEvent
from xcode_cli.mcp.state import MCPStateStore
from xcode_cli.mcp.status import MCPServerStatus
from xcode_cli.mcp.trust import MCPTrustStore


class FakeManager:
    def __init__(self, tools: list[MCPDiscoveredTool]) -> None:
        self._tools = tools
        self.shutdown_called = False
        self.refresh_calls: list[str] = []
        self.reconnect_calls: list[str | None] = []
        self.events: list[MCPEvent] = []
        self.status = "connected"

    def list_connected_tools(self) -> list[MCPDiscoveredTool]:
        return self._tools

    def call_tool_sync(self, server_name: str, tool_name: str, arguments: dict):
        return {"content": [{"type": "text", "text": "ok"}]}

    def statuses(self):
        return [
            MCPServerStatus(
                name="filesystem",
                status=self.status,
                fingerprint="sha256:" + "a" * 64,
                tool_count=len(self._tools) if self.status == "connected" else 0,
            )
        ]

    def refresh_tools_sync(self, server_name: str) -> None:
        self.refresh_calls.append(server_name)
        if self.status == "failed":
            self._tools = []
            self.events.append(MCPEvent(ts=1.0, server_name=server_name, kind="failed", message="refresh failed"))
        else:
            self.events.append(MCPEvent(ts=1.0, server_name=server_name, kind="refresh", message="refreshed"))

    def reconnect_sync(self, server_name: str | None = None) -> None:
        self.reconnect_calls.append(server_name)
        self._tools = []
        kind = "failed" if self.status == "failed" else "reconnect"
        message = "reconnect failed" if self.status == "failed" else "reconnected"
        self.events.append(MCPEvent(ts=1.0, server_name=server_name or "filesystem", kind=kind, message=message))

    def drain_events(self):
        events = list(self.events)
        self.events.clear()
        return events

    def shutdown(self) -> None:
        self.shutdown_called = True


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=True, width=140)


def _output(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


def _server(**overrides) -> MCPServerConfig:
    values = {
        "name": "filesystem",
        "type": "stdio",
        "command": "python",
        "args": ("server.py",),
        "cwd": Path.cwd(),
        "env": {"TOKEN": "secret-value"},
    }
    values.update(overrides)
    return MCPServerConfig(**values)


def _tool(name: str, schema: object | None = None) -> MCPDiscoveredTool:
    return MCPDiscoveredTool(
        server_name="filesystem",
        name=name,
        description=f"{name} desc",
        input_schema=schema if schema is not None else {"properties": {"path": {"type": "string"}}, "required": ["path"]},
    )


def _runtime(tmp_path: Path, *, server: MCPServerConfig | None = None, tools: list[MCPDiscoveredTool] | None = None):
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.console = _console()
    runtime.cwd = str(tmp_path)
    runtime._project_key = "project"
    runtime.mcp_config = MCPConfig(servers=(server or _server(),))
    runtime.mcp_trust = MCPTrustStore(tmp_path / "trust.json")
    runtime.mcp_state_store = MCPStateStore("project", path=tmp_path / "mcp_state.json")
    runtime.mcp_manager = FakeManager(tools or [_tool("read_file")])
    runtime._mcp_tool_warnings = []
    runtime._mcp_tool_catalog = []
    runtime._mcp_events = []
    runtime.tools = ToolRegistry()
    runtime._rebuild_mcp_tool_registry()
    return runtime


def test_mcp_tools_lists_catalog_without_markup_parsing(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("[red]danger[/red]")])

    runtime._handle_mcp_command(["/mcp", "tools"])

    output = _output(runtime.console)
    assert "[red]danger[/red]" in output
    assert "registered" in output
    assert "secret-value" not in output
    assert "\x1b[31m" not in output


def test_mcp_disable_server_writes_local_state_and_reloads_not_project_config(tmp_path: Path) -> None:
    project_config = tmp_path / ".xcode" / "mcp.json"
    project_config.parent.mkdir()
    project_config.write_text(json.dumps({"mcpServers": {"filesystem": {"command": "python"}}}), encoding="utf-8")
    runtime = _runtime(tmp_path)
    runtime._reload_mcp_servers = MagicMock()

    runtime._handle_mcp_command(["/mcp", "disable", "filesystem"])

    assert runtime.mcp_state_store.load().servers["filesystem"].enabled is False
    runtime._reload_mcp_servers.assert_called_once()
    assert json.loads(project_config.read_text(encoding="utf-8")) == {"mcpServers": {"filesystem": {"command": "python"}}}


def test_mcp_enable_server_does_not_write_trust(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.mcp_state_store.set_server_enabled("filesystem", False)
    runtime._reload_mcp_servers = MagicMock()

    runtime._handle_mcp_command(["/mcp", "enable", "filesystem"])

    assert runtime.mcp_state_store.load().servers["filesystem"].enabled is True
    assert not runtime.mcp_trust.is_trusted("project", runtime.mcp_config.servers[0])
    runtime._reload_mcp_servers.assert_called_once()


def test_effective_config_respects_state_disable_but_not_config_disabled_enable(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    runtime.mcp_state_store.set_server_enabled("filesystem", False)
    assert runtime._effective_mcp_config().servers[0].enabled is False

    runtime.mcp_config = MCPConfig(servers=(_server(enabled=False),))
    runtime.mcp_state_store.set_server_enabled("filesystem", True)
    assert runtime._effective_mcp_config().servers[0].enabled is False


def test_mcp_tool_disable_removes_tool_from_registry_schema(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file"), _tool("write_file")])

    runtime._handle_mcp_command(["/mcp", "tool", "disable", "filesystem", "read_file"])

    schema_names = [schema["function"]["name"] for schema in runtime.tools.get_openai_schemas()]
    assert "mcp__filesystem__read_file" not in schema_names
    assert "mcp__filesystem__write_file" in schema_names
    assert runtime.mcp_state_store.load().servers["filesystem"].tools["read_file"].enabled is False


def test_mcp_tool_enable_cannot_enable_config_blocked_tool(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, server=_server(tool_blocklist=("write_file",)), tools=[_tool("write_file")])

    runtime._handle_mcp_command(["/mcp", "tool", "enable", "filesystem", "write_file"])

    assert runtime.mcp_state_store.load().servers == {}
    assert "Cannot enable" in _output(runtime.console)
    assert runtime.tools.get_openai_schemas() == []


def test_mcp_tool_enable_cannot_enable_invalid_schema_tool(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("bad", "not a schema")])

    runtime._handle_mcp_command(["/mcp", "tool", "enable", "filesystem", "bad"])

    assert runtime.mcp_state_store.load().servers == {}
    assert "Cannot enable" in _output(runtime.console)


def test_mcp_output_limit_accepts_number_and_default(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file")])

    runtime._handle_mcp_command(["/mcp", "output-limit", "filesystem", "read_file", "12000"])
    assert runtime.mcp_state_store.load().servers["filesystem"].tools["read_file"].max_output_chars == 12000

    runtime._handle_mcp_command(["/mcp", "output-limit", "filesystem", "read_file", "default"])
    assert runtime.mcp_state_store.load().servers == {}


def test_mcp_tools_shows_output_limit_source(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file")])

    runtime._handle_mcp_command(["/mcp", "output-limit", "filesystem", "read_file", "12000"])
    runtime._handle_mcp_command(["/mcp", "tools", "filesystem"])

    output = _output(runtime.console)
    assert "12000 (state)" in output


def test_mcp_status_verbose_shows_many_tools_warning(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool(f"tool_{index}") for index in range(101)])

    runtime._handle_mcp_command(["/mcp", "status", "--verbose"])

    output = _output(runtime.console)
    assert "101" in output
    assert "100" in output


@pytest.mark.parametrize("value", ["0", "-1", "abc", "200001"])
def test_mcp_output_limit_rejects_invalid_values(tmp_path: Path, value: str) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file")])

    runtime._handle_mcp_command(["/mcp", "output-limit", "filesystem", "read_file", value])

    assert "Invalid output limit" in _output(runtime.console)
    assert runtime.mcp_state_store.load().servers == {}


def test_mcp_unknown_server_and_tool_are_readable_errors(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file")])

    runtime._handle_mcp_command(["/mcp", "disable", "missing"])
    runtime._handle_mcp_command(["/mcp", "tool", "disable", "filesystem", "missing"])

    output = _output(runtime.console)
    assert "Unknown MCP server: missing" in output
    assert "Unknown MCP tool: filesystem.missing" in output


def test_mcp_reconnect_uses_manager_and_removes_old_tools(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file")])

    runtime._handle_mcp_command(["/mcp", "reconnect", "filesystem"])

    assert runtime.mcp_manager.reconnect_calls == ["filesystem"]
    assert "mcp__filesystem__read_file" not in runtime.tools.list_names()
    assert any(event.kind == "reconnect" for event in runtime._mcp_events)


def test_mcp_refresh_failure_uses_non_committal_prompt(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file")])
    runtime.mcp_manager.status = "failed"

    runtime._handle_mcp_command(["/mcp", "refresh", "filesystem"])

    output = _output(runtime.console)
    assert runtime.mcp_manager.refresh_calls == ["filesystem"]
    assert "MCP refresh requested; check /mcp status." in output
    assert "MCP tools refreshed." not in output


def test_mcp_reconnect_failure_uses_non_committal_prompt(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file")])
    runtime.mcp_manager.status = "failed"

    runtime._handle_mcp_command(["/mcp", "reconnect", "filesystem"])

    output = _output(runtime.console)
    assert runtime.mcp_manager.reconnect_calls == ["filesystem"]
    assert "MCP reconnect requested; check /mcp status." in output
    assert "MCP servers reconnected." not in output


def test_mcp_events_prints_recent_events_without_env_values(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, tools=[_tool("read_file")])
    runtime._mcp_events = [
        MCPEvent(ts=1.0, server_name="filesystem", kind="failed", message="failed with [redacted]")
    ]

    runtime._handle_mcp_command(["/mcp", "events"])

    output = _output(runtime.console)
    assert "filesystem" in output
    assert "failed" in output
    assert "[redacted]" in output
    assert "secret-value" not in output


def test_mcp_command_completion_includes_phase2_subcommands() -> None:
    completer = SlashCompleter()

    completions = [
        completion.text
        for completion in completer.get_completions(Document("/mcp "), None)
    ]

    assert "/mcp status" in completions
    assert "/mcp tools" in completions
    assert "/mcp enable " in completions
    assert "/mcp disable " in completions
    assert "/mcp tool enable " in completions
    assert "/mcp tool disable " in completions
    assert "/mcp refresh" in completions
    assert "/mcp reconnect" in completions
    assert "/mcp events" in completions
    assert "/mcp output-limit " in completions
