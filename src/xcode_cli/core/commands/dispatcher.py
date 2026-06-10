from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.console import Console

from xcode_cli.core.commands.registry import CommandRegistry
from xcode_cli.core.turn import UserTurnInput
from xcode_cli.skills.invocation import SkillInvocation
from xcode_cli.skills.prompt import ExpandedSkillPrompt, UnsupportedSkillInvocation


@dataclass(frozen=True)
class SlashDispatchResult:
    """斜杠命令分发结果。

    kind="prompt": turn_input 是展开后的 user turn，应继续走普通 user turn。
    kind="handled": 命令已由 side-effect handler 处理完毕，应回到输入循环。
    """
    kind: str
    turn_input: UserTurnInput | None = None

    @property
    def text(self) -> str | None:
        if self.turn_input is None:
            return None
        return self.turn_input.model_content


class SlashCommandDispatcher:
    """将斜杠命令路由到对应 handler，返回统一的 dispatch result。

    不依赖 AgentRuntime；所有行为通过构造函数注入。
    """

    def __init__(
        self,
        console: Console,
        help_handler: Callable[[], None],
        context_handler: Callable[[], None],
        dashboard_handler: Callable[[], None],
        skill_handler: Callable[[list[str]], None],
        env_handler: Callable[[list[str]], None],
        plan_handler: Callable[[list[str]], None],
        memory_handler: Callable[[list[str]], None],
        resume_handler: Callable[[], None],
        compact_handler: Callable[[], None],
        qqchat_handler: Callable[[list[str]], None] | None = None,
        mcp_handler: Callable[[list[str]], None] | None = None,
        registry: CommandRegistry | None = None,
    ) -> None:
        self._console = console
        self._registry = registry or CommandRegistry.from_skills([])
        self._handlers: dict[str, Callable] = {
            "/help": lambda parts: help_handler(),
            "/context": lambda parts: context_handler(),
            "/dashboard": lambda parts: dashboard_handler(),
            "/skill": lambda parts: skill_handler(parts),
            "/env": lambda parts: env_handler(parts),
            "/plan": lambda parts: plan_handler(parts),
            "/memory": lambda parts: memory_handler(parts),
            "/resume": lambda parts: resume_handler(),
            "/compact": lambda parts: compact_handler(),
            "/qqchat": lambda parts: qqchat_handler(parts) if qqchat_handler else self._console.print("QQchat is not available."),
            "/mcp": lambda parts: mcp_handler(parts) if mcp_handler else self._console.print("MCP is not available."),
        }

    def dispatch(self, command: str) -> SlashDispatchResult:
        """分发一条斜杠命令，返回 dispatch result。

        Parameters
        ----------
        command : str
            完整的斜杠命令，如 "/help" 或 "/skill list"。
        """
        parts = command.split()
        head = parts[0].lower()

        # prompt command（如 /init）→ 展开为 prompt text，继续走普通 user turn
        prompt_cmd = self._registry.get(head)
        if prompt_cmd is not None and prompt_cmd.kind == "prompt":
            args = " ".join(parts[1:]) if len(parts) > 1 else ""
            try:
                payload = prompt_cmd.handler(args)
            except UnsupportedSkillInvocation as exc:
                self._console.print(str(exc), markup=False, highlight=False)
                return SlashDispatchResult(kind="handled")
            metadata = dict(prompt_cmd.metadata)
            if prompt_cmd.source == "skill":
                metadata["args"] = args
            if isinstance(payload, UserTurnInput):
                turn_input = payload
            elif isinstance(payload, SkillInvocation):
                turn_input = UserTurnInput(
                    display_content=payload.display_content,
                    model_content=payload.model_content,
                    metadata=payload.model_metadata,
                )
            elif isinstance(payload, ExpandedSkillPrompt):
                turn_input = UserTurnInput(
                    display_content=command,
                    model_content=payload.prompt,
                    metadata=metadata,
                )
            else:
                if isinstance(payload, str) and payload.startswith("Error:"):
                    self._console.print(payload, markup=False, highlight=False)
                    return SlashDispatchResult(kind="handled")
                turn_input = UserTurnInput(display_content=command, model_content=str(payload), metadata=metadata)
            return SlashDispatchResult(kind="prompt", turn_input=turn_input)

        # side-effect command → 调用 handler，返回 handled
        handler = self._handlers.get(head)
        if handler is not None:
            handler(parts)
            return SlashDispatchResult(kind="handled")

        # 未知命令
        self._console.print(f"Unknown command: {command}. Try /help")
        return SlashDispatchResult(kind="handled")
