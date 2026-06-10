from __future__ import annotations

from xcode_cli.mcp.result import render_mcp_tool_result


def test_text_content_is_joined() -> None:
    result = render_mcp_tool_result(
        {"content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]},
        max_chars=100,
    )

    assert result == "hello\nworld"


def test_structured_content_is_serialized() -> None:
    result = render_mcp_tool_result({"structuredContent": {"ok": True}}, max_chars=100)

    assert '"ok": true' in result


def test_binary_content_is_omitted() -> None:
    result = render_mcp_tool_result(
        {"content": [{"type": "image", "mimeType": "image/png"}, {"type": "resource", "uri": "file://x"}]},
        max_chars=200,
    )

    assert "[mcp image omitted: image/png]" in result
    assert "[mcp resource omitted: file://x]" in result


def test_error_result_gets_tool_error_prefix() -> None:
    result = render_mcp_tool_result({"isError": True, "content": [{"type": "text", "text": "boom"}]}, max_chars=100)

    assert result == "Tool error: boom"


def test_output_is_truncated() -> None:
    result = render_mcp_tool_result({"content": [{"type": "text", "text": "abcdef"}]}, max_chars=3)

    assert result.startswith("abc")
    assert "[MCP output truncated: 6 -> 3 chars]" in result
