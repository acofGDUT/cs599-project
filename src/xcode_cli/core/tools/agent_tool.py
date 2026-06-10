from __future__ import annotations

from xcode_cli.core.agent_types import AgentType
from xcode_cli.core.config import ConfigStore
from xcode_cli.core.llm import LLMClient
from xcode_cli.core.sub_agent import SubAgentExecutor
from xcode_cli.core.tool_registry import ToolDef


def create_dispatch_agent_tool(llm_client: LLMClient, config_store: ConfigStore) -> ToolDef:
    def dispatch_agent(agent_type: str, prompt: str) -> str:
        try:
            normalized = AgentType(agent_type.lower())
        except Exception:
            return "Error: invalid agent_type. Use one of: explore, plan, general"

        executor = SubAgentExecutor(agent_type=normalized, llm_client=llm_client, config_store=config_store)
        return executor.run(prompt)

    return ToolDef(
        name="dispatch_agent",
        description=(
            "Dispatch an independent sub-agent task. "
            "agent_type: explore|plan|general. Prompt must be self-contained."
        ),
        parameters={
            "agent_type": {
                "type": "string",
                "enum": ["explore", "plan", "general"],
                "description": "Sub-agent type.",
            },
            "prompt": {
                "type": "string",
                "description": "Self-contained task prompt for the sub-agent.",
            },
        },
        required=["agent_type", "prompt"],
        execute=dispatch_agent,
        is_read_only=False,
    )
