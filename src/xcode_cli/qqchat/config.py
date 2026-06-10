from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping


READ_ONLY_TOOLS = ["read_file", "grep", "glob", "task_list"]
PROJECT_IGNORED_SECRET_FIELDS = {"client_secret", "access_token", "authorization"}


def default_tool_scope() -> dict[str, object]:
    return {
        "visible_tools": list(READ_ONLY_TOOLS),
        "execution_allowlist": list(READ_ONLY_TOOLS),
        "remote_approval": False,
    }


@dataclass
class QQChatConfig:
    app_id: str = ""
    client_secret: str = ""
    enabled: bool = True
    enable_c2c: bool = True
    enable_group_at: bool = True
    group_allowlist: list[str] = field(default_factory=list)
    owner_openids: list[str] = field(default_factory=list)
    tool_scope: dict[str, object] = field(default_factory=default_tool_scope)
    max_reply_chars: int = 1800
    group_turn_timeout_seconds: int = 240
    c2c_turn_timeout_seconds: int = 900

    def safe_summary(self) -> dict[str, object]:
        return {
            "app_id": self.app_id or "<missing>",
            "client_secret": "<set>" if self.client_secret else "<missing>",
            "enabled": self.enabled,
            "enable_c2c": self.enable_c2c,
            "enable_group_at": self.enable_group_at,
            "group_allowlist": list(self.group_allowlist),
            "owner_openids": list(self.owner_openids),
            "tool_scope": dict(self.tool_scope),
            "max_reply_chars": self.max_reply_chars,
            "group_turn_timeout_seconds": self.group_turn_timeout_seconds,
            "c2c_turn_timeout_seconds": self.c2c_turn_timeout_seconds,
        }


def load_qqchat_config(
    *,
    project_root: str | Path,
    user_config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> QQChatConfig:
    config = QQChatConfig()
    environment = os.environ if env is None else env
    user_path = Path(user_config_path) if user_config_path is not None else Path.home() / ".xcode" / "qqchat.json"
    project_path = Path(project_root) / ".xcode" / "config.json"

    if user_path.exists():
        user_data = _read_json_object(user_path)
        _apply_config_data(config, _qqchat_section_or_self(user_data), allow_secret=True)

    if project_path.exists():
        project_data = _read_json_object(project_path)
        qqchat_data = project_data.get("qqchat", {})
        if qqchat_data is None:
            qqchat_data = {}
        if not isinstance(qqchat_data, Mapping):
            raise RuntimeError(f"Invalid QQ chat config in {project_path}: 'qqchat' must be an object")
        _apply_config_data(config, qqchat_data, allow_secret=False)

    app_id = environment.get("QQ_BOT_APP_ID")
    if app_id is not None:
        config.app_id = app_id
    client_secret = environment.get("QQ_BOT_CLIENT_SECRET")
    if client_secret is not None:
        config.client_secret = client_secret

    return config


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in QQ chat config {path}: {exc.msg}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read QQ chat config {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid QQ chat config {path}: root must be an object")
    return data


def _qqchat_section_or_self(data: Mapping[str, Any]) -> Mapping[str, Any]:
    section = data.get("qqchat")
    if section is None:
        return data
    if not isinstance(section, Mapping):
        raise RuntimeError("Invalid QQ chat user config: 'qqchat' must be an object")
    return section


def _apply_config_data(config: QQChatConfig, data: Mapping[str, Any], *, allow_secret: bool) -> None:
    config_fields = {field.name for field in fields(QQChatConfig)}
    for key, value in data.items():
        if key == "tool_scope":
            if isinstance(value, Mapping):
                config.tool_scope = _merge_tool_scope(config.tool_scope, value)
            continue
        if key in PROJECT_IGNORED_SECRET_FIELDS and not allow_secret:
            continue
        if key == "client_secret" and not allow_secret:
            continue
        if key in config_fields:
            setattr(config, key, _normalize_value(key, value))


def _merge_tool_scope(current: Mapping[str, object], data: Mapping[str, Any]) -> dict[str, object]:
    tool_scope = dict(current)
    if isinstance(data.get("visible_tools"), list):
        tool_scope["visible_tools"] = [str(item) for item in data["visible_tools"]]
    if isinstance(data.get("execution_allowlist"), list):
        tool_scope["execution_allowlist"] = [str(item) for item in data["execution_allowlist"]]
    if "remote_approval" in data:
        tool_scope["remote_approval"] = bool(data["remote_approval"])
    return tool_scope


def _normalize_value(key: str, value: Any) -> Any:
    if key in {"group_allowlist", "owner_openids"}:
        return [str(item) for item in value] if isinstance(value, list) else []
    if key in {"enabled", "enable_c2c", "enable_group_at"}:
        return bool(value)
    if key in {"max_reply_chars", "group_turn_timeout_seconds", "c2c_turn_timeout_seconds"}:
        return int(value)
    return value
