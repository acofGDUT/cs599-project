from __future__ import annotations

from xcode_cli.core.tool_registry import ToolDef, ToolOutput
from xcode_cli.mcp.catalog import MCPCatalogTool
from xcode_cli.mcp.config import MCPConfig, MCPServerConfig
from xcode_cli.mcp.connection import MCPConnectionManager, MCPDiscoveredTool
from xcode_cli.mcp.naming import mcp_tool_name
from xcode_cli.mcp.result import render_mcp_tool_result
from xcode_cli.mcp.schema import convert_input_schema
from xcode_cli.mcp.state import MCPProjectState, MCPServerState, MCPToolState


MCP_TOOL_COUNT_WARNING_THRESHOLD = 100


class _MCPToolCandidate:
    def __init__(
        self,
        *,
        discovered: MCPDiscoveredTool,
        server: MCPServerConfig,
        read_only: bool,
        output_limit: int,
        output_limit_source: str,
        parameters: dict,
        required: list[str],
        schema_warnings: tuple[str, ...],
    ) -> None:
        self.discovered = discovered
        self.server = server
        self.read_only = read_only
        self.output_limit = output_limit
        self.output_limit_source = output_limit_source
        self.parameters = parameters
        self.required = required
        self.schema_warnings = schema_warnings


def create_mcp_tool_defs(
    *,
    connection_manager: MCPConnectionManager,
    config: MCPConfig,
    project_state: MCPProjectState | None = None,
    existing_names: set[str] | None = None,
) -> tuple[list[ToolDef], list[str], list[MCPCatalogTool]]:
    server_configs = {server.name: server for server in config.servers}
    state = project_state or MCPProjectState()
    warnings: list[str] = list(config.warnings)
    grouped: dict[str, list[MCPDiscoveredTool]] = {}
    for tool in connection_manager.list_connected_tools():
        grouped.setdefault(tool.server_name, []).append(tool)

    tool_defs: list[ToolDef] = []
    catalog: list[MCPCatalogTool] = []
    used_names = set(existing_names or set())
    for server_name, tools in grouped.items():
        server = server_configs.get(server_name)
        if server is None:
            warnings.append(f"Skipped MCP tools for unknown server '{server_name}'.")
            continue
        server_state = state.servers.get(server_name, MCPServerState())
        candidates: list[_MCPToolCandidate] = []

        for tool in tools:
            tool_state = server_state.tools.get(tool.name, MCPToolState())
            read_only = tool.name in server.read_only_tools
            output_limit, output_limit_source = _effective_output_limit(config, tool_state)

            if not server.enabled or not _is_tool_enabled_by_config(server, tool.name):
                catalog.append(
                    MCPCatalogTool(
                        server_name=server_name,
                        original_name=tool.name,
                        registered_name=None,
                        state="disabled_by_config",
                        read_only=read_only,
                        output_limit=output_limit,
                        output_limit_source=output_limit_source,
                    )
                )
                continue
            if server_state.enabled is False or tool_state.enabled is False:
                catalog.append(
                    MCPCatalogTool(
                        server_name=server_name,
                        original_name=tool.name,
                        registered_name=None,
                        state="disabled_by_state",
                        read_only=read_only,
                        output_limit=output_limit,
                        output_limit_source=output_limit_source,
                    )
                )
                continue

            schema = convert_input_schema(tool.input_schema)
            warnings.extend(f"MCP tool '{tool.name}': {warning}" for warning in schema.warnings)
            if schema.parameters is None:
                warnings.append(f"Skipped MCP tool '{tool.name}' because its inputSchema is invalid.")
                catalog.append(
                    MCPCatalogTool(
                        server_name=server_name,
                        original_name=tool.name,
                        registered_name=None,
                        state="invalid_schema",
                        read_only=read_only,
                        schema_warnings=tuple(schema.warnings),
                        output_limit=output_limit,
                        output_limit_source=output_limit_source,
                    )
                )
                continue
            candidates.append(
                _MCPToolCandidate(
                    discovered=tool,
                    server=server,
                    read_only=read_only,
                    output_limit=output_limit,
                    output_limit_source=output_limit_source,
                    parameters=schema.parameters,
                    required=schema.required,
                    schema_warnings=tuple(schema.warnings),
                )
            )

        seen_registered: set[str] = set()
        for candidate in candidates:
            tool = candidate.discovered
            try:
                registered_name = mcp_tool_name(server_name, tool.name)
            except ValueError as exc:
                warnings.append(f"Skipped MCP tool '{tool.name}': {exc}")
                catalog.append(
                    MCPCatalogTool(
                        server_name=server_name,
                        original_name=tool.name,
                        registered_name=None,
                        state="name_conflict",
                        read_only=candidate.read_only,
                        schema_warnings=candidate.schema_warnings,
                        output_limit=candidate.output_limit,
                        output_limit_source=candidate.output_limit_source,
                    )
                )
                continue
            if registered_name in used_names or registered_name in seen_registered:
                warnings.append(f"Skipped MCP tool '{tool.name}': registered name '{registered_name}' conflicts.")
                catalog.append(
                    MCPCatalogTool(
                        server_name=server_name,
                        original_name=tool.name,
                        registered_name=registered_name,
                        state="name_conflict",
                        read_only=candidate.read_only,
                        schema_warnings=candidate.schema_warnings,
                        output_limit=candidate.output_limit,
                        output_limit_source=candidate.output_limit_source,
                    )
                )
                continue
            used_names.add(registered_name)
            seen_registered.add(registered_name)
            catalog.append(
                MCPCatalogTool(
                    server_name=server_name,
                    original_name=tool.name,
                    registered_name=registered_name,
                    state="registered",
                    read_only=candidate.read_only,
                    schema_warnings=candidate.schema_warnings,
                    output_limit=candidate.output_limit,
                    output_limit_source=candidate.output_limit_source,
                )
            )
            tool_defs.append(
                ToolDef(
                    name=registered_name,
                    description=tool.description or f"MCP tool {tool.name} from server {server_name}.",
                    parameters=candidate.parameters,
                    required=candidate.required,
                    execute=_make_execute(connection_manager, server_name, tool.name, candidate.output_limit),
                    is_read_only=candidate.read_only,
                )
            )

    if len(tool_defs) > MCP_TOOL_COUNT_WARNING_THRESHOLD:
        warnings.append(
            f"MCP enabled tool count {len(tool_defs)} exceeds recommended threshold {MCP_TOOL_COUNT_WARNING_THRESHOLD}; "
            "use /mcp tools and /mcp tool disable to reduce the exposed tool set."
        )

    return tool_defs, warnings, catalog


def _is_tool_enabled_by_config(server: MCPServerConfig, tool_name: str) -> bool:
    if server.tool_allowlist and tool_name not in server.tool_allowlist:
        return False
    if tool_name in server.tool_blocklist:
        return False
    return True


def _make_execute(connection_manager: MCPConnectionManager, server_name: str, tool_name: str, max_chars: int):
    def execute(**kwargs) -> ToolOutput:
        raw_result = connection_manager.call_tool_sync(server_name, tool_name, kwargs)
        return ToolOutput(content=render_mcp_tool_result(raw_result, max_chars=max_chars))

    return execute


def _effective_output_limit(config: MCPConfig, tool_state: MCPToolState) -> tuple[int, str]:
    if tool_state.max_output_chars is not None:
        return tool_state.max_output_chars, "state"
    return config.max_mcp_output_chars, "config"
