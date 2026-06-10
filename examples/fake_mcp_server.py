from __future__ import annotations

import json
import os
import sys
from datetime import datetime


def main() -> None:
    _log("start")
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                _write_error(None, -32700, f"parse error: {exc}")
                continue
            _handle_message(message)
    finally:
        _log("stop")


def _handle_message(message: object) -> None:
    if not isinstance(message, dict):
        _write_error(None, -32600, "invalid request")
        return

    method = message.get("method")
    request_id = message.get("id")

    # Notifications do not carry an id and must not receive a response.
    if request_id is None:
        _log(f"notification {method}")
        return

    if method == "initialize":
        _write_result(
            request_id,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "xcode-fake-mcp", "version": "0.1.0"},
            },
        )
        return

    if method == "tools/list":
        _write_result(request_id, {"tools": _tools()})
        return

    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        _log(f"call {name} {json.dumps(arguments, ensure_ascii=True, sort_keys=True)}")
        _write_result(request_id, _call_tool(str(name), arguments))
        return

    _write_error(request_id, -32601, f"unknown method: {method}")


def _tools() -> list[dict[str, object]]:
    return [
        {
            "name": "echo",
            "description": "Echo text for Xcode MCP manual testing.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        {
            "name": "long_output",
            "description": "Return long text to verify Xcode MCP output truncation.",
            "inputSchema": {
                "type": "object",
                "properties": {"size": {"type": "integer"}},
                "required": [],
            },
        },
        {
            "name": "fail",
            "description": "Return an MCP error result for Xcode MCP manual testing.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    ]


def _call_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    if name == "echo":
        text = str(arguments.get("text", ""))
        return {"content": [{"type": "text", "text": f"echo: {text}"}]}
    if name == "long_output":
        size = arguments.get("size", 50000)
        if not isinstance(size, int) or size < 0:
            size = 50000
        return {"content": [{"type": "text", "text": "x" * size}]}
    if name == "fail":
        return {"isError": True, "content": [{"type": "text", "text": "fake failure"}]}
    return {"isError": True, "content": [{"type": "text", "text": f"unknown tool: {name}"}]}


def _write_result(request_id: object, result: object) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "result": result})


def _write_error(request_id: object, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _write(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _log(message: str) -> None:
    log_path = os.environ.get("FAKE_MCP_LOG")
    if not log_path:
        return
    timestamp = datetime.now().isoformat(timespec="seconds")
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {message}\n")


if __name__ == "__main__":
    main()
