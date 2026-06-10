from pathlib import Path

from xcode_cli.skills.catalog import SkillCatalog
from xcode_cli.skills.invocation import SkillInvocationService
from xcode_cli.skills.model import Skill


def _skill(name="review", **overrides):
    data = dict(
        name=name,
        display_name=None,
        description="Review code",
        body="Review $ARGUMENTS in ${XCODE_SKILL_DIR}",
        root=Path(f"D:/Xcode/.xcode/skills/{name}"),
        source_path=Path(f"D:/Xcode/.xcode/skills/{name}/SKILL.md"),
        source_hash="sha256:test",
        allowed_tools=["Read", "Grep"],
    )
    data.update(overrides)
    return Skill(**data)


def test_user_invocation_returns_display_and_model_metadata():
    catalog = SkillCatalog([_skill("review")], builtin_commands=set())
    service = SkillInvocationService(catalog)

    invocation = service.invoke_for_user("review", "src/foo.py")

    assert invocation.display_content == "/review src/foo.py"
    assert "Review src/foo.py" in invocation.model_content
    assert invocation.model_metadata["source"] == "user"
    assert invocation.model_metadata["skill"] == "review"
    assert invocation.model_metadata["allowed_tools"] == ["read_file", "grep"]
    assert invocation.model_metadata["model_content"] == invocation.model_content
    assert invocation.audit_metadata["source"] == "user"
    assert invocation.audit_metadata["skill"] == "review"
    assert invocation.audit_metadata["allowed_tools"] == ["read_file", "grep"]
    assert invocation.audit_metadata["source_path"].endswith("SKILL.md")
    assert invocation.audit_metadata["skill_source_hash"] == "sha256:test"
    assert "model_content" not in invocation.audit_metadata


def test_model_invocation_allows_non_user_invocable_skill():
    catalog = SkillCatalog([_skill("internal", user_invocable=False)], builtin_commands=set())
    service = SkillInvocationService(catalog)

    invocation = service.invoke_for_model("internal", None)

    assert invocation.audit_metadata["source"] == "model"
    assert invocation.audit_metadata["skill"] == "internal"
    assert "model_content" not in invocation.audit_metadata


def test_model_invocation_returns_error_for_disabled_skill():
    catalog = SkillCatalog([_skill("manual-only", disable_model_invocation=True)], builtin_commands=set())
    service = SkillInvocationService(catalog)

    result = service.invoke_for_model("manual-only", "")

    assert isinstance(result, str)
    assert result.startswith("Error:")
