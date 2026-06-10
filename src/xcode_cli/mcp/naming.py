from __future__ import annotations

import re


VALID_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")
MULTI_UNDERSCORE_RE = re.compile(r"_+")


def sanitize_mcp_name(value: str) -> str:
    sanitized = VALID_NAME_RE.sub("_", value.strip())
    sanitized = MULTI_UNDERSCORE_RE.sub("_", sanitized).strip("_")
    if not sanitized:
        raise ValueError("MCP names must contain at least one alphanumeric or underscore character.")
    return sanitized


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    return f"mcp__{sanitize_mcp_name(server_name)}__{sanitize_mcp_name(tool_name)}"


def detect_tool_name_conflicts(
    *,
    server_name: str,
    tool_names: list[str],
    existing_names: set[str],
) -> tuple[dict[str, str], list[str]]:
    accepted: dict[str, str] = {}
    seen_registered: set[str] = set()
    warnings: list[str] = []
    for original_name in tool_names:
        try:
            registered_name = mcp_tool_name(server_name, original_name)
        except ValueError as exc:
            warnings.append(f"Skipped MCP tool '{original_name}': {exc}")
            continue
        if registered_name in existing_names or registered_name in seen_registered:
            warnings.append(f"Skipped MCP tool '{original_name}': registered name '{registered_name}' conflicts.")
            continue
        accepted[original_name] = registered_name
        seen_registered.add(registered_name)
    return accepted, warnings
