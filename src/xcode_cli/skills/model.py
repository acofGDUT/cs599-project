from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Skill:
    name: str
    display_name: str | None
    description: str
    body: str
    root: Path
    source_path: Path | None = None
    source_hash: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    argument_hint: str | None = None
    argument_names: list[str] = field(default_factory=list)
    when_to_use: str | None = None
    model: str | None = None
    effort: str | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    context: str | None = None
    agent: str | None = None
    paths: list[str] = field(default_factory=list)
    hooks: dict[str, Any] | None = None
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillLoadNotice:
    path: Path
    message: str


@dataclass(frozen=True)
class SkillLoadResult:
    skills: list[Skill]
    notices: list[SkillLoadNotice] = field(default_factory=list)
