from __future__ import annotations

import hashlib
import json
from pathlib import Path

import xcode_cli.paths as xcode_paths
from xcode_cli.mcp.config import MCPServerConfig


def default_mcp_trust_path() -> Path:
    return xcode_paths.XCODE_DIR / "mcp_trust.json"


def compute_server_fingerprint(project_key: str, server: MCPServerConfig) -> str:
    payload = {
        "project_key": project_key,
        "server_name": server.name,
        "type": server.type,
        "command": server.command,
        "args": list(server.args),
        "cwd": str(server.cwd),
        "env_keys": sorted(server.env.keys()),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class MCPTrustStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_mcp_trust_path()

    def is_trusted(self, project_key: str, server: MCPServerConfig) -> bool:
        records = self._load()
        return records.get(project_key, {}).get(server.name) == compute_server_fingerprint(project_key, server)

    def trust(self, project_key: str, server: MCPServerConfig) -> str:
        records = self._load()
        fingerprint = compute_server_fingerprint(project_key, server)
        project_records = records.setdefault(project_key, {})
        project_records[server.name] = fingerprint
        self._save(records)
        return fingerprint

    def untrust(self, project_key: str, server_name: str) -> None:
        records = self._load()
        project_records = records.get(project_key)
        if project_records is not None:
            project_records.pop(server_name, None)
            if not project_records:
                records.pop(project_key, None)
        self._save(records)

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        records: dict[str, dict[str, str]] = {}
        for project_key, project_records in raw.items():
            if not isinstance(project_key, str) or not isinstance(project_records, dict):
                continue
            records[project_key] = {
                str(server_name): str(fingerprint)
                for server_name, fingerprint in project_records.items()
                if isinstance(server_name, str) and isinstance(fingerprint, str)
            }
        return records

    def _save(self, records: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
