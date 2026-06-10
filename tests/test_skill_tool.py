from pathlib import Path

from xcode_cli.core.tool_registry import ToolRegistry
from xcode_cli.core.tools.skill_tool import create_skill_tool
from xcode_cli.skills.catalog import SkillCatalog
from xcode_cli.skills.invocation import SkillInvocationService
from xcode_cli.skills.model import Skill


def _skill(name="review", **overrides):
    data = dict(
        name=name,
        display_name=None,
        description="Review code",
        body="Review $ARGUMENTS",
        root=Path(f"D:/Xcode/.xcode/skills/{name}"),
        source_path=Path(f"D:/Xcode/.xcode/skills/{name}/SKILL.md"),
        source_hash="sha256:test",
        allowed_tools=["read_file"],
    )
    data.update(overrides)
    return Skill(**data)


def test_skill_tool_schema_is_read_only_and_accepts_skill_args():
    tool = create_skill_tool(SkillInvocationService(SkillCatalog([_skill()], builtin_commands=set())))

    assert tool.name == "skill"
    assert tool.is_read_only is True
    assert "skill" in tool.parameters
    assert "args" in tool.parameters
    assert tool.required == ["skill"]


def test_skill_tool_returns_loaded_marker_audit_metadata_and_blocks_recursion():
    registry = ToolRegistry()
    registry.register(create_skill_tool(SkillInvocationService(SkillCatalog([_skill()], builtin_commands=set()))))

    result = registry.execute("skill", {"skill": "review", "args": "src/foo.py"})

    assert '<xcode_loaded_skill name="review" source="model">' in result.content
    assert "Review src/foo.py" in result.content
    assert result.audit_metadata["kind"] == "skill_invocation"
    assert result.audit_metadata["skill"] == "review"
    assert result.audit_metadata["allowed_tools"] == ["read_file"]
    assert result.blocked_tools == ["skill"]
    assert "model_content" not in result.audit_metadata


def test_skill_tool_rejects_disabled_model_invocation():
    registry = ToolRegistry()
    service = SkillInvocationService(
        SkillCatalog([_skill("manual-only", disable_model_invocation=True)], builtin_commands=set())
    )
    registry.register(create_skill_tool(service))

    result = registry.execute("skill", {"skill": "manual-only"})

    assert result.content.startswith("Error:")
    assert result.audit_metadata == {}
    assert result.blocked_tools == []
