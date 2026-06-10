from __future__ import annotations

from pathlib import Path

from xcode_cli.core.tool_registry import ToolRegistry
from xcode_cli.mcp.config import MCPConfig, MCPServerConfig
from xcode_cli.mcp.connection import MCPDiscoveredTool
from xcode_cli.mcp.state import MCPProjectState, MCPServerState, MCPToolState
from xcode_cli.mcp.tools import create_mcp_tool_defs


class FakeManager:
    def __init__(self, tools: list[MCPDiscoveredTool], result=None) -> None:
        self._tools = tools
        self.result = result or {"content": [{"type": "text", "text": "ok"}]}
        self.calls: list[tuple[str, str, dict]] = []

    def list_connected_tools(self) -> list[MCPDiscoveredTool]:
        return self._tools

    def call_tool_sync(self, server_name: str, tool_name: str, arguments: dict):
        self.calls.append((server_name, tool_name, arguments))
        return self.result


def _server(**overrides) -> MCPServerConfig:
    values = {
        "name": "filesystem",
        "type": "stdio",
        "command": "python",
        "args": (),
        "cwd": Path.cwd(),
        "env": {},
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


def test_mcp_tool_registers_with_prefixed_name() -> None:
    manager = FakeManager([_tool("read_file")])
    tool_defs, warnings, _ = create_mcp_tool_defs(
        connection_manager=manager,
        config=MCPConfig(servers=(_server(),)),
    )

    assert warnings == []
    assert tool_defs[0].name == "mcp__filesystem__read_file"
    assert tool_defs[0].parameters == {"path": {"type": "string"}}
    assert tool_defs[0].required == ["path"]


def test_mcp_tools_default_to_not_read_only() -> None:
    tool_defs, _, _ = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file")]),
        config=MCPConfig(servers=(_server(),)),
    )

    assert tool_defs[0].is_read_only is False


def test_read_only_tools_must_be_declared_in_config() -> None:
    tool_defs, _, _ = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file")]),
        config=MCPConfig(servers=(_server(read_only_tools=("read_file",)),)),
    )

    assert tool_defs[0].is_read_only is True


def test_allowlist_and_blocklist_filter_original_tool_names() -> None:
    tool_defs, _, _ = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file"), _tool("write_file"), _tool("delete")]),
        config=MCPConfig(servers=(_server(tool_allowlist=("read_file", "write_file"), tool_blocklist=("write_file",)),)),
    )

    assert [tool.name for tool in tool_defs] == ["mcp__filesystem__read_file"]


def test_invalid_schema_is_skipped_with_warning() -> None:
    tool_defs, warnings, _ = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("bad", "not a schema")]),
        config=MCPConfig(servers=(_server(),)),
    )

    assert tool_defs == []
    assert any("bad" in warning for warning in warnings)


def test_tool_registry_execute_catches_manager_error() -> None:
    manager = FakeManager([_tool("read_file")], result={"isError": True, "content": [{"type": "text", "text": "Tool error: boom"}]})
    tool_defs, _, _ = create_mcp_tool_defs(connection_manager=manager, config=MCPConfig(servers=(_server(),)))
    registry = ToolRegistry()
    registry.register(tool_defs[0])

    output = registry.execute("mcp__filesystem__read_file", {"path": "README.md"})

    assert output.content == "Tool error: boom"
    assert manager.calls == [("filesystem", "read_file", {"path": "README.md"})]


def test_long_result_is_truncated_before_tool_output() -> None:
    manager = FakeManager([_tool("read_file")], result={"content": [{"type": "text", "text": "abcdef"}]})
    tool_defs, _, _ = create_mcp_tool_defs(
        connection_manager=manager,
        config=MCPConfig(servers=(_server(),), max_mcp_output_chars=3),
    )

    output = tool_defs[0].execute(path="README.md")

    assert "[MCP output truncated: 6 -> 3 chars]" in output.content


def test_per_tool_output_limit_overrides_global_config_before_tool_output() -> None:
    manager = FakeManager([_tool("read_file")], result={"content": [{"type": "text", "text": "abcdef"}]})
    state = MCPProjectState(
        servers={"filesystem": MCPServerState(tools={"read_file": MCPToolState(max_output_chars=3)})}
    )
    tool_defs, _, catalog = create_mcp_tool_defs(
        connection_manager=manager,
        config=MCPConfig(servers=(_server(),), max_mcp_output_chars=100),
        project_state=state,
    )

    output = tool_defs[0].execute(path="README.md")

    assert "[MCP output truncated: 6 -> 3 chars]" in output.content
    assert catalog[0].output_limit == 3
    assert catalog[0].output_limit_source == "state"


def test_many_enabled_mcp_tools_adds_warning_without_hiding_tools() -> None:
    tools = [_tool(f"tool_{index}") for index in range(101)]

    tool_defs, warnings, _ = create_mcp_tool_defs(
        connection_manager=FakeManager(tools),
        config=MCPConfig(servers=(_server(),)),
    )

    assert len(tool_defs) == 101
    assert any("101" in warning and "100" in warning for warning in warnings)


def test_existing_name_conflict_is_skipped() -> None:
    tool_defs, warnings, _ = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file")]),
        config=MCPConfig(servers=(_server(),)),
        existing_names={"mcp__filesystem__read_file"},
    )

    assert tool_defs == []
    assert any("conflicts" in warning for warning in warnings)
