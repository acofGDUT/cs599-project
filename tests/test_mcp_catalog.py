from __future__ import annotations

from pathlib import Path

from xcode_cli.core.tool_registry import ToolRegistry
from xcode_cli.core.tools import ALL_TOOLS
from xcode_cli.mcp.catalog import MCPCatalogTool
from xcode_cli.mcp.config import MCPConfig, MCPServerConfig
from xcode_cli.mcp.connection import MCPDiscoveredTool
from xcode_cli.mcp.state import MCPProjectState, MCPServerState, MCPToolState
from xcode_cli.mcp.tools import create_mcp_tool_defs


class FakeManager:
    def __init__(self, tools: list[MCPDiscoveredTool]) -> None:
        self._tools = tools

    def list_connected_tools(self) -> list[MCPDiscoveredTool]:
        return self._tools

    def call_tool_sync(self, server_name: str, tool_name: str, arguments: dict):
        return {"content": [{"type": "text", "text": "ok"}]}


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


def _by_original(catalog: list[MCPCatalogTool]) -> dict[str, MCPCatalogTool]:
    return {tool.original_name: tool for tool in catalog}


def test_discovered_tool_defaults_to_registered() -> None:
    tool_defs, warnings, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file")]),
        config=MCPConfig(servers=(_server(),)),
    )

    assert warnings == []
    assert [tool.name for tool in tool_defs] == ["mcp__filesystem__read_file"]
    entry = catalog[0]
    assert entry.state == "registered"
    assert entry.server_name == "filesystem"
    assert entry.original_name == "read_file"
    assert entry.registered_name == "mcp__filesystem__read_file"


def test_config_blocklist_marks_tool_disabled_by_config_and_skips_schema() -> None:
    tool_defs, _, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("write_file")]),
        config=MCPConfig(servers=(_server(tool_blocklist=("write_file",)),)),
    )

    assert tool_defs == []
    assert catalog[0].state == "disabled_by_config"
    assert catalog[0].registered_name is None


def test_config_allowlist_marks_omitted_tool_disabled_by_config() -> None:
    tool_defs, _, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file"), _tool("write_file")]),
        config=MCPConfig(servers=(_server(tool_allowlist=("read_file",)),)),
    )

    entries = _by_original(catalog)
    assert [tool.name for tool in tool_defs] == ["mcp__filesystem__read_file"]
    assert entries["read_file"].state == "registered"
    assert entries["write_file"].state == "disabled_by_config"


def test_local_state_disabled_tool_is_not_registered() -> None:
    state = MCPProjectState(
        servers={"filesystem": MCPServerState(tools={"read_file": MCPToolState(enabled=False)})}
    )

    tool_defs, _, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file")]),
        config=MCPConfig(servers=(_server(),)),
        project_state=state,
    )

    assert tool_defs == []
    assert catalog[0].state == "disabled_by_state"


def test_local_state_cannot_enable_config_blocked_tool() -> None:
    state = MCPProjectState(
        servers={"filesystem": MCPServerState(tools={"write_file": MCPToolState(enabled=True)})}
    )

    tool_defs, _, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("write_file")]),
        config=MCPConfig(servers=(_server(tool_blocklist=("write_file",)),)),
        project_state=state,
    )

    assert tool_defs == []
    assert catalog[0].state == "disabled_by_config"


def test_invalid_schema_is_cataloged_and_not_registered() -> None:
    tool_defs, warnings, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("bad", "not a schema")]),
        config=MCPConfig(servers=(_server(),)),
    )

    assert tool_defs == []
    assert catalog[0].state == "invalid_schema"
    assert catalog[0].schema_warnings
    assert any("bad" in warning for warning in warnings)


def test_name_conflict_is_cataloged_and_not_registered() -> None:
    tool_defs, warnings, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file")]),
        config=MCPConfig(servers=(_server(),)),
        existing_names={"mcp__filesystem__read_file"},
    )

    assert tool_defs == []
    assert catalog[0].state == "name_conflict"
    assert catalog[0].registered_name == "mcp__filesystem__read_file"
    assert any("conflicts" in warning for warning in warnings)


def test_registered_catalog_keeps_read_only_and_output_limit() -> None:
    state = MCPProjectState(
        servers={"filesystem": MCPServerState(tools={"read_file": MCPToolState(max_output_chars=12000)})}
    )

    tool_defs, _, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file")]),
        config=MCPConfig(servers=(_server(read_only_tools=("read_file",)),)),
        project_state=state,
    )

    assert tool_defs[0].is_read_only is True
    assert catalog[0].state == "registered"
    assert catalog[0].read_only is True
    assert catalog[0].output_limit == 12000


def test_disabled_invalid_and_conflicting_tools_do_not_enter_openai_schema() -> None:
    state = MCPProjectState(
        servers={"filesystem": MCPServerState(tools={"disabled": MCPToolState(enabled=False)})}
    )
    tool_defs, _, catalog = create_mcp_tool_defs(
        connection_manager=FakeManager([
            _tool("enabled"),
            _tool("disabled"),
            _tool("blocked"),
            _tool("bad", "not a schema"),
            _tool("conflict"),
        ]),
        config=MCPConfig(servers=(_server(tool_blocklist=("blocked",)),)),
        project_state=state,
        existing_names={"mcp__filesystem__conflict"},
    )
    registry = ToolRegistry()
    for tool in tool_defs:
        registry.register(tool)

    schema_names = [schema["function"]["name"] for schema in registry.get_openai_schemas()]

    assert schema_names == ["mcp__filesystem__enabled"]
    assert {entry.state for entry in catalog} == {
        "registered",
        "disabled_by_state",
        "disabled_by_config",
        "invalid_schema",
        "name_conflict",
    }


def test_tool_registry_unregister_prefix_removes_only_mcp_tools() -> None:
    registry = ToolRegistry()
    registry.register(ALL_TOOLS[0])
    tool_defs, _, _ = create_mcp_tool_defs(
        connection_manager=FakeManager([_tool("read_file"), _tool("write_file")]),
        config=MCPConfig(servers=(_server(),)),
    )
    for tool in tool_defs:
        registry.register(tool)

    removed = registry.unregister_prefix("mcp__filesystem__")

    assert removed == ["mcp__filesystem__read_file", "mcp__filesystem__write_file"]
    assert ALL_TOOLS[0].name in registry.list_names()
    assert "mcp__filesystem__read_file" not in registry.list_names()
