from __future__ import annotations

import json
from pathlib import Path

from xcode_cli.core.permissions import PermissionManager


def test_task_create_default_allow(tmp_path: Path) -> None:
    pm = PermissionManager(str(tmp_path))
    assert pm.check("task_create") == "allow"


def test_task_update_default_allow(tmp_path: Path) -> None:
    pm = PermissionManager(str(tmp_path))
    assert pm.check("task_update") == "allow"


def test_task_list_default_ask_but_read_only(tmp_path: Path) -> None:
    """task_list defaults to 'ask' in PermissionManager, but is_read_only=True bypasses approval."""
    pm = PermissionManager(str(tmp_path))
    assert pm.check("task_list") == "ask"


def test_task_deny_override(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".xcode"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"permissions": {"task_create": "deny"}}),
        encoding="utf-8",
    )
    pm = PermissionManager(str(tmp_path))
    assert pm.check("task_create") == "deny"


def test_task_update_deny_override(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".xcode"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"permissions": {"task_update": "deny"}}),
        encoding="utf-8",
    )
    pm = PermissionManager(str(tmp_path))
    assert pm.check("task_update") == "deny"


def test_task_list_is_read_only_allow(tmp_path: Path) -> None:
    """When is_read_only=True is passed, task_list defaults to allow."""
    pm = PermissionManager(str(tmp_path))
    assert pm.check("task_list", is_read_only=True) == "allow"


def test_is_read_only_deny_overrides(tmp_path: Path) -> None:
    """Explicit deny takes precedence over is_read_only=True."""
    settings_dir = tmp_path / ".xcode"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"permissions": {"task_list": "deny"}}),
        encoding="utf-8",
    )
    pm = PermissionManager(str(tmp_path))
    assert pm.check("task_list", is_read_only=True) == "deny"


def test_is_read_only_explicit_ask_overrides(tmp_path: Path) -> None:
    """Explicit ask in settings overrides is_read_only=True."""
    settings_dir = tmp_path / ".xcode"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"permissions": {"task_list": "ask"}}),
        encoding="utf-8",
    )
    pm = PermissionManager(str(tmp_path))
    assert pm.check("task_list", is_read_only=True) == "ask"
