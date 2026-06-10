from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from rich.console import Console

from xcode_cli.core.commands.dispatcher import SlashCommandDispatcher, SlashDispatchResult
from xcode_cli.core.commands.slash import SlashCommand
from xcode_cli.core.turn import UserTurnInput


def _make_console() -> Console:
    return Console(file=StringIO(), force_terminal=True, width=120)


def _captured(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


def _make_dispatcher(console: Console | None = None, **kwargs) -> SlashCommandDispatcher:
    """创建带默认 mock handler 的 dispatcher。"""
    console = console or _make_console()
    defaults = {
        "help_handler": MagicMock(),
        "context_handler": MagicMock(),
        "dashboard_handler": MagicMock(),
        "skill_handler": MagicMock(),
        "env_handler": MagicMock(),
        "plan_handler": MagicMock(),
        "memory_handler": MagicMock(),
        "resume_handler": MagicMock(),
        "compact_handler": MagicMock(),
    }
    defaults.update(kwargs)
    return SlashCommandDispatcher(console=console, **defaults)


# ------------------------------------------------------------------
# prompt command
# ------------------------------------------------------------------

class TestDispatchPromptCommand:
    def test_init_returns_prompt_with_init_prompt(self) -> None:
        """dispatch /init → kind="prompt", text=INIT_PROMPT"""
        dispatcher = _make_dispatcher()
        result = dispatcher.dispatch("/init")
        assert result.kind == "prompt"
        assert "XCODE.md" in result.text

    def test_init_with_args_returns_prompt(self) -> None:
        """dispatch /init extra args → 仍然返回 prompt"""
        dispatcher = _make_dispatcher()
        result = dispatcher.dispatch("/init some extra")
        assert result.kind == "prompt"
        assert "XCODE.md" in result.text


# ------------------------------------------------------------------
# side-effect commands
# ------------------------------------------------------------------

class TestDispatchSideEffectCommands:
    def test_help_calls_help_handler_and_returns_handled(self) -> None:
        """/help → 调用 help_handler，返回 kind="handled" """
        help_handler = MagicMock()
        dispatcher = _make_dispatcher(help_handler=help_handler)
        result = dispatcher.dispatch("/help")

        assert result.kind == "handled"
        assert result.text is None
        help_handler.assert_called_once()

    def test_skill_calls_skill_handler_with_parts(self) -> None:
        """/skill list → skill_handler(['/skill', 'list'])"""
        skill_handler = MagicMock()
        dispatcher = _make_dispatcher(skill_handler=skill_handler)
        result = dispatcher.dispatch("/skill list")

        assert result.kind == "handled"
        skill_handler.assert_called_once_with(["/skill", "list"])

    def test_context_calls_handler(self) -> None:
        """/context → 调用 context_handler"""
        handler = MagicMock()
        dispatcher = _make_dispatcher(context_handler=handler)
        result = dispatcher.dispatch("/context")
        assert result.kind == "handled"
        handler.assert_called_once()

    def test_memory_calls_handler_with_parts(self) -> None:
        """/memory auto on → memory_handler(['/memory', 'auto', 'on'])"""
        handler = MagicMock()
        dispatcher = _make_dispatcher(memory_handler=handler)
        result = dispatcher.dispatch("/memory auto on")
        assert result.kind == "handled"
        handler.assert_called_once_with(["/memory", "auto", "on"])

    def test_plan_calls_handler_with_parts(self) -> None:
        handler = MagicMock()
        dispatcher = _make_dispatcher(plan_handler=handler)
        result = dispatcher.dispatch("/plan show")
        assert result.kind == "handled"
        handler.assert_called_once_with(["/plan", "show"])

    def test_resume_calls_handler(self) -> None:
        handler = MagicMock()
        dispatcher = _make_dispatcher(resume_handler=handler)
        result = dispatcher.dispatch("/resume")
        assert result.kind == "handled"
        handler.assert_called_once()

    def test_compact_calls_handler(self) -> None:
        handler = MagicMock()
        dispatcher = _make_dispatcher(compact_handler=handler)
        result = dispatcher.dispatch("/compact")
        assert result.kind == "handled"
        handler.assert_called_once()

    def test_env_calls_handler_with_parts(self) -> None:
        handler = MagicMock()
        dispatcher = _make_dispatcher(env_handler=handler)
        result = dispatcher.dispatch("/env")
        assert result.kind == "handled"
        handler.assert_called_once_with(["/env"])

    def test_dashboard_calls_handler(self) -> None:
        handler = MagicMock()
        dispatcher = _make_dispatcher(dashboard_handler=handler)
        result = dispatcher.dispatch("/dashboard")
        assert result.kind == "handled"
        handler.assert_called_once()

    def test_qqchat_dispatch_is_side_effect_command(self) -> None:
        calls = []
        dispatcher = _make_dispatcher(qqchat_handler=lambda parts: calls.append(parts))

        result = dispatcher.dispatch("/QQchat status")

        assert result.kind == "handled"
        assert calls == [["/QQchat", "status"]]

    def test_mcp_dispatch_is_side_effect_command(self) -> None:
        calls = []
        dispatcher = _make_dispatcher(mcp_handler=lambda parts: calls.append(parts))

        result = dispatcher.dispatch("/mcp status")

        assert result.kind == "handled"
        assert calls == [["/mcp", "status"]]


# ------------------------------------------------------------------
# unknown command
# ------------------------------------------------------------------

class TestDispatchUnknownCommand:
    def test_unknown_command_returns_handled(self) -> None:
        """未知命令 → 打印错误信息，返回 kind="handled" """
        console = _make_console()
        dispatcher = _make_dispatcher(console=console)
        result = dispatcher.dispatch("/bogus")

        assert result.kind == "handled"
        assert result.text is None
        output = _captured(console)
        assert "Unknown command" in output

    def test_unknown_command_does_not_call_any_handler(self) -> None:
        """未知命令不应调用任何 handler"""
        dispatcher = _make_dispatcher()
        # 不会抛异常，说明没调用不存在的 handler
        result = dispatcher.dispatch("/nonexistent")
        assert result.kind == "handled"


# ------------------------------------------------------------------
# SlashDispatchResult 数据结构
# ------------------------------------------------------------------

class TestSlashDispatchResult:
    def test_result_defaults(self) -> None:
        r = SlashDispatchResult(kind="handled")
        assert r.kind == "handled"
        assert r.text is None

    def test_prompt_result_carries_text(self) -> None:
        r = SlashDispatchResult(kind="prompt", turn_input=UserTurnInput(display_content="/x", model_content="hello"))
        assert r.kind == "prompt"
        assert r.text == "hello"
