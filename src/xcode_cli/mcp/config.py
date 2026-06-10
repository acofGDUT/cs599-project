from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from xcode_cli.mcp.naming import sanitize_mcp_name


DEFAULT_MAX_MCP_OUTPUT_CHARS = 20000
_VAR_RE = re.compile(r"\$\{([^}]+)\}")


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    type: str
    command: str
    args: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    enabled: bool = True
    tool_allowlist: tuple[str, ...] = ()
    tool_blocklist: tuple[str, ...] = ()
    read_only_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class MCPConfig:
    servers: tuple[MCPServerConfig, ...]
    max_mcp_output_chars: int = DEFAULT_MAX_MCP_OUTPUT_CHARS
    warnings: tuple[str, ...] = ()


def load_mcp_config(project_root: str | Path, env: Mapping[str, str] | None = None) -> MCPConfig:
    root = Path(project_root).resolve()
    config_path = root / ".xcode" / "mcp.json"
    warnings: list[str] = []
    if not config_path.exists():
        return MCPConfig(servers=())

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return MCPConfig(servers=(), warnings=(f"Failed to read MCP config: {exc}",))

    if not isinstance(raw, dict):
        return MCPConfig(servers=(), warnings=("MCP config root must be an object.",))

    max_chars = _positive_int(raw.get("max_mcp_output_chars"), DEFAULT_MAX_MCP_OUTPUT_CHARS)
    if "max_mcp_output_chars" in raw and max_chars == DEFAULT_MAX_MCP_OUTPUT_CHARS and raw.get("max_mcp_output_chars") != DEFAULT_MAX_MCP_OUTPUT_CHARS:
        warnings.append("Invalid max_mcp_output_chars; using default 20000.")

    raw_servers = raw.get("mcpServers", {})
    if not isinstance(raw_servers, dict):
        warnings.append("mcpServers must be an object.")
        return MCPConfig(servers=(), max_mcp_output_chars=max_chars, warnings=tuple(warnings))

    servers: list[MCPServerConfig] = []
    sanitized_server_names: set[str] = set()
    for name, value in raw_servers.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            warnings.append("MCP server entries must be object values with string names.")
            continue
        try:
            sanitized_name = sanitize_mcp_name(name)
        except ValueError as exc:
            warnings.append(f"MCP server '{name}' was skipped: {exc}")
            continue
        if sanitized_name in sanitized_server_names:
            warnings.append(f"MCP server '{name}' sanitized name '{sanitized_name}' conflicts and was skipped.")
            continue
        server = _parse_server(name, value, root, env or {}, warnings)
        if server is not None:
            sanitized_server_names.add(sanitized_name)
            servers.append(server)

    return MCPConfig(servers=tuple(servers), max_mcp_output_chars=max_chars, warnings=tuple(warnings))


def _parse_server(
    name: str,
    raw: dict,
    project_root: Path,
    env: Mapping[str, str],
    warnings: list[str],
) -> MCPServerConfig | None:
    server_type = str(raw.get("type", "stdio")).strip() or "stdio"
    if server_type != "stdio":
        warnings.append(f"MCP server '{name}' has unsupported type '{server_type}' and was skipped.")
        return None

    command = raw.get("command")
    if not isinstance(command, str) or not command.strip():
        warnings.append(f"MCP server '{name}' requires a non-empty command.")
        return None

    args = _string_list(raw.get("args", []), f"MCP server '{name}' args", warnings)
    cwd_raw = raw.get("cwd", "${workspace}")
    if not isinstance(cwd_raw, str):
        warnings.append(f"MCP server '{name}' cwd must be a string; using workspace.")
        cwd_raw = "${workspace}"
    cwd = _resolve_server_cwd(_expand_vars(cwd_raw, project_root, env, warnings, name), project_root)

    server_env: dict[str, str] = {}
    raw_env = raw.get("env", {})
    if not isinstance(raw_env, dict):
        warnings.append(f"MCP server '{name}' env must be an object and was ignored.")
    else:
        for key, value in raw_env.items():
            if not isinstance(key, str) or not isinstance(value, str):
                warnings.append(f"MCP server '{name}' env must contain only string keys and values.")
                continue
            server_env[key] = _expand_vars(value, project_root, env, warnings, name)

    return MCPServerConfig(
        name=name,
        type=server_type,
        command=_expand_vars(command, project_root, env, warnings, name),
        args=tuple(_expand_vars(arg, project_root, env, warnings, name) for arg in args),
        cwd=cwd,
        env=server_env,
        enabled=bool(raw.get("enabled", True)),
        tool_allowlist=tuple(_string_list(raw.get("tool_allowlist", []), f"MCP server '{name}' tool_allowlist", warnings)),
        tool_blocklist=tuple(_string_list(raw.get("tool_blocklist", []), f"MCP server '{name}' tool_blocklist", warnings)),
        read_only_tools=tuple(_string_list(raw.get("read_only_tools", []), f"MCP server '{name}' read_only_tools", warnings)),
    )


def _positive_int(value: object, default: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return default


def _string_list(value: object, label: str, warnings: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        warnings.append(f"{label} must be a string array.")
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        else:
            warnings.append(f"{label} must contain only strings.")
    return result


def _resolve_server_cwd(value: str, project_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _expand_vars(value: str, project_root: Path, env: Mapping[str, str], warnings: list[str], server_name: str) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "workspace":
            return str(project_root)
        if key in env:
            return str(env[key])
        warnings.append(f"MCP server '{server_name}' references missing environment variable '{key}'.")
        return ""

    return _VAR_RE.sub(replace, value)
