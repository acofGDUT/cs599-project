from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class InstalledSkill:
    name: str
    path: Path
    description: str


class SkillManager:
    """Compatibility layer for the removed installed-skill model."""

    def install(self, source_dir: str) -> InstalledSkill:
        raise ValueError("Skills are now loaded from .xcode/skills/<name>/SKILL.md.")

    def list_installed(self) -> list[InstalledSkill]:
        return []
