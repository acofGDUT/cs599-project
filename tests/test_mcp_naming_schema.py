from __future__ import annotations

import pytest

from xcode_cli.mcp.naming import detect_tool_name_conflicts, mcp_tool_name, sanitize_mcp_name
from xcode_cli.mcp.schema import convert_input_schema


def test_mcp_tool_name_uses_claude_style_prefix() -> None:
    assert mcp_tool_name("filesystem", "read_file") == "mcp__filesystem__read_file"


def test_sanitize_replaces_invalid_characters() -> None:
    assert sanitize_mcp_name("my-server") == "my_server"
    assert sanitize_mcp_name("tool.name") == "tool_name"
    assert sanitize_mcp_name("a---b") == "a_b"


def test_empty_names_are_invalid() -> None:
    with pytest.raises(ValueError):
        sanitize_mcp_name("!!!")
    with pytest.raises(ValueError):
        mcp_tool_name("", "read")


def test_sanitized_conflicts_return_warning_and_skip() -> None:
    accepted, warnings = detect_tool_name_conflicts(
        server_name="my-server",
        tool_names=["read-file", "read_file", "write"],
        existing_names=set(),
    )

    assert accepted == {"read-file": "mcp__my_server__read_file", "write": "mcp__my_server__write"}
    assert any("read_file" in warning for warning in warnings)


def test_existing_tool_name_conflict_is_skipped() -> None:
    accepted, warnings = detect_tool_name_conflicts(
        server_name="server",
        tool_names=["tool"],
        existing_names={"mcp__server__tool"},
    )

    assert accepted == {}
    assert any("conflicts" in warning for warning in warnings)


def test_schema_missing_type_and_properties_get_defaults() -> None:
    result = convert_input_schema({"required": ["path"]})

    assert result.parameters == {}
    assert result.required == ["path"]
    assert result.warnings == ()


def test_schema_invalid_required_is_cleared_with_warning() -> None:
    result = convert_input_schema({"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path", 1]})

    assert result.parameters == {"path": {"type": "string"}}
    assert result.required == []
    assert any("required" in warning for warning in result.warnings)


def test_non_dict_schema_is_invalid() -> None:
    result = convert_input_schema("bad")

    assert result.parameters is None
    assert any("inputSchema" in warning for warning in result.warnings)
