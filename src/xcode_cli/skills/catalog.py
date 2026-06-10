from __future__ import annotations

from xcode_cli.skills.model import Skill


class SkillCatalog:
    def __init__(self, skills: list[Skill], builtin_commands: set[str]) -> None:
        self._builtin_commands = {_command_name(name) for name in builtin_commands}
        self._skills = {_skill_key(skill.name): skill for skill in skills}

    def find(self, name: str) -> Skill | None:
        return self._skills.get(_skill_key(name))

    def user_invocable_skills(self) -> list[Skill]:
        return [
            skill
            for skill in self._sorted_skills()
            if skill.user_invocable and not self._conflicts_with_builtin(skill.name)
        ]

    def model_invocable_skills(self) -> list[Skill]:
        return [
            skill
            for skill in self._sorted_skills()
            if self.validate_model_invocation(skill.name) is None
        ]

    def validate_model_invocation(self, name: str) -> str | None:
        normalized = _skill_key(name)
        if not normalized:
            return "Error: skill name is required."
        if self._conflicts_with_builtin(normalized):
            return f"Error: '{normalized}' is a built-in command, not a skill."

        skill = self.find(normalized)
        if skill is None:
            return f"Error: skill not found: {normalized}"
        if skill.disable_model_invocation:
            return f"Error: skill '{skill.name}' has model invocation disabled."
        if (skill.context or "").strip().lower() == "fork":
            return f"Error: skill '{skill.name}' requires fork execution, which is not supported yet."
        return None

    def _sorted_skills(self) -> list[Skill]:
        return [self._skills[name] for name in sorted(self._skills)]

    def _conflicts_with_builtin(self, name: str) -> bool:
        return _command_name(name) in self._builtin_commands


def _skill_key(name: str) -> str:
    return name.strip().lower().lstrip("/")


def _command_name(name: str) -> str:
    key = _skill_key(name)
    return f"/{key}" if key else ""
