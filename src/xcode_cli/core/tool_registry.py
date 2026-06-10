from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ToolOutput:
    content: str
    metadata: dict[str, object] = field(default_factory=dict)
    audit_metadata: dict[str, object] = field(default_factory=dict)
    blocked_tools: list[str] = field(default_factory=list)


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    required: list[str]
    execute: Callable[..., str | ToolOutput]
    is_read_only: bool = True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def unregister_prefix(self, prefix: str) -> list[str]:
        removed: list[str] = []
        for name in list(self._tools.keys()):
            if name.startswith(prefix):
                self.unregister(name)
                removed.append(name)
        return removed

    def get_openai_schemas(
        self,
        blocked_tools: set[str] | list[str] | None = None,
        visible_tools: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> list[dict]:
        blocked = set(blocked_tools or [])
        visible = set(visible_tools) if visible_tools is not None else None
        schemas: list[dict] = []
        for tool in self._tools.values():
            if tool.name in blocked:
                continue
            if visible is not None and tool.name not in visible:
                continue
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": {
                            "type": "object",
                            "properties": tool.parameters,
                            "required": tool.required,
                        },
                    },
                }
            )
        return schemas

    def execute(self, name: str, args: dict) -> ToolOutput:
        tool = self._tools.get(name)
        if not tool:
            return ToolOutput(content=f"Error: unknown tool '{name}'")
        try:
            result = tool.execute(**args)
            if isinstance(result, ToolOutput):
                return result
            return ToolOutput(content=str(result))
        except Exception as exc:
            return ToolOutput(content=f"Tool error: {exc}")

    def is_read_only(self, name: str) -> bool:
        tool = self._tools.get(name)
        return tool.is_read_only if tool else False

    def list_names(self) -> list[str]:
        return list(self._tools.keys())
