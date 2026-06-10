from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from xcode_cli.core.turn import UserTurnInput, coerce_user_turn_input


DEFAULT_EXTERNAL_TOOLS = ("read_file", "grep", "glob", "task_list")
FORBIDDEN_EXTERNAL_TOOLS = {
    "write_file",
    "edit_file",
    "run_shell",
    "dispatch_agent",
    "skill",
}
SENSITIVE_METADATA_KEYS = {
    "access_token",
    "app_secret",
    "AppSecret",
    "client_secret",
    "authorization",
    "Authorization",
}


@dataclass(frozen=True)
class ExternalTurnResult:
    text: str
    session_id: str
    error: str | None = None


@dataclass(frozen=True)
class ToolScope:
    source: Literal["qqchat"]
    visible_tools: tuple[str, ...]
    execution_allowlist: tuple[str, ...]
    remote_approval: bool = False


@dataclass
class _ExternalConversationState:
    session_id: str
    history: list[dict[str, Any]] = field(default_factory=list)


def default_qqchat_tool_scope() -> ToolScope:
    return ToolScope(
        source="qqchat",
        visible_tools=DEFAULT_EXTERNAL_TOOLS,
        execution_allowlist=DEFAULT_EXTERNAL_TOOLS,
        remote_approval=False,
    )


def sanitize_tool_scope(tool_scope: ToolScope) -> ToolScope:
    execution_allowlist = tuple(
        tool for tool in tool_scope.execution_allowlist
        if tool and tool not in FORBIDDEN_EXTERNAL_TOOLS
    )
    if not execution_allowlist:
        execution_allowlist = DEFAULT_EXTERNAL_TOOLS
    executable = set(execution_allowlist)
    visible_tools = tuple(
        tool for tool in tool_scope.visible_tools
        if tool and tool not in FORBIDDEN_EXTERNAL_TOOLS and tool in executable
    )
    if not visible_tools:
        visible_tools = tuple(tool for tool in DEFAULT_EXTERNAL_TOOLS if tool in executable)
    if not visible_tools:
        visible_tools = DEFAULT_EXTERNAL_TOOLS
        execution_allowlist = DEFAULT_EXTERNAL_TOOLS
    return ToolScope(
        source=tool_scope.source,
        visible_tools=visible_tools,
        execution_allowlist=execution_allowlist,
        remote_approval=False if tool_scope.source == "qqchat" else tool_scope.remote_approval,
    )


class ExternalTurnRunner:
    def __init__(
        self,
        *,
        session_store,
        run_llm_loop: Callable[..., str],
        build_system_prompt: Callable[[], str],
        default_tool_scope: ToolScope | None = None,
    ) -> None:
        self._session_store = session_store
        self._run_llm_loop = run_llm_loop
        self._build_system_prompt = build_system_prompt
        self._default_tool_scope = sanitize_tool_scope(default_tool_scope or default_qqchat_tool_scope())
        self._conversations: dict[str, _ExternalConversationState] = {}

    def run(
        self,
        conversation_key: str,
        turn: str | UserTurnInput,
        *,
        tool_scope: ToolScope | None = None,
    ) -> ExternalTurnResult:
        state = self._state_for(conversation_key)
        user_turn = coerce_user_turn_input(turn)
        effective_tool_scope = sanitize_tool_scope(tool_scope or self._default_tool_scope)

        metadata = _clean_metadata(user_turn.metadata)
        metadata["entry_tool_scope"] = _tool_scope_metadata(effective_tool_scope)
        if user_turn.model_content != user_turn.display_content:
            metadata["model_content"] = user_turn.model_content

        self._session_store.append_message(
            state.session_id,
            {"role": "user", "content": user_turn.display_content, "metadata": metadata},
        )
        self._session_store.append_user_history(state.session_id, user_turn.display_content)
        state.history.append({"role": "user", "content": user_turn.model_content})

        final_text = self._run_llm_loop(
            history=state.history,
            system_prompt=self._build_system_prompt(),
            tool_scope=effective_tool_scope,
            session_id=state.session_id,
        )

        if _is_llm_error(final_text):
            return ExternalTurnResult(text=final_text, session_id=state.session_id, error=final_text)

        self._session_store.append_message(state.session_id, {"role": "assistant", "content": final_text})
        state.history.append({"role": "assistant", "content": final_text})
        return ExternalTurnResult(text=final_text, session_id=state.session_id)

    def _state_for(self, conversation_key: str) -> _ExternalConversationState:
        state = self._conversations.get(conversation_key)
        if state is not None:
            return state
        state = _ExternalConversationState(session_id=self._session_store.new_session_id())
        self._conversations[conversation_key] = state
        return state


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key not in SENSITIVE_METADATA_KEYS}


def _tool_scope_metadata(tool_scope: ToolScope) -> dict[str, object]:
    return {
        "source": tool_scope.source,
        "visible_tools": list(tool_scope.visible_tools),
        "execution_allowlist": list(tool_scope.execution_allowlist),
        "remote_approval": tool_scope.remote_approval,
    }


def _is_llm_error(text: str) -> bool:
    return (
        text.startswith("[v0] LLM request failed:")
        or text.startswith("[v0] Missing API key")
        or text.startswith("[v0] openai package not installed")
    )
