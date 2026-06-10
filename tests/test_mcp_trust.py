from __future__ import annotations

from pathlib import Path

import xcode_cli.paths as xcode_paths
from xcode_cli.mcp.config import MCPServerConfig
from xcode_cli.mcp.trust import MCPTrustStore, compute_server_fingerprint, default_mcp_trust_path


def _server(**overrides) -> MCPServerConfig:
    values = {
        "name": "filesystem",
        "type": "stdio",
        "command": "python",
        "args": ("server.py",),
        "cwd": Path("D:/Xcode").resolve(),
        "env": {"TOKEN": "one"},
    }
    values.update(overrides)
    return MCPServerConfig(**values)


def test_fingerprint_uses_env_keys_not_values() -> None:
    first = compute_server_fingerprint("D--Xcode", _server(env={"TOKEN": "one"}))
    changed_value = compute_server_fingerprint("D--Xcode", _server(env={"TOKEN": "two"}))
    changed_key = compute_server_fingerprint("D--Xcode", _server(env={"OTHER": "two"}))

    assert first == changed_value
    assert first != changed_key


def test_fingerprint_changes_for_command_args_and_cwd() -> None:
    base = compute_server_fingerprint("D--Xcode", _server())

    assert base != compute_server_fingerprint("D--Xcode", _server(command="node"))
    assert base != compute_server_fingerprint("D--Xcode", _server(args=("other.py",)))
    assert base != compute_server_fingerprint("D--Xcode", _server(cwd=Path("C:/tmp").resolve()))


def test_default_trust_store_path_uses_xcode_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(xcode_paths, "XCODE_DIR", tmp_path / ".xcode", raising=True)

    assert default_mcp_trust_path() == tmp_path / ".xcode" / "mcp_trust.json"


def test_trust_and_hash_change(tmp_path: Path) -> None:
    store = MCPTrustStore(tmp_path / "mcp_trust.json")
    server = _server()

    assert not store.is_trusted("D--Xcode", server)
    fingerprint = store.trust("D--Xcode", server)

    assert fingerprint.startswith("sha256:")
    assert store.is_trusted("D--Xcode", server)
    assert not store.is_trusted("D--Xcode", _server(command="node"))


def test_untrust_removes_project_server_record(tmp_path: Path) -> None:
    store = MCPTrustStore(tmp_path / "mcp_trust.json")
    server = _server()
    store.trust("D--Xcode", server)

    store.untrust("D--Xcode", "filesystem")

    assert not store.is_trusted("D--Xcode", server)
