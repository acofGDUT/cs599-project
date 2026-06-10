from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from xcode_cli.mcp.catalog import ToolCatalogState


MCPServerState = Literal["connected", "failed", "untrusted", "disabled"]


@dataclass
class MCPToolStatus:
    original_name: str
    registered_name: str
    read_only: bool
    state: ToolCatalogState = "registered"
    schema_warnings: tuple[str, ...] = ()
    output_limit: int | None = None


@dataclass
class MCPServerStatus:
    name: str
    status: MCPServerState
    fingerprint: str
    tool_count: int = 0
    error_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    tools: list[MCPToolStatus] = field(default_factory=list)
    last_connected_at: float | None = None
    last_failed_at: float | None = None
    last_refreshed_at: float | None = None
    disabled_reason: str = ""
    event_count: int = 0
