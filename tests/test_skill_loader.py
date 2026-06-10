from pathlib import Path

from xcode_cli.skills.loader import SkillLoader


def test_loads_skill_from_project_xcode_skills(tmp_path):
    skill_dir = tmp_path / ".xcode" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: Code Review
description: Review code changes
allowed-tools:
  - read
  - grep
argument-hint: "[path]"
arguments:
  - target
when_to_use: Use when reviewing diffs
disable-model-invocation: false
user-invocable: true
---

Review $ARGUMENTS.
""",
        encoding="utf-8",
    )

    result = SkillLoader(tmp_path).load()

    assert len(result.skills) == 1
    skill = result.skills[0]
    assert skill.name == "review"
    assert skill.display_name == "Code Review"
    assert skill.description == "Review code changes"
    assert skill.allowed_tools == ["read", "grep"]
    assert skill.argument_hint == "[path]"
    assert skill.argument_names == ["target"]
    assert skill.when_to_use == "Use when reviewing diffs"
    assert skill.disable_model_invocation is False
    assert skill.user_invocable is True
    assert "Review $ARGUMENTS." in skill.body


def test_supporting_files_are_not_loaded_into_skill_body(tmp_path):
    skill_dir = tmp_path / ".xcode" / "skills" / "review"
    refs_dir = skill_dir / "references"
    refs_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: Review code\n---\nRead ${XCODE_SKILL_DIR}/references/style.md when needed.",
        encoding="utf-8",
    )
    (refs_dir / "style.md").write_text("Large reference content", encoding="utf-8")

    result = SkillLoader(tmp_path).load()

    assert len(result.skills) == 1
    assert "Large reference content" not in result.skills[0].body
    assert "references/style.md" in result.skills[0].body


def test_description_falls_back_to_first_body_line(tmp_path):
    skill_dir = tmp_path / ".xcode" / "skills" / "explain"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Explain code clearly.\n\nMore detail.", encoding="utf-8")

    result = SkillLoader(tmp_path).load()

    assert result.skills[0].description == "Explain code clearly."


def test_invalid_frontmatter_skips_skill_and_records_notice(tmp_path):
    skill_dir = tmp_path / ".xcode" / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nallowed-tools: [\n---\nBody", encoding="utf-8")

    result = SkillLoader(tmp_path).load()

    assert result.skills == []
    assert result.notices
    assert "broken" in result.notices[0].message


def test_allowed_tools_supports_comma_separated_claude_style_names(tmp_path):
    skill_dir = tmp_path / ".xcode" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: Review code\nallowed-tools: Read, Grep, Bash\n---\nReview.",
        encoding="utf-8",
    )

    result = SkillLoader(tmp_path).load()

    assert result.skills[0].allowed_tools == ["Read", "Grep", "Bash"]
