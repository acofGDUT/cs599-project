from __future__ import annotations

from difflib import unified_diff
import re

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table


class OutputRenderer:
    """Encapsulates Rich rendering for consistent output style."""

    CODE_BLOCK_RE = re.compile(r"```([\w+-]*)\n([\s\S]*?)```", re.MULTILINE)
    TABLE_BLOCK_RE = re.compile(
        r"(^\|.*\|\s*\n^\|(?:\s*:?-{3,}:?\s*\|)+\s*\n(?:^\|.*\|\s*\n?)*)",
        re.MULTILINE,
    )

    @staticmethod
    def _build_syntax(text: str, lexer: str, theme: str, line_numbers: bool) -> Syntax:
        try:
            return Syntax(text, lexer, theme=theme, line_numbers=line_numbers)
        except Exception:
            return Syntax(text, lexer, theme="monokai", line_numbers=line_numbers)

    @staticmethod
    def _render_markdown_with_tables(console: Console, payload: str) -> None:
        cursor = 0
        for match in OutputRenderer.TABLE_BLOCK_RE.finditer(payload):
            start, end = match.span()
            if start > cursor:
                before = payload[cursor:start]
                if before.strip():
                    console.print(Markdown(before))

            table_block = match.group(1)
            OutputRenderer._render_markdown_table(console, table_block)
            cursor = end

        if cursor < len(payload):
            tail = payload[cursor:]
            if tail.strip():
                console.print(Markdown(tail))

    @staticmethod
    def _render_markdown_table(console: Console, table_block: str) -> None:
        lines = [line.strip() for line in table_block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            console.print(Markdown(table_block))
            return

        header_cells = [c.strip() for c in lines[0].strip("|").split("|")]
        rows = lines[2:]

        table = Table(show_header=True, header_style="bold cyan")
        for h in header_cells:
            table.add_column(h or " ")

        for row in rows:
            cells = [c.strip() for c in row.strip("|").split("|")]
            if len(cells) < len(header_cells):
                cells.extend([""] * (len(header_cells) - len(cells)))
            elif len(cells) > len(header_cells):
                cells = cells[: len(header_cells)]
            table.add_row(*cells)

        console.print(table)

    @staticmethod
    def render(console: Console, text: str, syntax_theme: str = "monokai") -> None:
        """Render markdown with syntax-highlighted code blocks and GFM-style tables."""
        parts: list[tuple[str, str, str]] = []
        cursor = 0
        for match in OutputRenderer.CODE_BLOCK_RE.finditer(text):
            start, end = match.span()
            if start > cursor:
                parts.append(("markdown", "", text[cursor:start]))
            lang = (match.group(1) or "text").strip()
            code = match.group(2)
            parts.append(("code", lang, code))
            cursor = end

        if cursor < len(text):
            parts.append(("markdown", "", text[cursor:]))

        if not parts:
            parts = [("markdown", "", text)]

        for kind, lang, payload in parts:
            if kind == "markdown":
                if payload.strip():
                    OutputRenderer._render_markdown_with_tables(console, payload)
            else:
                syntax = OutputRenderer._build_syntax(
                    payload,
                    lang or "text",
                    syntax_theme,
                    line_numbers=False,
                )
                console.print(Panel(syntax, border_style="blue", title=f"code · {lang or 'text'}", title_align="left"))

    @staticmethod
    def render_diff(
        console: Console,
        old: str,
        new: str,
        file_path: str,
        syntax_theme: str = "monokai",
        line_numbers: bool = True,
    ) -> None:
        diff_lines = list(
            unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm="",
            )
        )

        if not diff_lines:
            console.print("[dim]No changes detected for diff preview.[/dim]")
            return

        syntax = OutputRenderer._build_syntax(
            "\n".join(diff_lines),
            "diff",
            syntax_theme,
            line_numbers=line_numbers,
        )
        console.print(Panel(syntax, title=f"Diff · {file_path}", border_style="cyan", title_align="left"))
