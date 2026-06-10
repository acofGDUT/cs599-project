from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from xcode_cli.skills.catalog import SkillCatalog
from xcode_cli.skills.prompt import (
    SkillPromptExpander,
    UnsupportedSkillInvocation,
    normalize_tool_name,
)


@dataclass(frozen=True)
class SkillInvocation:
    display_content: str
    model_content: str
    model_metadata: dict[str, object]
    audit_metadata: dict[str, object]


class SkillInvocationService:
    def __init__(self, catalog: SkillCatalog) -> None:
        self._catalog = catalog
        self._expander = SkillPromptExpander()

    def invoke_for_user(self, skill_name: str, args: str | None) -> SkillInvocation | str:
        return self._invoke(skill_name, args or "", source="user")

    def invoke_for_model(self, skill_name: str, args: str | None) -> SkillInvocation | str:
        error = self._catalog.validate_model_invocation(skill_name)
        if error is not None:
            return error
        return self._invoke(skill_name, args or "", source="model")

    def _invoke(
        self,
        skill_name: str,
        args: str,
        *,
        source: Literal["user", "model"],
    ) -> SkillInvocation | str:
        skill = self._catalog.find(skill_name)
        if skill is None:
            return f"Error: skill not found: {skill_name.strip().lstrip('/')}"
        try:
            expanded = self._expander.expand(skill, args)
        except UnsupportedSkillInvocation as exc:
            return f"Error: {exc}"

        audit_metadata: dict[str, object] = {
            "kind": "skill_invocation",
            "source": source,
            "skill": skill.name,
            "args": args,
        }
        if skill.source_path is not None:
            audit_metadata["source_path"] = str(skill.source_path)
        if skill.source_hash is not None:
            audit_metadata["skill_source_hash"] = skill.source_hash
        allowed_tools = [normalize_tool_name(tool) for tool in skill.allowed_tools]
        if allowed_tools:
            audit_metadata["allowed_tools"] = allowed_tools
        model_metadata = dict(audit_metadata)
        model_metadata["model_content"] = expanded.prompt

        display = f"/{skill.name}" + (f" {args}" if args else "")
        return SkillInvocation(
            display_content=display,
            model_content=expanded.prompt,
            model_metadata=model_metadata,
            audit_metadata=audit_metadata,
        )
