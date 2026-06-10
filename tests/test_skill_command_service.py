from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console


def _make_console() -> Console:
    return Console(file=StringIO(), force_terminal=True, width=120)


def _captured(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


def _write_skill(root: Path, name: str = "review", frontmatter: str = "description: Review code") -> None:
    skill_dir = root / ".xcode" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\nReview $ARGUMENTS", encoding="utf-8")


def test_skill_list_uses_project_skill_loader(tmp_path: Path) -> None:
    from xcode_cli.core.commands.skill import SkillCommandService
    from xcode_cli.skills.loader import SkillLoader

    _write_skill(tmp_path)
    console = _make_console()

    svc = SkillCommandService(SkillLoader(tmp_path), console)
    svc.list_project_skills()

    output = _captured(console)
    assert "review" in output
    assert "Review code" in output


def test_skill_show_prints_project_skill_details(tmp_path: Path) -> None:
    from xcode_cli.core.commands.skill import SkillCommandService
    from xcode_cli.skills.loader import SkillLoader

    _write_skill(tmp_path, frontmatter='description: Review code\nargument-hint: "[path]"')
    console = _make_console()

    svc = SkillCommandService(SkillLoader(tmp_path), console)
    svc.show_project_skill("review")

    output = _captured(console)
    assert "Skill: review" in output
    assert "Review code" in output
    assert "[path]" in output


def test_skill_validate_combines_loader_and_validation_notices(tmp_path: Path) -> None:
    from xcode_cli.core.commands.skill import SkillCommandService
    from xcode_cli.skills.loader import SkillLoader

    _write_skill(tmp_path, name="init", frontmatter="allowed-tools: UnknownTool")
    console = _make_console()

    svc = SkillCommandService(SkillLoader(tmp_path), console, builtin_commands={"/init"})
    svc.validate_project_skills()

    output = _captured(console)
    assert "description missing" in output
    assert "conflicts with built-in command" in output
    assert "UnknownTool" in output


def test_skill_run_routes_list_show_and_validate(tmp_path: Path) -> None:
    from xcode_cli.core.commands.skill import SkillCommandService
    from xcode_cli.skills.loader import SkillLoader

    _write_skill(tmp_path)
    console = _make_console()
    svc = SkillCommandService(SkillLoader(tmp_path), console)

    svc.run(["/skill", "list"])
    svc.run(["/skill", "show", "review"])
    svc.run(["/skill", "validate"])

    output = _captured(console)
    assert "review" in output
    assert "No skill validation issues." in output


def test_legacy_skill_commands_print_migration_notice(tmp_path: Path) -> None:
    from xcode_cli.core.commands.skill import SkillCommandService
    from xcode_cli.skills.loader import SkillLoader

    console = _make_console()
    svc = SkillCommandService(SkillLoader(tmp_path), console)

    svc.run(["/skill", "install", "/tmp/skill"])
    svc.run(["/skill", "enable", "review"])
    svc.run(["/skill", "disable", "review"])

    output = _captured(console)
    assert output.count("Skills are now loaded from") == 3
    assert ".xcode/skills/" in output
