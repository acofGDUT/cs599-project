from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DANGEROUS_TOOLS = {"write_file", "edit_file", "run_shell"}


@dataclass
class ToolDisplayState:
    expanded: bool = False


class ToolCallDisplay:
    def __init__(self, state: ToolDisplayState) -> None:
        self.state = state

    def render_calls(self, tool_calls: list[Any]) -> list[str]:
        if self.state.expanded:
            return self._render_expanded(tool_calls)
        return [self._render_summary(tool_calls)]

    def _render_summary(self, tool_calls: list[Any]) -> str:
        count = len(tool_calls)
        names = [tc.name for tc in tool_calls]
        summary = f"tools: {count} calls: {', '.join(names)}"
        dangerous = [name for name in names if name in DANGEROUS_TOOLS]
        if dangerous:
            summary += " [danger]"
        return summary

    def _render_expanded(self, tool_calls: list[Any]) -> list[str]:
        lines: list[str] = []
        for tc in tool_calls:
            lines.append(f"  ## tool.{tc.name}")
            for key, value in tc.args.items():
                val_str = str(value)
                if len(val_str) > 120:
                    val_str = val_str[:120] + "..."
                lines.append(f"    {key}: {val_str}")
        return lines
