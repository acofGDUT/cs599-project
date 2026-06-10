from __future__ import annotations

import json
from typing import Any

from xcode_cli.core.agent_types import AgentType
from xcode_cli.core.config import ConfigStore
from xcode_cli.core.llm import LLMClient
from xcode_cli.core.prompting import BASE_SYSTEM_PROMPT
from xcode_cli.core.tool_registry import ToolRegistry
from xcode_cli.core.tools import ALL_TOOLS


def _system_prompt_for(agent_type: AgentType) -> str:
    if agent_type == AgentType.EXPLORE:
        return (
            "You are an EXPLORE sub-agent. Search and read code only. "
            "Do not modify files or run shell commands. Keep output concise."
        )
    if agent_type == AgentType.PLAN:
        return (
            "You are a PLAN sub-agent. Analyze code and produce a structured implementation plan. "
            "Read/search only; do not modify files or run shell commands."
        )
    return BASE_SYSTEM_PROMPT


class SubAgentExecutor:
    def __init__(self, agent_type: AgentType, llm_client: LLMClient, config_store: ConfigStore):
        self.agent_type = agent_type
        self.llm = llm_client
        self.config_store = config_store
        self.tools = ToolRegistry()

        read_only_tools = {"read_file", "grep", "glob"}
        for tool in ALL_TOOLS:
            if agent_type in {AgentType.EXPLORE, AgentType.PLAN}:
                if tool.name in read_only_tools:
                    self.tools.register(tool)
            else:
                self.tools.register(tool)

    def run(self, prompt: str) -> str:
        history: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        system_prompt = _system_prompt_for(self.agent_type)

        for _ in range(15):
            response = self.llm.complete(
                system_prompt=system_prompt,
                messages=history,
                tool_schemas=self.tools.get_openai_schemas(),
            )

            if not response.tool_calls:
                return response.content

            history.append(
                {
                    "role": "assistant",
                    "content": response.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                        }
                        for tc in response.tool_calls
                    ],
                }
            )

            for tc in response.tool_calls:
                result = self.tools.execute(tc.name, tc.args).content
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )

        return "Reached maximum tool call rounds."
