from __future__ import annotations

import os
import sys


def read_key() -> str:
    """Read a single keypress and return a normalized key name."""
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in {"\x00", "\xe0"}:
            second = msvcrt.getwch()
            if second == "H":
                return "up"
            if second == "P":
                return "down"
            return ""
        if ch == "\r":
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch.lower()

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            rest = sys.stdin.read(2)
            if rest == "[A":
                return "up"
            if rest == "[B":
                return "down"
            return "escape"
        if ch in {"\r", "\n"}:
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class ToolApprovalController:
    def __init__(self, console, auto_approve: dict[str, bool]) -> None:
        self.console = console
        self.auto_approve = auto_approve

    def scope_for_tool(self, tool_name: str) -> str | None:
        if tool_name in {"edit_file", "write_file"}:
            return "write"
        if tool_name == "run_shell":
            return "shell"
        return tool_name

    def prompt(self, tool_name: str, scope: str | None) -> str:
        if scope and self.auto_approve.get(scope):
            return "yes"

        approval_scope = scope or tool_name
        if not sys.stdin.isatty():
            try:
                value = input(f"  Apply {tool_name} for {approval_scope}? [Y]es / [n]o / [a]ll: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return "no"
            if not value or value in {"y", "yes"}:
                return "yes"
            if value in {"a", "all", "yes_all"}:
                return "yes_all"
            return "no"

        selected = 0
        try:
            self._render_options(tool_name, approval_scope, selected)
            while True:
                key = self._read_key()
                if key in {"up", "k"}:
                    selected = (selected - 1) % 3
                    self._refresh_options(tool_name, approval_scope, selected)
                elif key in {"down", "j"}:
                    selected = (selected + 1) % 3
                    self._refresh_options(tool_name, approval_scope, selected)
                elif key in {"enter", " "}:
                    self.console.print()
                    return ["yes", "no", "yes_all"][selected]
                elif key in {"y"}:
                    self.console.print()
                    return "yes"
                elif key in {"n", "escape"}:
                    self.console.print()
                    return "no"
                elif key in {"a"}:
                    self.console.print()
                    return "yes_all"
        except (EOFError, KeyboardInterrupt):
            return "no"

    def _read_key(self) -> str:
        return read_key()

    def _render_options(self, tool_name: str, scope: str, selected: int) -> None:
        options = [
            "Yes",
            "No",
            "Yes, for this conversation",
        ]
        self.console.print(f"  [bold]Apply {tool_name} for {scope}?[/bold] [dim](↑/↓, Enter)[/dim]")
        for idx, label in enumerate(options):
            prefix = ">" if idx == selected else " "
            style = "bold cyan" if idx == selected else "dim"
            self.console.print(f"  {prefix} {label}", style=style)

    def _refresh_options(self, tool_name: str, scope: str, selected: int) -> None:
        sys.stdout.write("\x1b[4A")
        for _ in range(4):
            sys.stdout.write("\x1b[2K")
            sys.stdout.write("\x1b[1B")
        sys.stdout.write("\x1b[4A")
        sys.stdout.flush()
        self._render_options(tool_name, scope, selected)
