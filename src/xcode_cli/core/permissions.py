from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolPermission:
    tool_name: str
    level: str  # "allow" | "deny" | "ask"


class PermissionManager:
    VALID_LEVELS = {"allow", "deny", "ask"}

    def __init__(self, cwd: str) -> None:
        self.cwd = Path(cwd)
        self.session_rules: dict[str, str] = {}

    def set_session_rule(self, tool_name: str, level: str) -> None:
        if level not in self.VALID_LEVELS:
            raise ValueError(f"Invalid permission level: {level}")
        self.session_rules[tool_name] = level

    def check(self, tool_name: str, is_read_only: bool = False) -> str:
        session_level = self.session_rules.get(tool_name)
        if session_level in self.VALID_LEVELS:
            return session_level

        project_level = self._load_project_rules().get(tool_name)
        if project_level in self.VALID_LEVELS:
            return project_level

        global_level = self._load_global_rules().get(tool_name)
        if global_level in self.VALID_LEVELS:
            return global_level

        if is_read_only:
            return "allow"

        return self._default_level(tool_name)

    def _load_project_rules(self) -> dict[str, str]:
        project_settings = self.cwd / ".xcode" / "settings.json"
        return self._read_rules(project_settings)

    def _load_global_rules(self) -> dict[str, str]:
        global_settings = Path.home() / ".xcode" / "settings.json"
        return self._read_rules(global_settings)

    def _read_rules(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        raw_rules = data.get("permissions", {})
        if not isinstance(raw_rules, dict):
            return {}

        cleaned: dict[str, str] = {}
        for k, v in raw_rules.items():
            if isinstance(k, str) and isinstance(v, str) and v in self.VALID_LEVELS:
                cleaned[k] = v
        return cleaned

    def _default_level(self, tool_name: str) -> str:
        if tool_name in {"task_create", "task_update"}:
            return "allow"
        if tool_name == "run_shell":
            return "ask"
        if tool_name in {"write_file", "edit_file"}:
            return "ask"
        if tool_name in {"read_file", "grep", "glob"}:
            return "allow"
        return "ask"
