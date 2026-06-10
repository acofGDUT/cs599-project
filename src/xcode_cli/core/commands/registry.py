from __future__ import annotations

from collections.abc import Iterable

from xcode_cli.core.commands.slash import COMMANDS, PROMPT_COMMANDS, SlashCommand
from xcode_cli.skills.catalog import SkillCatalog
from xcode_cli.skills.invocation import SkillInvocationService
from xcode_cli.skills.model import Skill


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    @classmethod
    def from_skills(
        cls,
        skills: list[Skill],
        invocation_service: SkillInvocationService | None = None,
    ) -> "CommandRegistry":
        registry = cls()
        registry.register_many(PROMPT_COMMANDS.values())
        service = invocation_service or SkillInvocationService(
            SkillCatalog(skills, builtin_commands=set(COMMANDS))
        )
        for skill in skills:
            if not skill.user_invocable:
                continue
            if _command_name(skill.name) in COMMANDS:
                continue
            registry.register(create_skill_slash_command(skill, service))
        return registry

    def register_many(self, commands: Iterable[SlashCommand]) -> None:
        for command in commands:
            self.register(command)

    def register(self, command: SlashCommand) -> None:
        name = _command_name(command.name)
        if name in self._commands:
            return
        self._commands[name] = command

    def get(self, command_name: str) -> SlashCommand | None:
        return self._commands.get(_command_name(command_name))

    def visible_commands(self) -> dict[str, str]:
        visible: dict[str, str] = dict(sorted(COMMANDS.items()))
        for name, cmd in sorted(self._commands.items()):
            description = cmd.description
            if cmd.argument_hint:
                description = f"{description} {cmd.argument_hint}"
            visible[name] = description
        return visible


def create_skill_slash_command(skill: Skill, service: SkillInvocationService) -> SlashCommand:
    def handler(args: str) -> object:
        return service.invoke_for_user(skill.name, args)

    metadata: dict[str, object] = {"kind": "skill_invocation", "skill": skill.name}
    if skill.source_path is not None:
        metadata["source_path"] = str(skill.source_path)
    if skill.source_hash is not None:
        metadata["skill_source_hash"] = skill.source_hash

    return SlashCommand(
        name=skill.name,
        kind="prompt",
        description=skill.description,
        handler=handler,
        source="skill",
        argument_hint=skill.argument_hint,
        metadata=metadata,
    )


def _command_name(name: str) -> str:
    normalized = name.strip().lower()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized
