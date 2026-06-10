from __future__ import annotations

from dataclasses import dataclass

from xcode_cli.skills.model import Skill


class UnsupportedSkillInvocation(Exception):
    pass


@dataclass(frozen=True)
class ExpandedSkillPrompt:
    prompt: str


_TOOL_ALIASES = {
    "read": "read_file",
    "read_file": "read_file",
    "write": "write_file",
    "write_file": "write_file",
    "edit": "edit_file",
    "edit_file": "edit_file",
    "grep": "grep",
    "glob": "glob",
    "shell": "run_shell",
    "bash": "run_shell",
    "run_shell": "run_shell",
    "task": "dispatch_agent",
    "dispatch_agent": "dispatch_agent",
}


def normalize_tool_name(name: str) -> str:
    key = name.strip().lower()
    return _TOOL_ALIASES.get(key, name)


class SkillPromptExpander:
    def expand(self, skill: Skill, args: str) -> ExpandedSkillPrompt:
        if skill.context == "fork":
            raise UnsupportedSkillInvocation(
                "This skill requires fork execution, which is not supported yet."
            )

        prompt = skill.body.replace("$ARGUMENTS", args)
        prompt = prompt.replace("${XCODE_SKILL_DIR}", str(skill.root))
        return ExpandedSkillPrompt(prompt=prompt)
