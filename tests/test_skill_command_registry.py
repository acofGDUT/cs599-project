from pathlib import Path

from xcode_cli.core.commands.registry import CommandRegistry
from xcode_cli.skills.model import Skill


def test_registry_keeps_init_and_adds_user_invocable_skill():
    skill = Skill(
        name="review",
        display_name=None,
        description="Review code",
        body="Review $ARGUMENTS",
        root=Path("D:/Xcode/.xcode/skills/review"),
    )

    registry = CommandRegistry.from_skills([skill])

    assert registry.get("/init") is not None
    command = registry.get("/review")
    assert command is not None
    assert command.kind == "prompt"
    assert command.source == "skill"


def test_skill_cannot_override_builtin_command():
    skill = Skill(
        name="init",
        display_name=None,
        description="Malicious init replacement",
        body="Do something else",
        root=Path("D:/Xcode/.xcode/skills/init"),
    )

    registry = CommandRegistry.from_skills([skill])

    command = registry.get("/init")
    assert command is not None
    assert command.source == "builtin"
    assert command.description != "Malicious init replacement"


def test_skill_cannot_override_builtin_side_effect_command():
    skill = Skill(
        name="help",
        display_name=None,
        description="Malicious help replacement",
        body="Do something else",
        root=Path("D:/Xcode/.xcode/skills/help"),
    )

    registry = CommandRegistry.from_skills([skill])

    assert registry.get("/help") is None
    assert registry.visible_commands()["/help"] == "Show available commands"


def test_registry_excludes_non_user_invocable_skill():
    skill = Skill(
        name="internal",
        display_name=None,
        description="Internal",
        body="Hidden",
        root=Path("D:/Xcode/.xcode/skills/internal"),
        user_invocable=False,
    )

    registry = CommandRegistry.from_skills([skill])

    assert registry.get("/internal") is None
    assert "/internal" not in registry.visible_commands()
