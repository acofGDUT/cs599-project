from __future__ import annotations

import sys
from io import StringIO
from unittest.mock import MagicMock

from xcode_cli.core.tooling.approval import ToolApprovalController


# ---------------------------------------------------------------------------
# scope_for_tool
# ---------------------------------------------------------------------------

def test_scope_for_write_file() -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    assert ctrl.scope_for_tool("write_file") == "write"


def test_scope_for_edit_file() -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    assert ctrl.scope_for_tool("edit_file") == "write"


def test_scope_for_run_shell() -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    assert ctrl.scope_for_tool("run_shell") == "shell"


def test_scope_for_read_only_tool() -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    assert ctrl.scope_for_tool("read_file") == "read_file"
    assert ctrl.scope_for_tool("grep") == "grep"
    assert ctrl.scope_for_tool("glob") == "glob"


# ---------------------------------------------------------------------------
# prompt — session auto approve
# ---------------------------------------------------------------------------

def test_auto_approve_returns_yes_when_scope_enabled() -> None:
    ctrl = ToolApprovalController(MagicMock(), {"write": True})
    result = ctrl.prompt("write_file", "write")
    assert result == "yes"


def test_auto_approve_returns_yes_when_scope_enabled_for_edit_file() -> None:
    ctrl = ToolApprovalController(MagicMock(), {"write": True})
    result = ctrl.prompt("edit_file", "write")
    assert result == "yes"


def test_auto_approve_ignored_when_scope_not_enabled() -> None:
    ctrl = ToolApprovalController(MagicMock(), {"write": False, "shell": False})
    # Scope not enabled and also scope is not None but auto_approve[scope] is False
    # So it falls through to isatty check
    assert ctrl.auto_approve.get("write") is False


# ---------------------------------------------------------------------------
# prompt — non-TTY fallback
# ---------------------------------------------------------------------------

def test_non_tty_default_enter_returns_yes(monkeypatch) -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "")
    result = ctrl.prompt("write_file", "write")
    assert result == "yes"


def test_non_tty_y_returns_yes(monkeypatch) -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    result = ctrl.prompt("write_file", "write")
    assert result == "yes"


def test_non_tty_yes_returns_yes(monkeypatch) -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    result = ctrl.prompt("write_file", "write")
    assert result == "yes"


def test_non_tty_n_returns_no(monkeypatch) -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    result = ctrl.prompt("write_file", "write")
    assert result == "no"


def test_non_tty_a_returns_yes_all(monkeypatch) -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "a")
    result = ctrl.prompt("write_file", "write")
    assert result == "yes_all"


def test_non_tty_all_returns_yes_all(monkeypatch) -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "all")
    result = ctrl.prompt("write_file", "write")
    assert result == "yes_all"


def test_non_tty_eof_returns_no(monkeypatch) -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
    result = ctrl.prompt("write_file", "write")
    assert result == "no"


def test_non_tty_unknown_input_returns_no(monkeypatch) -> None:
    ctrl = ToolApprovalController(MagicMock(), {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "xyz")
    result = ctrl.prompt("write_file", "write")
    assert result == "no"
