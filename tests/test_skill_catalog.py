from pathlib import Path

from xcode_cli.skills.catalog import SkillCatalog
from xcode_cli.skills.model import Skill


def _skill(name="review", **overrides):
    data = dict(
        name=name,
        display_name=None,
        description="Review code",
        body="Review $ARGUMENTS",
        root=Path(f"D:/Xcode/.xcode/skills/{name}"),
    )
    data.update(overrides)
    return Skill(**data)


def test_find_accepts_plain_or_slash_name():
    catalog = SkillCatalog([_skill("review")], builtin_commands={"/help"})

    assert catalog.find("review").name == "review"
    assert catalog.find("/review").name == "review"


def test_model_invocable_does_not_require_user_invocable():
    skill = _skill("internal", user_invocable=False, disable_model_invocation=False)
    catalog = SkillCatalog([skill], builtin_commands=set())

    assert [item.name for item in catalog.model_invocable_skills()] == ["internal"]
    assert catalog.user_invocable_skills() == []


def test_model_invocable_excludes_disabled_fork_and_builtin_conflicts():
    catalog = SkillCatalog(
        [
            _skill("review"),
            _skill("manual-only", disable_model_invocation=True),
            _skill("forked", context="fork"),
            _skill("help"),
        ],
        builtin_commands={"/help"},
    )

    assert [item.name for item in catalog.model_invocable_skills()] == ["review"]


def test_validate_model_invocation_returns_clear_errors():
    catalog = SkillCatalog(
        [
            _skill("review"),
            _skill("manual-only", disable_model_invocation=True),
            _skill("forked", context="fork"),
        ],
        builtin_commands={"/compact"},
    )

    assert catalog.validate_model_invocation("").startswith("Error:")
    assert "not found" in catalog.validate_model_invocation("missing")
    assert "built-in" in catalog.validate_model_invocation("/compact")
    assert "disabled" in catalog.validate_model_invocation("manual-only")
    assert "fork" in catalog.validate_model_invocation("forked")
    assert catalog.validate_model_invocation("review") is None
