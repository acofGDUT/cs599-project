from __future__ import annotations

import json
from typing import Any


def render_mcp_tool_result(result: object, *, max_chars: int) -> str:
    is_error = bool(_get(result, "isError", False))
    parts: list[str] = []

    content = _get(result, "content", None)
    if isinstance(content, list):
        for item in content:
            rendered = _render_content_item(item)
            if rendered:
                parts.append(rendered)

    structured = _get(result, "structuredContent", None)
    if structured is not None:
        try:
            parts.append(json.dumps(structured, ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError):
            parts.append(str(structured))

    if not parts:
        parts.append(str(result))

    text = "\n".join(parts)
    if is_error and not text.startswith("Tool error:"):
        text = f"Tool error: {text}"
    return _truncate(text, max_chars)


def _render_content_item(item: object) -> str:
    item_type = str(_get(item, "type", ""))
    if item_type == "text":
        return str(_get(item, "text", ""))
    if item_type in {"image", "audio"}:
        mime = str(_get(item, "mimeType", _get(item, "mime_type", "unknown")))
        return f"[mcp {item_type} omitted: {mime}]"
    if item_type == "resource":
        uri = str(_get(item, "uri", _get(_get(item, "resource", {}), "uri", "resource")))
        return f"[mcp resource omitted: {uri}]"
    if item_type:
        return f"[mcp {item_type} omitted]"
    return str(item)


def _get(value: object, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n[MCP output truncated: {len(text)} -> {max_chars} chars]"
