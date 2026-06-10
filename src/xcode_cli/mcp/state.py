from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import xcode_cli.paths as xcode_paths


MCP_STATE_VERSION = 1
MAX_MCP_TOOL_OUTPUT_LIMIT = 200000


@dataclass(frozen=True)
class MCPToolState:
    enabled: bool | None = None
    max_output_chars: int | None = None


@dataclass(frozen=True)
class MCPServerState:
    enabled: bool | None = None
    tools: dict[str, MCPToolState] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPProjectState:
    servers: dict[str, MCPServerState] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class MCPStateStore:
    def __init__(self, project_key: str, path: Path | None = None) -> None:
        self.project_key = project_key
        self.path = path or xcode_paths.ensure_xcode_home() / "projects" / project_key / "mcp_state.json"

    def load(self) -> MCPProjectState:
        if not self.path.exists():
            return MCPProjectState()

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            return MCPProjectState(warnings=(f"Failed to read MCP state: {exc}",))

        if not isinstance(raw, dict):
            return MCPProjectState(warnings=("MCP state root must be an object.",))

        warnings: list[str] = []
        raw_servers = raw.get("servers", {})
        if raw_servers is None:
            raw_servers = {}
        if not isinstance(raw_servers, dict):
            return MCPProjectState(warnings=("MCP state servers must be an object.",))

        servers: dict[str, MCPServerState] = {}
        for server_name, server_value in raw_servers.items():
            if not isinstance(server_name, str) or not isinstance(server_value, dict):
                warnings.append("Skipped malformed MCP server state entry.")
                continue
            server_state = self._parse_server_state(server_value, warnings)
            if server_state is not None:
                servers[server_name] = server_state

        return MCPProjectState(servers=servers, warnings=tuple(warnings))

    def set_server_enabled(self, server_name: str, enabled: bool | None) -> None:
        raw = self._load_raw_for_write()
        server = self._ensure_server(raw, server_name)
        if enabled is None:
            server.pop("enabled", None)
        else:
            server["enabled"] = bool(enabled)
        self._prune_empty_server(raw, server_name)
        self._write_raw(raw)

    def set_tool_enabled(self, server_name: str, tool_name: str, enabled: bool | None) -> None:
        raw = self._load_raw_for_write()
        tool = self._ensure_tool(raw, server_name, tool_name)
        if enabled is None:
            tool.pop("enabled", None)
        else:
            tool["enabled"] = bool(enabled)
        self._prune_empty_tool(raw, server_name, tool_name)
        self._write_raw(raw)

    def set_tool_output_limit(self, server_name: str, tool_name: str, value: int | None) -> None:
        if value is not None and (not isinstance(value, int) or value <= 0 or value > MAX_MCP_TOOL_OUTPUT_LIMIT):
            raise ValueError(f"MCP tool output limit must be between 1 and {MAX_MCP_TOOL_OUTPUT_LIMIT}.")

        raw = self._load_raw_for_write()
        tool = self._ensure_tool(raw, server_name, tool_name)
        if value is None:
            tool.pop("max_output_chars", None)
        else:
            tool["max_output_chars"] = value
        self._prune_empty_tool(raw, server_name, tool_name)
        self._write_raw(raw)

    def _parse_server_state(self, raw: dict[str, Any], warnings: list[str]) -> MCPServerState | None:
        enabled = raw.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            warnings.append("Ignored invalid MCP server enabled state.")
            enabled = None

        raw_tools = raw.get("tools", {})
        if raw_tools is None:
            raw_tools = {}
        if not isinstance(raw_tools, dict):
            warnings.append("Ignored invalid MCP server tools state.")
            raw_tools = {}

        tools: dict[str, MCPToolState] = {}
        for tool_name, tool_value in raw_tools.items():
            if not isinstance(tool_name, str) or not isinstance(tool_value, dict):
                warnings.append("Skipped malformed MCP tool state entry.")
                continue
            tool_state = self._parse_tool_state(tool_value, warnings)
            if tool_state is not None:
                tools[tool_name] = tool_state

        return MCPServerState(enabled=enabled, tools=tools)

    def _parse_tool_state(self, raw: dict[str, Any], warnings: list[str]) -> MCPToolState | None:
        enabled = raw.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            warnings.append("Ignored invalid MCP tool enabled state.")
            enabled = None

        max_output_chars = raw.get("max_output_chars")
        if max_output_chars is not None:
            if not isinstance(max_output_chars, int) or max_output_chars <= 0 or max_output_chars > MAX_MCP_TOOL_OUTPUT_LIMIT:
                warnings.append("Ignored invalid MCP tool output limit.")
                max_output_chars = None

        return MCPToolState(enabled=enabled, max_output_chars=max_output_chars)

    def _load_raw_for_write(self) -> dict[str, Any]:
        state = self.load()
        raw_servers: dict[str, Any] = {}
        for server_name, server in state.servers.items():
            server_raw: dict[str, Any] = {}
            if server.enabled is not None:
                server_raw["enabled"] = server.enabled
            if server.tools:
                tools_raw: dict[str, Any] = {}
                for tool_name, tool in server.tools.items():
                    tool_raw: dict[str, Any] = {}
                    if tool.enabled is not None:
                        tool_raw["enabled"] = tool.enabled
                    if tool.max_output_chars is not None:
                        tool_raw["max_output_chars"] = tool.max_output_chars
                    if tool_raw:
                        tools_raw[tool_name] = tool_raw
                if tools_raw:
                    server_raw["tools"] = tools_raw
            if server_raw:
                raw_servers[server_name] = server_raw
        return {"version": MCP_STATE_VERSION, "servers": raw_servers}

    def _write_raw(self, raw: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _ensure_server(self, raw: dict[str, Any], server_name: str) -> dict[str, Any]:
        servers = raw.setdefault("servers", {})
        server = servers.setdefault(server_name, {})
        return server

    def _ensure_tool(self, raw: dict[str, Any], server_name: str, tool_name: str) -> dict[str, Any]:
        server = self._ensure_server(raw, server_name)
        tools = server.setdefault("tools", {})
        tool = tools.setdefault(tool_name, {})
        return tool

    def _prune_empty_tool(self, raw: dict[str, Any], server_name: str, tool_name: str) -> None:
        servers = raw.get("servers", {})
        server = servers.get(server_name, {})
        tools = server.get("tools", {})
        tool = tools.get(tool_name, {})
        if not tool:
            tools.pop(tool_name, None)
        if not tools:
            server.pop("tools", None)
        self._prune_empty_server(raw, server_name)

    def _prune_empty_server(self, raw: dict[str, Any], server_name: str) -> None:
        servers = raw.get("servers", {})
        server = servers.get(server_name, {})
        if not server:
            servers.pop(server_name, None)
