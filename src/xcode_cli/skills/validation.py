from __future__ import annotations

from xcode_cli.skills.model import Skill, SkillLoadNotice
from xcode_cli.skills.prompt import normalize_tool_name


_KNOWN_TOOL_NAMES = {
    "read_file",
    "write_file",
    "edit_file",
    "grep",
    "glob",
    "run_shell",
    "dispatch_agent",
    "read",
    "write",
    "edit",
    "shell",
    "bash",
    "task",
}


def validate_skills(skills: list[Skill], builtin_commands: set[str]) -> list[SkillLoadNotice]:
    notices: list[SkillLoadNotice] = []
    for skill in skills:
        if f"/{skill.name}" in builtin_commands:
            notices.append(SkillLoadNotice(skill.root, f"{skill.name}: conflicts with built-in command"))
        if "description" not in skill.raw_frontmatter:
            notices.append(SkillLoadNotice(skill.root, f"{skill.name}: description missing; using body fallback"))
        for tool in skill.allowed_tools:
            normalized = normalize_tool_name(tool)
            if normalized == tool and tool.strip().lower() not in _KNOWN_TOOL_NAMES:
                notices.append(SkillLoadNotice(skill.root, f"{skill.name}: unknown allowed tool {tool}"))
        if skill.context == "fork":
            notices.append(SkillLoadNotice(skill.root, f"{skill.name}: context=fork is not supported yet"))
        if skill.hooks:
            notices.append(SkillLoadNotice(skill.root, f"{skill.name}: hooks are parsed but not executed"))
    return notices
