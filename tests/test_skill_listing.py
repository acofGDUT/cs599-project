from pathlib import Path

from xcode_cli.skills.listing import (
    DEFAULT_CHAR_BUDGET,
    MAX_LISTING_DESC_CHARS,
    SkillListingFormatter,
    skill_listing_char_budget,
)
from xcode_cli.skills.model import Skill


def _skill(name="review", **overrides):
    data = dict(
        name=name,
        display_name=None,
        description="Review code changes",
        body="FULL BODY MUST NOT APPEAR",
        root=Path(f"D:/Xcode/.xcode/skills/{name}"),
        when_to_use="Use when reviewing diffs",
        allowed_tools=["read_file", "grep"],
        argument_hint="[path]",
        paths=["src/**"],
        hooks={"pre": "echo no"},
    )
    data.update(overrides)
    return Skill(**data)


def test_char_budget_uses_one_percent_context_with_default_fallback():
    assert skill_listing_char_budget(128000) == 5120
    assert skill_listing_char_budget(0) == DEFAULT_CHAR_BUDGET


def test_listing_contains_only_name_description_and_when_to_use():
    content = SkillListingFormatter().format([_skill("review")], context_window_tokens=128000)

    assert "review" in content
    assert "Review code changes" in content
    assert "Use when reviewing diffs" in content
    assert "FULL BODY MUST NOT APPEAR" not in content
    assert "allowed_tools" not in content
    assert "argument-hint" not in content
    assert "src/**" not in content
    assert "echo no" not in content


def test_listing_truncates_long_summary_before_name_only_degradation():
    long_text = "x" * (MAX_LISTING_DESC_CHARS + 200)
    content = SkillListingFormatter().format(
        [_skill("review", description=long_text, when_to_use=long_text)],
        context_window_tokens=2000,
    )

    assert len(content) <= skill_listing_char_budget(2000)
    assert "...[truncated]" in content or "- review" in content


def test_listing_degrades_to_name_only_when_budget_is_tiny():
    skills = [_skill(f"skill-{i}", description="x" * 500, when_to_use="y" * 500) for i in range(20)]
    content = SkillListingFormatter().format(skills, context_window_tokens=100)

    assert "- skill-0" in content
    assert "Review code changes" not in content
