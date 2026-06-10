from __future__ import annotations

from xcode_cli.core.tool_registry import ToolDef, ToolOutput
from xcode_cli.skills.invocation import SkillInvocation, SkillInvocationService


def create_skill_tool(service: SkillInvocationService) -> ToolDef:
    def execute(skill: str, args: str | None = None) -> ToolOutput:
        result = service.invoke_for_model(skill, args)
        if isinstance(result, str):
            return ToolOutput(content=result)
        return ToolOutput(
            content=_loaded_skill_content(result),
            audit_metadata=result.audit_metadata,
            blocked_tools=["skill"],
        )

    return ToolDef(
        name="skill",
        description=(
            "Load a project skill when it clearly matches the user's current task. "
            "Use only skill names from the Available skills listing."
        ),
        parameters={
            "skill": {
                "type": "string",
                "description": "The skill name from the Available skills listing. A leading slash is allowed.",
            },
            "args": {
                "type": "string",
                "description": "Optional arguments to pass as $ARGUMENTS.",
            },
        },
        required=["skill"],
        execute=execute,
        is_read_only=True,
    )


def _loaded_skill_content(invocation: SkillInvocation) -> str:
    name = str(invocation.audit_metadata.get("skill", ""))
    return (
        f'<xcode_loaded_skill name="{name}" source="model">\n'
        f"{invocation.model_content}\n"
        "</xcode_loaded_skill>"
    )
