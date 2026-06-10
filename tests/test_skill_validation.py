from pathlib import Path

from xcode_cli.skills.model import Skill
from xcode_cli.skills.validation import validate_skills


def _skill(name="review", **overrides):
    data = dict(
        name=name,
        display_name=None,
        description="Review code",
        body="Review.",
        root=Path(f"D:/Xcode/.xcode/skills/{name}"),
    )
    data.update(overrides)
    return Skill(**data)


def test_warns_when_skill_conflicts_with_builtin_command():
    notices = validate_skills([_skill("init")], builtin_commands={"/init", "/help"})

    assert any("conflicts with built-in command" in n.message for n in notices)


def test_warns_when_description_uses_fallback():
    notices = validate_skills(
        [_skill(description="Review.", raw_frontmatter={})],
        builtin_commands=set(),
    )

    assert any("description missing" in n.message for n in notices)


def test_warns_for_unknown_allowed_tool():
    notices = validate_skills(
        [_skill(allowed_tools=["Read", "UnknownTool"])],
        builtin_commands=set(),
    )

    assert any("UnknownTool" in n.message for n in notices)
