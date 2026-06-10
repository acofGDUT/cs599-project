from __future__ import annotations

from rich.console import Console

from xcode_cli.core.commands.slash import COMMANDS
from xcode_cli.skills.loader import SkillLoader
from xcode_cli.skills.validation import validate_skills


_MIGRATION_NOTICE = "Skills are now loaded from .xcode/skills/<name>/SKILL.md."


class SkillCommandService:
    """Shared service for REPL `/skill` and CLI `xcode skill` commands."""

    def __init__(
        self,
        loader: SkillLoader,
        console: Console,
        builtin_commands: set[str] | None = None,
    ) -> None:
        self._loader = loader
        self._console = console
        self._builtin_commands = builtin_commands or set(COMMANDS)

    def run(self, parts: list[str]) -> None:
        if len(parts) == 1:
            self._console.print("/skill list | /skill show <name> | /skill validate")
            return

        action = parts[1].lower()
        if action == "list":
            self.list_project_skills()
        elif action == "show" and len(parts) >= 3:
            self.show_project_skill(" ".join(parts[2:]))
        elif action == "validate":
            self.validate_project_skills()
        elif action in {"install", "enable", "disable"}:
            self._print_migration_notice()
        else:
            self._console.print("Usage: /skill list|show <name>|validate")

    def list_project_skills(self) -> None:
        result = self._loader.load()
        if not result.skills:
            self._console.print("No project skills found.")
            return
        for skill in result.skills:
            self._console.print(f"- {skill.name} - {skill.description}", markup=False, highlight=False)

    def show_project_skill(self, name: str) -> None:
        normalized = name.strip().lstrip("/")
        result = self._loader.load()
        skill = next((item for item in result.skills if item.name == normalized), None)
        if skill is None:
            self._console.print(f"Skill not found: {normalized}")
            return

        self._console.print(f"Skill: {skill.name}", markup=False, highlight=False)
        if skill.display_name:
            self._console.print(f"Name: {skill.display_name}", markup=False, highlight=False)
        self._console.print(f"Description: {skill.description}", markup=False, highlight=False)
        if skill.argument_hint:
            self._console.print(f"Arguments: {skill.argument_hint}", markup=False, highlight=False)
        self._console.print(f"Path: {skill.root}", markup=False, highlight=False)
        self._console.print(skill.body, markup=False, highlight=False)

    def validate_project_skills(self) -> None:
        result = self._loader.load()
        notices = list(result.notices)
        notices.extend(validate_skills(result.skills, builtin_commands=self._builtin_commands))
        if not notices:
            self._console.print("No skill validation issues.")
            return
        for notice in notices:
            self._console.print(f"- {notice.path}: {notice.message}", markup=False, highlight=False)

    def list_installed(self) -> None:
        self.list_project_skills()

    def install(self, path: str) -> None:
        self._print_migration_notice()

    def enable(self, name: str) -> None:
        self._print_migration_notice()

    def disable(self, name: str) -> None:
        self._print_migration_notice()

    def _print_migration_notice(self) -> None:
        self._console.print(_MIGRATION_NOTICE, markup=False, highlight=False)
