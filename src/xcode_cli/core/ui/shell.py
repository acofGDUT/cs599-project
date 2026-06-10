from __future__ import annotations

import os
import time
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from xcode_cli.core.bootstrap import ensure_ripgrep_installed
from xcode_cli.core.commands.slash import COMMANDS
from xcode_cli.ui.renderer import OutputRenderer


class ShellUI:
    def __init__(
        self,
        console: Console,
        config_store,
        context,
        session_start_getter: Callable[[], float],
        tool_count_getter: Callable[[], int],
        token_getter: Callable[[], int],
        cwd: str,
        command_getter: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self.console = console
        self.config_store = config_store
        self.context = context
        self._session_start_getter = session_start_getter
        self._tool_count_getter = tool_count_getter
        self._token_getter = token_getter
        self.cwd = cwd
        self._command_getter = command_getter

    def render_welcome(self) -> None:
        ensure_ripgrep_installed()

        cfg = self.config_store.load()
        has_key = bool(cfg.api_key or os.getenv("XCODE_API_KEY") or os.getenv("OPENAI_API_KEY"))
        key_state = "ready" if has_key else "missing-key"

        self.console.print("[bold]Xcode[/bold] v0.1.0  /\\_/\\")
        self.console.print("terminal-native AI agent  (•.•)")
        self.console.print(f"[dim]API:[/dim] {key_state} | [dim]Project:[/dim] {self.cwd}")
        self.console.print("[dim]Type normally to chat · / for commands · Tab to complete[/dim]")

    def show_command_suggestions(self, commands: dict[str, str] | None = None) -> None:
        visible_commands = commands
        if visible_commands is None and self._command_getter is not None:
            visible_commands = self._command_getter()
        if visible_commands is None:
            visible_commands = COMMANDS

        table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
        table.add_column("Command", style="green")
        table.add_column("Description", style="white")
        for command, description in visible_commands.items():
            table.add_row(command, Text(description))
        self.console.print(Panel(table, title="Slash Commands", border_style="cyan"))

    def bottom_toolbar(self) -> str:
        cfg = self.config_store.load()
        model = cfg.model or os.getenv("XCODE_MODEL", "gpt-4o-mini")
        has_key = bool(cfg.api_key or os.getenv("XCODE_API_KEY") or os.getenv("OPENAI_API_KEY"))
        api = "ready" if has_key else "missing-key"
        elapsed = int(time.monotonic() - self._session_start_getter())
        minutes, seconds = divmod(elapsed, 60)
        session_str = f"{minutes}m{seconds}s" if minutes else f"{seconds}s"
        tok_k = self._token_getter() // 1000 if self._token_getter() else 0
        max_tok_k = max((cfg.max_tokens or 0) // 1000, 1)
        tool_count = self._tool_count_getter()
        return f" {model} | tokens≈{tok_k}k/{max_tok_k}k | tools:{tool_count} | session {session_str} | {api} "

    def print_user_bubble(self, text: str) -> None:
        self.console.print(f"[dim]▸ {text}[/dim]")

    def print_assistant_bubble(self, text: str) -> None:
        OutputRenderer.render(self.console, text, syntax_theme=self.config_store.load().syntax_theme)

    def render_assistant_prefix(self) -> None:
        self.console.print("[magenta]assistant[/magenta] ▸ ", end="")
