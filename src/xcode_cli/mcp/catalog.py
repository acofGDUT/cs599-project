from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolCatalogState = Literal[
    "discovered",
    "registered",
    "disabled_by_config",
    "disabled_by_state",
    "invalid_schema",
    "name_conflict",
]
MCPOutputLimitSource = Literal["state", "config"]


@dataclass(frozen=True)
class MCPCatalogTool:
    server_name: str
    original_name: str
    registered_name: str | None
    state: ToolCatalogState
    read_only: bool
    schema_warnings: tuple[str, ...] = ()
    output_limit: int | None = None
    output_limit_source: MCPOutputLimitSource = "config"
