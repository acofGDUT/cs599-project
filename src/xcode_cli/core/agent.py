from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import ANSI
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from xcode_cli.core.permissions import PermissionManager
from xcode_cli.core.commands.dispatcher import SlashCommandDispatcher
from xcode_cli.core.commands.registry import CommandRegistry
from xcode_cli.core.commands.skill import SkillCommandService
from xcode_cli.core.commands.slash import COMMANDS, SlashCompleter
from xcode_cli.core.config import ConfigStore
from xcode_cli.core.conversation.compaction import ConversationCompactor
from xcode_cli.core.conversation.resume import ResumeCommandService
from xcode_cli.core.tooling.approval import ToolApprovalController
from xcode_cli.core.tooling.display import ToolCallDisplay, ToolDisplayState
from xcode_cli.core.tooling.execution import ToolCallExecutor
from xcode_cli.core.ui.shell import ShellUI
from xcode_cli.core.ui.streaming import StreamingTurnRenderer
from xcode_cli.core.context import ContextManager
from xcode_cli.core.dashboard import Dashboard
from xcode_cli.core.external_turn import ExternalTurnRunner, ToolScope
from xcode_cli.core.llm import LLMClient, _friendly_llm_error
from xcode_cli.core.memory import MemoryManager
from xcode_cli.core.planning import PlanMode, write_plan_file
from xcode_cli.core.prompting import build_skill_listing_section, build_system_prompt
from xcode_cli.core.project_root import resolve_project_root
from xcode_cli.core.runtime_status import RuntimeStatusStore
from xcode_cli.core.session import SessionStore
from xcode_cli.core.task_tracker import TaskTracker, create_task_tools
from xcode_cli.core.tool_registry import ToolDef, ToolRegistry
from xcode_cli.core.tools import ALL_TOOLS
from xcode_cli.core.tools.agent_tool import create_dispatch_agent_tool
from xcode_cli.core.tools.skill_tool import create_skill_tool
from xcode_cli.core.turn import UserTurnInput, coerce_user_turn_input
from xcode_cli.mcp.config import MCPConfig, MCPServerConfig, load_mcp_config
from xcode_cli.mcp.connection import MCPConnectionManager
from xcode_cli.mcp.catalog import MCPCatalogTool
from xcode_cli.mcp.events import MCPEvent
from xcode_cli.mcp.state import MAX_MCP_TOOL_OUTPUT_LIMIT, MCPStateStore
from xcode_cli.mcp.tools import create_mcp_tool_defs
from xcode_cli.mcp.trust import MCPTrustStore, compute_server_fingerprint
from xcode_cli.qqchat.auth import QQAuthClient
from xcode_cli.qqchat.config import load_qqchat_config
from xcode_cli.qqchat.gateway import QQGatewayClient
from xcode_cli.qqchat.message_client import QQMessageClient
from xcode_cli.qqchat.service import QQChatService
from xcode_cli.skills.catalog import SkillCatalog
from xcode_cli.skills.invocation import SkillInvocationService
from xcode_cli.skills.listing import SkillListingFormatter
from xcode_cli.skills.loader import SkillLoader


class AgentRuntime:
    def __init__(self) -> None:
        self.console = Console()
        self.cwd = str(resolve_project_root(os.getcwd()))
        self.sessions = SessionStore(cwd=self.cwd)
        self._project_key = self.sessions.project_key()
        self.mcp_config: MCPConfig = load_mcp_config(self.cwd, env=os.environ)
        self.mcp_trust = MCPTrustStore()
        self.mcp_state_store = MCPStateStore(self._project_key)
        self.mcp_manager: MCPConnectionManager | None = None
        self._mcp_tool_catalog: list[MCPCatalogTool] = []
        self._mcp_events: list[MCPEvent] = []
        self._mcp_tool_warnings: list[str] = []
        self._runtime_status = RuntimeStatusStore()
        self.skill_loader = SkillLoader(self.cwd)
        self._skill_load_result = self.skill_loader.load()
        self._skill_catalog = SkillCatalog(self._skill_load_result.skills, builtin_commands=set(COMMANDS))
        self._skill_invocation = SkillInvocationService(self._skill_catalog)
        self._skill_listing_formatter = SkillListingFormatter()
        self._command_registry = CommandRegistry.from_skills(
            self._skill_catalog.user_invocable_skills(),
            invocation_service=self._skill_invocation,
        )
        self.config_store = ConfigStore()
        self._skill_service = SkillCommandService(self.skill_loader, self.console, builtin_commands=set(COMMANDS))
        self.llm = LLMClient()
        cfg = self.config_store.load()
        self.context = ContextManager(max_tokens=cfg.max_tokens, max_summary_chars=cfg.max_summary_chars)
        self.task_tracker = TaskTracker()
        self.memory = MemoryManager(cwd=self.cwd)
        self.permissions = PermissionManager(cwd=self.cwd)
        self.plan_mode = PlanMode()
        self._session_start = time.monotonic()
        self._tool_call_count = 0
        self._estimated_tokens = 0
        self._history: list[dict[str, Any]] = []
        self._session_id: str = ""
        self._current_blocked_tools: set[str] = set()
        self._session_auto_approve: dict[str, bool] = {"write": False, "shell": False}
        self.prompt = PromptSession(
            completer=SlashCompleter(commands=self._command_registry.visible_commands()),
            auto_suggest=AutoSuggestFromHistory(),
        )
        self.approval = ToolApprovalController(self.console, self._session_auto_approve)
        self.compactor = ConversationCompactor(self.context, self.llm, self.sessions, self.console)
        self.resume_service = ResumeCommandService(self.sessions, self.context, self.console, self.prompt)
        self.shell_ui = ShellUI(
            self.console,
            self.config_store,
            self.context,
            session_start_getter=lambda: self._session_start,
            tool_count_getter=lambda: self._tool_call_count,
            token_getter=lambda: self._estimated_tokens,
            cwd=self.cwd,
            command_getter=self._command_registry.visible_commands,
        )
        self.tools = ToolRegistry()
        for t in ALL_TOOLS:
            self.tools.register(t)
        self.tools.register(create_dispatch_agent_tool(self.llm, self.config_store))
        for task_tool in create_task_tools(self.task_tracker):
            self.tools.register(task_tool)
        for extra_tool in self._create_plan_memory_tools():
            self.tools.register(extra_tool)
        if self._skill_catalog.model_invocable_skills():
            self.tools.register(create_skill_tool(self._skill_invocation))
        self._initialize_mcp_manager()
        self._register_mcp_tools()
        self.tool_display_state = ToolDisplayState(expanded=False)
        self.tool_display = ToolCallDisplay(self.tool_display_state)
        self.tool_executor = ToolCallExecutor(
            self.console,
            self.tools,
            self.permissions,
            self.approval,
            self.memory,
            self.config_store,
            self._session_auto_approve,
            tool_display=self.tool_display,
        )
        self.qqchat_service: QQChatService | None = None
        self._qqchat_init_error: str | None = None
        try:
            self.qqchat_service = self._create_qqchat_service()
        except Exception as exc:
            self._qqchat_init_error = str(exc)
        self._dispatcher = SlashCommandDispatcher(
            console=self.console,
            help_handler=self._handle_help_command,
            context_handler=self._handle_context_command,
            dashboard_handler=lambda: Dashboard().run(),
            skill_handler=self._handle_skill_command,
            env_handler=self._handle_env_command,
            plan_handler=self._handle_plan_command,
            memory_handler=self._handle_memory_command,
            resume_handler=self._handle_resume_command,
            compact_handler=self._handle_compact_command,
            qqchat_handler=self._handle_qqchat_command,
            mcp_handler=self._handle_mcp_command,
            registry=self._command_registry,
        )

    def _create_qqchat_service(self) -> QQChatService:
        qq_config = load_qqchat_config(project_root=self.cwd)
        if not qq_config.app_id or not qq_config.client_secret:
            raise RuntimeError(
                "QQchat requires QQ_BOT_APP_ID and QQ_BOT_CLIENT_SECRET, "
                "or app_id/client_secret in ~/.xcode/qqchat.json."
            )
        auth_client = QQAuthClient(qq_config.app_id, qq_config.client_secret)
        gateway = QQGatewayClient(
            access_token_getter=auth_client.get_access_token,
            on_event=lambda payload: self.qqchat_service.handle_gateway_event(payload) if self.qqchat_service else None,
            on_status=lambda message: self.qqchat_service.handle_gateway_status(message) if self.qqchat_service else None,
        )
        runner = ExternalTurnRunner(
            session_store=self.sessions,
            run_llm_loop=self._run_external_llm_loop,
            build_system_prompt=self._build_external_system_prompt,
        )
        reply_client = QQMessageClient(access_token_getter=auth_client.get_access_token)
        return QQChatService(
            gateway=gateway,
            runner=runner,
            reply_client=reply_client,
            config=qq_config,
        )

    def _build_external_system_prompt(self) -> str:
        cfg = self.config_store.load()
        return build_system_prompt(cfg, self.cwd)

    def _run_external_llm_loop(
        self,
        *,
        history: list[dict[str, Any]],
        system_prompt: str,
        tool_scope: ToolScope,
        session_id: str | None = None,
    ) -> str:
        return self._run_llm_loop(
            history=history,
            system_prompt=system_prompt,
            tool_scope=tool_scope,
            session_id=session_id,
            render_output=False,
            update_runtime_stats=False,
            turn_blocked_tools=set(),
        )

    def run_chat(self) -> None:
        self._session_id = self.sessions.new_session_id()
        self._runtime_status.create(self._session_id, self.cwd)
        self._render_welcome()

        self._history: list[dict[str, Any]] = []

        try:
            while True:
                user_input = self.prompt.prompt(ANSI("\x1b[96myou\x1b[0m ▸ "), bottom_toolbar=self._bottom_toolbar).strip()
                if not user_input:
                    continue
                if user_input in {"/exit", "exit", "quit"}:
                    self.console.print("Goodbye.")
                    break

                if user_input == "/":
                    self._show_command_suggestions()
                    continue

                if user_input.startswith("/"):
                    prompt_turn = self._handle_slash_command(user_input)
                    if prompt_turn is None:
                        continue
                    user_input = prompt_turn

                if isinstance(user_input, str) and self.plan_mode.pending_approval and self._handle_plan_approval_input(user_input):
                    continue

                self._run_user_turn(user_input)
        finally:
            self._shutdown_mcp_manager()
            self._runtime_status.delete()

    def _render_welcome(self) -> None:
        self.shell_ui.render_welcome()

    def _show_command_suggestions(self) -> None:
        self.shell_ui.show_command_suggestions()

    def _bottom_toolbar(self) -> str:
        return self.shell_ui.bottom_toolbar()

    def _print_user_bubble(self, text: str) -> None:
        self.shell_ui.print_user_bubble(text)

    def _print_assistant_bubble(self, text: str) -> None:
        self.shell_ui.print_assistant_bubble(text)

    def _run_user_turn(self, user_input: str | UserTurnInput) -> None:
        """执行一个普通 user turn：写入 session/history → 调用 LLM → 追加 assistant 响应。"""
        turn = coerce_user_turn_input(user_input)
        self._current_blocked_tools = set()
        message = {"role": "user", "content": turn.display_content}
        metadata = dict(turn.metadata)
        if turn.model_content != turn.display_content or metadata:
            metadata["model_content"] = turn.model_content
            if "skill_source_hash" in turn.metadata:
                metadata["skill_source_hash"] = turn.metadata.get("skill_source_hash")
            message["metadata"] = metadata
        self.sessions.append_message(self._session_id, message)
        self.sessions.append_user_history(self._session_id, turn.display_content)
        self._print_user_bubble(turn.display_content)
        self._history.append({"role": "user", "content": turn.model_content})

        if self.plan_mode.is_active:
            cfg = self.config_store.load()
            system_prompt = self._append_skill_listing_to_prompt(
                self.plan_mode.get_system_prompt(),
                cfg.max_tokens,
            )
        else:
            cfg = self.config_store.load()
            system_prompt = build_system_prompt(
                cfg,
                self.cwd,
                skill_listing=self._available_skill_listing(cfg.max_tokens),
            )

        self._runtime_status.update("busy")
        try:
            final_text = self._run_llm_loop(history=self._history, system_prompt=system_prompt)
        finally:
            self._runtime_status.update("idle")

        is_llm_error = final_text.startswith("[v0] LLM request failed:")
        is_missing_key = final_text.startswith("[v0] Missing API key")
        is_missing_pkg = final_text.startswith("[v0] openai package not installed")

        if is_llm_error or is_missing_key or is_missing_pkg:
            self.console.print(f"[bold red]{final_text}[/bold red]")
            return

        self.sessions.append_message(self._session_id, {"role": "assistant", "content": final_text})
        self._history.append({"role": "assistant", "content": final_text})

        if self.plan_mode.pending_approval:
            self._show_plan_and_ask_approval()

    def _handle_help_command(self) -> None:
        self._show_command_suggestions()

    def _handle_slash_command(self, command: str) -> UserTurnInput | None:
        result = self._dispatcher.dispatch(command)
        return result.turn_input if result.kind == "prompt" else None

    def _handle_skill_command(self, parts: list[str]) -> None:
        self._skill_service.run(parts)

    def _handle_qqchat_command(self, parts: list[str]) -> None:
        action = parts[1].lower() if len(parts) > 1 else "status"
        if action not in {"start", "stop", "status"}:
            self.console.print("Usage: /QQchat start|stop|status")
            return
        if self.qqchat_service is None:
            detail = self._qqchat_init_error or "QQchat is not available."
            self.console.print(f"QQchat unavailable: {detail}", markup=False, highlight=False)
            return
        if action == "start":
            try:
                self.qqchat_service.start()
            except RuntimeError as exc:
                self.console.print(str(exc), markup=False, highlight=False)
        elif action == "stop":
            self.qqchat_service.stop()
        self._print_qqchat_status()

    def _print_qqchat_status(self) -> None:
        if self.qqchat_service is None:
            return
        status = self.qqchat_service.status()
        table = Table(title="QQchat")
        table.add_column("Key")
        table.add_column("Value")
        for key in ("state", "last_error", "handled_messages", "sent_replies"):
            table.add_row(key, str(status.get(key)))
        tool_scope = status.get("tool_scope")
        if isinstance(tool_scope, dict):
            table.add_row("visible_tools", ", ".join(str(x) for x in tool_scope.get("visible_tools", [])))
            table.add_row("execution_allowlist", ", ".join(str(x) for x in tool_scope.get("execution_allowlist", [])))
            table.add_row("remote_approval", str(tool_scope.get("remote_approval")))
        self.console.print(table)

    def _handle_mcp_command(self, parts: list[str]) -> None:
        action = parts[1].lower() if len(parts) > 1 else "status"
        if action == "status":
            self._print_mcp_status(verbose="--verbose" in parts[2:])
            return
        if action == "tools":
            self._handle_mcp_tools_command(parts)
            return
        if action == "reload":
            self._reload_mcp_servers()
            self._print_mcp_status()
            return
        if action == "enable":
            self._handle_mcp_enable_command(parts, enabled=True)
            return
        if action == "disable":
            self._handle_mcp_enable_command(parts, enabled=False)
            return
        if action == "tool":
            self._handle_mcp_tool_command(parts)
            return
        if action == "refresh":
            self._handle_mcp_refresh_command(parts)
            return
        if action == "reconnect":
            self._handle_mcp_reconnect_command(parts)
            return
        if action == "events":
            self._handle_mcp_events_command(parts)
            return
        if action == "output-limit":
            self._handle_mcp_output_limit_command(parts)
            return
        if action == "trust":
            if len(parts) < 3:
                self.console.print("Usage: /mcp trust <server>", markup=False, highlight=False)
                return
            self._trust_mcp_server(parts[2])
            return
        if action == "untrust":
            if len(parts) < 3:
                self.console.print("Usage: /mcp untrust <server>", markup=False, highlight=False)
                return
            self.mcp_trust.untrust(self._project_key, parts[2])
            self._reload_mcp_servers()
            self.console.print(f"MCP server '{parts[2]}' untrusted.")
            return
        self.console.print(_mcp_usage(), markup=False, highlight=False)

    def _print_mcp_status(self, *, verbose: bool = False) -> None:
        self._drain_mcp_refresh_events()
        table = Table(title="MCP")
        table.add_column("Server")
        table.add_column("Status")
        table.add_column("Tools")
        table.add_column("Hash")
        table.add_column("Error / warnings")

        statuses = self.mcp_manager.statuses() if self.mcp_manager is not None else []
        seen = set()
        for status in statuses:
            seen.add(status.name)
            details = []
            if status.error_summary:
                details.append(status.error_summary)
            details.extend(status.warnings)
            table.add_row(
                _table_text(status.name),
                _table_text(status.status),
                _table_text(str(status.tool_count)),
                _table_text(_short_fingerprint(status.fingerprint)),
                _table_text("\n".join(details)),
            )

        for server in self.mcp_config.servers:
            if server.name in seen:
                continue
            fingerprint = compute_server_fingerprint(self._project_key, server)
            status = "disabled" if not server.enabled else "untrusted"
            table.add_row(
                _table_text(server.name),
                _table_text(status),
                _table_text("0"),
                _table_text(_short_fingerprint(fingerprint)),
                _table_text(""),
            )

        for warning in [*self.mcp_config.warnings, *self._mcp_tool_warnings]:
            table.add_row(_table_text("(warning)"), _table_text(""), _table_text(""), _table_text(""), _table_text(warning))
        self.console.print(table)
        if verbose:
            self._print_mcp_tools_table()

    def _handle_mcp_tools_command(self, parts: list[str]) -> None:
        server_name = parts[2] if len(parts) > 2 else None
        if server_name is not None and self._find_mcp_server(server_name) is None:
            self.console.print(f"Unknown MCP server: {server_name}", markup=False, highlight=False)
            return
        self._drain_mcp_refresh_events()
        self._print_mcp_tools_table(server_name=server_name)

    def _print_mcp_tools_table(self, server_name: str | None = None) -> None:
        table = Table(title="MCP Tools")
        table.add_column("Server")
        table.add_column("Tool")
        table.add_column("Registered")
        table.add_column("State")
        table.add_column("Read-only")
        table.add_column("Output limit")
        table.add_column("Warnings")
        entries = [
            entry
            for entry in self._mcp_tool_catalog
            if server_name is None or entry.server_name == server_name
        ]
        if not entries:
            table.add_row(
                _table_text(server_name or "(all)"),
                _table_text("(none)"),
                _table_text(""),
                _table_text(""),
                _table_text(""),
                _table_text(""),
                _table_text(""),
            )
        for entry in entries:
            table.add_row(
                _table_text(entry.server_name),
                _table_text(entry.original_name),
                _table_text(entry.registered_name or ""),
                _table_text(entry.state),
                _table_text(str(entry.read_only)),
                _table_text(f"{entry.output_limit} ({entry.output_limit_source})"),
                _table_text("; ".join(entry.schema_warnings)),
            )
        self.console.print(table)

    def _handle_mcp_enable_command(self, parts: list[str], *, enabled: bool) -> None:
        if len(parts) < 3:
            verb = "enable" if enabled else "disable"
            self.console.print(f"Usage: /mcp {verb} <server>", markup=False, highlight=False)
            return
        server_name = parts[2]
        if self._find_mcp_server(server_name) is None:
            self.console.print(f"Unknown MCP server: {server_name}", markup=False, highlight=False)
            return
        self.mcp_state_store.set_server_enabled(server_name, enabled)
        self._reload_mcp_servers()
        state = "enabled" if enabled else "disabled"
        self.console.print(f"MCP server '{server_name}' {state}.", markup=False, highlight=False)

    def _handle_mcp_tool_command(self, parts: list[str]) -> None:
        if len(parts) < 5 or parts[2].lower() not in {"enable", "disable"}:
            self.console.print("Usage: /mcp tool enable|disable <server> <tool>", markup=False, highlight=False)
            return
        enabled = parts[2].lower() == "enable"
        server_name = parts[3]
        tool_name = parts[4]
        if self._find_mcp_server(server_name) is None:
            self.console.print(f"Unknown MCP server: {server_name}", markup=False, highlight=False)
            return
        entry = self._find_mcp_catalog_tool(server_name, tool_name)
        if entry is None:
            self.console.print(f"Unknown MCP tool: {server_name}.{tool_name}", markup=False, highlight=False)
            return
        if enabled and entry.state in {"disabled_by_config", "invalid_schema", "name_conflict"}:
            self.console.print(
                f"Cannot enable MCP tool '{server_name}.{tool_name}' while state is {entry.state}.",
                markup=False,
                highlight=False,
            )
            return
        self.mcp_state_store.set_tool_enabled(server_name, tool_name, enabled)
        self._rebuild_mcp_tool_registry()
        state = "enabled" if enabled else "disabled"
        self.console.print(f"MCP tool '{server_name}.{tool_name}' {state}.", markup=False, highlight=False)

    def _handle_mcp_refresh_command(self, parts: list[str]) -> None:
        if len(parts) > 2 and self._find_mcp_server(parts[2]) is None:
            self.console.print(f"Unknown MCP server: {parts[2]}", markup=False, highlight=False)
            return
        server_name = parts[2] if len(parts) > 2 else None
        targets = self._refresh_mcp_tools(server_name)
        self.console.print(self._mcp_operation_message("refresh", targets), markup=False, highlight=False)

    def _handle_mcp_reconnect_command(self, parts: list[str]) -> None:
        if len(parts) > 2 and self._find_mcp_server(parts[2]) is None:
            self.console.print(f"Unknown MCP server: {parts[2]}", markup=False, highlight=False)
            return
        server_name = parts[2] if len(parts) > 2 else None
        targets = self._reconnect_mcp_servers(server_name)
        self.console.print(self._mcp_operation_message("reconnect", targets), markup=False, highlight=False)

    def _handle_mcp_events_command(self, parts: list[str]) -> None:
        if len(parts) > 2 and self._find_mcp_server(parts[2]) is None:
            self.console.print(f"Unknown MCP server: {parts[2]}", markup=False, highlight=False)
            return
        self._collect_mcp_manager_events()
        server_name = parts[2] if len(parts) > 2 else None
        events = getattr(self, "_mcp_events", [])
        if server_name is not None:
            events = [event for event in events if event.server_name == server_name]
        if not events:
            self.console.print("No MCP events recorded.", markup=False, highlight=False)
            return
        table = Table(title="MCP Events")
        table.add_column("Time")
        table.add_column("Server")
        table.add_column("Kind")
        table.add_column("Message")
        for event in events[-100:]:
            table.add_row(
                _table_text(time.strftime("%H:%M:%S", time.localtime(event.ts))),
                _table_text(event.server_name),
                _table_text(event.kind),
                _table_text(event.message),
            )
        self.console.print(table)

    def _handle_mcp_output_limit_command(self, parts: list[str]) -> None:
        if len(parts) < 5:
            self.console.print("Usage: /mcp output-limit <server> <tool> <chars|default>", markup=False, highlight=False)
            return
        server_name, tool_name, raw_value = parts[2], parts[3], parts[4]
        if self._find_mcp_server(server_name) is None:
            self.console.print(f"Unknown MCP server: {server_name}", markup=False, highlight=False)
            return
        if self._find_mcp_catalog_tool(server_name, tool_name) is None:
            self.console.print(f"Unknown MCP tool: {server_name}.{tool_name}", markup=False, highlight=False)
            return
        value: int | None
        if raw_value.lower() == "default":
            value = None
        else:
            try:
                value = int(raw_value)
            except ValueError:
                self.console.print(_invalid_mcp_output_limit_message(), markup=False, highlight=False)
                return
        try:
            self.mcp_state_store.set_tool_output_limit(server_name, tool_name, value)
        except ValueError:
            self.console.print(_invalid_mcp_output_limit_message(), markup=False, highlight=False)
            return
        self._rebuild_mcp_tool_registry()
        label = "default" if value is None else str(value)
        self.console.print(f"MCP tool '{server_name}.{tool_name}' output limit set to {label}.", markup=False, highlight=False)

    def _trust_mcp_server(self, server_name: str) -> None:
        server = self._find_mcp_server(server_name)
        if server is None:
            self.console.print(f"Unknown MCP server: {server_name}")
            return
        fingerprint = compute_server_fingerprint(self._project_key, server)
        self.console.print(f"MCP server: {server.name}", markup=False, highlight=False)
        self.console.print(f"command: {server.command}", markup=False, highlight=False)
        self.console.print(f"args: {' '.join(server.args)}", markup=False, highlight=False)
        self.console.print(f"cwd: {server.cwd}", markup=False, highlight=False)
        self.console.print(f"env keys: {', '.join(sorted(server.env.keys())) or '(none)'}", markup=False, highlight=False)
        self.console.print(f"hash: {fingerprint}", markup=False, highlight=False)
        if _mcp_command_is_risky(server):
            self.console.print(
                "Warning: this MCP command may download or execute external code. Confirm the source is trusted.",
                markup=False,
                highlight=False,
            )
        if not self._confirm_mcp_trust(server):
            self.console.print("MCP trust cancelled.")
            return
        self.mcp_trust.trust(self._project_key, server)
        self.console.print(f"MCP server '{server.name}' trusted.")
        self._reload_mcp_servers()

    def _confirm_mcp_trust(self, server: MCPServerConfig) -> bool:
        try:
            answer = input(f"Trust MCP server '{server.name}'? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes"}

    def _find_mcp_server(self, server_name: str) -> MCPServerConfig | None:
        for server in self.mcp_config.servers:
            if server.name == server_name:
                return server
        return None

    def _find_mcp_catalog_tool(self, server_name: str, tool_name: str) -> MCPCatalogTool | None:
        for entry in self._mcp_tool_catalog:
            if entry.server_name == server_name and entry.original_name == tool_name:
                return entry
        return None

    def _reload_mcp_servers(self) -> None:
        self._shutdown_mcp_manager()
        self.mcp_config = load_mcp_config(self.cwd, env=os.environ)
        self._mcp_tool_warnings = []
        self._mcp_tool_catalog = []
        self._remove_mcp_tools()
        self._initialize_mcp_manager()
        self._register_mcp_tools()

    def _rebuild_mcp_tool_registry(self) -> None:
        self._mcp_tool_catalog = []
        self._mcp_tool_warnings = []
        self._remove_mcp_tools()
        self._register_mcp_tools()

    def _drain_mcp_refresh_events(self) -> None:
        if self.mcp_manager is None:
            return
        self._collect_mcp_manager_events()
        pending_func = getattr(self.mcp_manager, "pending_refresh_servers", None)
        pending = set(pending_func()) if callable(pending_func) else set()
        if not pending:
            return
        refresh_func = getattr(self.mcp_manager, "refresh_tools_sync", None)
        if not callable(refresh_func):
            return
        for server_name in sorted(pending):
            refresh_func(server_name)
        self._collect_mcp_manager_events()
        self._rebuild_mcp_tool_registry()

    def _refresh_mcp_tools(self, server_name: str | None = None) -> list[str]:
        if self.mcp_manager is None:
            self._rebuild_mcp_tool_registry()
            return []
        refresh_func = getattr(self.mcp_manager, "refresh_tools_sync", None)
        if not callable(refresh_func):
            self._rebuild_mcp_tool_registry()
            return []
        if server_name is not None:
            server_names = [server_name]
        else:
            server_names = [
                status.name
                for status in self.mcp_manager.statuses()
                if getattr(status, "status", "") == "connected"
            ]
        for name in server_names:
            refresh_func(name)
        self._collect_mcp_manager_events()
        self._rebuild_mcp_tool_registry()
        return server_names

    def _reconnect_mcp_servers(self, server_name: str | None = None) -> list[str]:
        if self.mcp_manager is None:
            self._reload_mcp_servers()
            return [server.name for server in self.mcp_config.servers if server_name is None or server.name == server_name]
        reconnect_func = getattr(self.mcp_manager, "reconnect_sync", None)
        if not callable(reconnect_func):
            self._reload_mcp_servers()
            return [server.name for server in self.mcp_config.servers if server_name is None or server.name == server_name]
        reconnect_func(server_name)
        self._collect_mcp_manager_events()
        self._rebuild_mcp_tool_registry()
        return [server.name for server in self.mcp_config.servers if server_name is None or server.name == server_name]

    def _mcp_operation_message(self, action: str, target_names: list[str]) -> str:
        statuses = self.mcp_manager.statuses() if self.mcp_manager is not None else []
        status_by_name = {status.name: status for status in statuses}
        problematic = {
            "failed",
            "untrusted",
            "disabled",
        }
        if any(status_by_name.get(name) is not None and status_by_name[name].status in problematic for name in target_names):
            return f"MCP {action} requested; check /mcp status."
        if action == "refresh":
            return "MCP tools refreshed."
        return "MCP servers reconnected."

    def _collect_mcp_manager_events(self) -> None:
        drain_func = getattr(self.mcp_manager, "drain_events", None) if self.mcp_manager is not None else None
        if not callable(drain_func):
            return
        if not hasattr(self, "_mcp_events"):
            self._mcp_events = []
        self._mcp_events.extend(drain_func())

    def _initialize_mcp_manager(self) -> None:
        if not self.mcp_config.servers:
            self.mcp_manager = None
            return
        try:
            effective_config = self._effective_mcp_config()
            self.mcp_manager = MCPConnectionManager(
                config=effective_config,
                trust_store=self.mcp_trust,
                project_key=self._project_key,
            )
            self.mcp_manager.start_trusted_servers()
        except Exception as exc:
            self.mcp_manager = None
            self._mcp_tool_warnings.append(f"MCP initialization failed: {exc}")

    def _register_mcp_tools(self) -> None:
        if self.mcp_manager is None:
            return
        project_state = self.mcp_state_store.load()
        self._mcp_tool_warnings.extend(project_state.warnings)
        tool_defs, warnings, catalog = create_mcp_tool_defs(
            connection_manager=self.mcp_manager,
            config=self.mcp_config,
            project_state=project_state,
            existing_names=set(self.tools.list_names()),
        )
        self._mcp_tool_warnings.extend(warnings)
        self._mcp_tool_catalog = catalog
        for tool in tool_defs:
            self.tools.register(tool)

    def _remove_mcp_tools(self) -> None:
        self.tools.unregister_prefix("mcp__")

    def _effective_mcp_config(self) -> MCPConfig:
        state = self.mcp_state_store.load()
        servers = []
        for server in self.mcp_config.servers:
            server_state = state.servers.get(server.name)
            enabled = server.enabled and not (server_state is not None and server_state.enabled is False)
            servers.append(replace(server, enabled=enabled))
        return replace(self.mcp_config, servers=tuple(servers))

    def _shutdown_mcp_manager(self) -> None:
        if self.mcp_manager is None:
            return
        try:
            self.mcp_manager.shutdown()
        except Exception as exc:
            self.console.print(f"MCP shutdown warning: {exc}", markup=False, highlight=False)
        finally:
            self.mcp_manager = None

    def _handle_env_command(self, parts: list[str]) -> None:
        from xcode_cli.core.ui.env_dashboard import EnvDashboard
        dashboard = EnvDashboard(self.config_store, self.console)
        dashboard.run()
        # 仪表盘退出后，同步关键字段到运行中的 ContextManager
        cfg = self.config_store.load()
        self.context.max_tokens = cfg.max_tokens
        self.context.max_summary_chars = cfg.max_summary_chars

    def _create_plan_memory_tools(self) -> list[ToolDef]:
        def write_plan(content: str) -> str:
            path = write_plan_file(content)
            self.plan_mode.plan_path = path
            return f"Plan written to: {path}"

        def exit_plan_mode(plan_summary: str) -> str:
            if not self.plan_mode.is_active:
                return "Error: not in planning mode"
            return self.plan_mode.exit(plan_summary)

        return [
            ToolDef(
                name="write_plan",
                description="Write plan markdown content to ~/.xcode/plans and return path.",
                parameters={"content": {"type": "string", "description": "Full plan markdown content."}},
                required=["content"],
                execute=write_plan,
                is_read_only=False,
            ),
            ToolDef(
                name="exit_plan_mode",
                description="Finish planning and request user approval.",
                parameters={"plan_summary": {"type": "string", "description": "Short summary of the plan."}},
                required=["plan_summary"],
                execute=exit_plan_mode,
                is_read_only=True,
            ),
        ]

    def _handle_memory_command(self, parts: list[str]) -> None:
        cfg = self.config_store.load()
        if len(parts) == 1:
            auto_state = "on" if cfg.auto_memory else "off"
            project_path = self.memory.project_memory_path()
            user_path = self.memory.user_memory_path()
            project_state = "exists" if self.memory.has_project_memory() else "missing"
            user_state = "exists" if self.memory.has_user_memory() else "missing"

            self.console.print(f"Auto-memory: {auto_state}")
            self.console.print(f"Project memory: {project_path} ({project_state})")
            self.console.print(f"User memory: {user_path} ({user_state})")
            memory_files = list(self.memory.memory_dir_path().glob("*.md"))
            memory_index = self.memory.read_memory_index()
            index_entries = memory_index.count("\n") + 1 if memory_index else 0
            self.console.print(f"Memory dir: {self.memory.memory_dir_path()}")
            self.console.print(f"Memory files: {len(memory_files)} (index: {index_entries} entries)")
            return

        if len(parts) == 3 and parts[1].lower() == "auto" and parts[2].lower() in {"on", "off"}:
            value = parts[2].lower() == "on"
            cfg.auto_memory = value
            self.config_store.save(cfg)
            self.console.print(f"Auto-memory set to {'on' if value else 'off'}")
            return

        self.console.print("Usage: /memory | /memory auto on|off")

    def _handle_resume_command(self) -> None:
        result = self.resume_service.run()
        if result is not None:
            self._history[:] = result.history
            self._session_id = result.session_id
            self._runtime_status.update_session_id(result.session_id)

    def _find_previous_summary(self, history: list[dict[str, Any]]) -> str:
        return self.compactor.find_previous_summary(history)

    def _handle_compact_command(self) -> None:
        if len(self._history) < 4:
            self.console.print("Nothing to compact.")
            return

        outcome = self.compactor.compact_history(self._history)
        if outcome is None:
            self.console.print("Nothing to compact.")
            return

        self._history[:] = outcome.messages
        saved_tokens = max(outcome.before_tokens - outcome.after_tokens, 0)

        self.compactor.write_checkpoint(self._session_id, outcome)

        self.console.print(
            f"[dim]Context compacted: {outcome.before_messages} -> {outcome.after_messages} messages, "
            f"saved ~{saved_tokens} tokens.[/dim]"
        )

    def _handle_plan_command(self, parts: list[str]) -> None:
        if len(parts) == 1:
            self.console.print("/plan enter | /plan show | /plan approve | /plan reject")
            return
        action = parts[1].lower()
        if action == "enter":
            msg = self.plan_mode.enter()
            self.console.print(msg)
            return
        if action == "show":
            if not self.plan_mode.plan_path:
                self.console.print("当前还没有计划文件。")
                return
            self.console.print(f"当前计划文件: {self.plan_mode.plan_path}")
            return
        if action == "approve":
            self.console.print(self.plan_mode.approve())
            return
        if action == "reject":
            self.console.print(self.plan_mode.reject())
            return
        self.console.print("Usage: /plan enter|show|approve|reject")

    def _show_plan_and_ask_approval(self) -> None:
        summary = self.plan_mode.plan_summary or "(无摘要)"
        self.console.print("\n[bold cyan]计划已生成，等待审批[/bold cyan]")
        if self.plan_mode.plan_path:
            self.console.print(f"计划文件: {self.plan_mode.plan_path}")
        self.console.print(f"摘要: {summary}")
        self.console.print("可先编辑计划文件后再确认，或直接输入：approve / reject")

    def _handle_plan_approval_input(self, user_input: str) -> bool:
        normalized = user_input.strip().lower()
        approve_set = {"approve", "同意", "批准", "通过", "/plan approve"}
        reject_set = {"reject", "拒绝", "驳回", "/plan reject"}

        if normalized in approve_set:
            self.console.print(self.plan_mode.approve())
            return True
        if normalized in reject_set:
            self.console.print(self.plan_mode.reject())
            return True
        return False

    def _current_system_prompt(self) -> str:
        if self.plan_mode.is_active:
            cfg = self.config_store.load()
            return self._append_skill_listing_to_prompt(
                self.plan_mode.get_system_prompt(),
                cfg.max_tokens,
            )
        cfg = self.config_store.load()
        return build_system_prompt(
            cfg,
            self.cwd,
            skill_listing=self._available_skill_listing(cfg.max_tokens),
        )

    def _available_skill_listing(self, context_window_tokens: int | None) -> str:
        model_skills = self._skill_catalog.model_invocable_skills()
        if not model_skills:
            return ""
        return self._skill_listing_formatter.format(
            model_skills,
            context_window_tokens=context_window_tokens,
        )

    def _append_skill_listing_to_prompt(self, system_prompt: str, context_window_tokens: int | None) -> str:
        skill_section = build_skill_listing_section(self._available_skill_listing(context_window_tokens))
        if not skill_section:
            return system_prompt
        return "\n".join([system_prompt, skill_section])

    def _handle_context_command(self) -> None:
        cfg = self.config_store.load()
        system_prompt = self._current_system_prompt()
        system_message = {"role": "system", "content": system_prompt}
        system_tokens = self.context.estimate_tokens([system_message])
        role_groups: dict[str, list[dict[str, Any]]] = {
            "user": [],
            "assistant": [],
            "tool": [],
            "system": [],
            "other": [],
        }
        for message in self._history:
            role = str(message.get("role", "other"))
            if role not in role_groups:
                role = "other"
            role_groups[role].append(message)

        role_tokens = {role: self.context.estimate_tokens(messages) for role, messages in role_groups.items()}
        history_tokens = sum(role_tokens.values())
        total_tokens = system_tokens + history_tokens
        max_tokens = self.context.max_tokens
        remaining_tokens = max(max_tokens - total_tokens, 0)
        compression_threshold = int(self.context.max_tokens * 0.8)

        table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
        table.add_column("Item", style="green")
        table.add_column("Value", style="white")
        table.add_row("model", cfg.model or os.getenv("XCODE_MODEL", "gpt-4o-mini"))
        table.add_row("max tokens", str(max_tokens))
        table.add_row("render mode", cfg.response_render_mode)
        table.add_row("syntax theme", cfg.syntax_theme)
        table.add_row("messages", str(len(self._history)))
        table.add_row("system prompt", f"~{system_tokens} tokens")
        table.add_row("user", f"{len(role_groups['user'])} msg / ~{role_tokens['user']} tokens")
        table.add_row("assistant", f"{len(role_groups['assistant'])} msg / ~{role_tokens['assistant']} tokens")
        table.add_row("tool", f"{len(role_groups['tool'])} msg / ~{role_tokens['tool']} tokens")
        if role_groups["system"]:
            table.add_row("history system", f"{len(role_groups['system'])} msg / ~{role_tokens['system']} tokens")
        if role_groups["other"]:
            table.add_row("other", f"{len(role_groups['other'])} msg / ~{role_tokens['other']} tokens")
        table.add_row("chat history", f"~{history_tokens} tokens")
        table.add_row("total", f"~{total_tokens} / {max_tokens}")
        table.add_row("free", f"~{remaining_tokens}")
        table.add_row("compression threshold", f"~{compression_threshold}")
        table.add_row("auto-memory", "on" if cfg.auto_memory else "off")
        self.console.print(Panel(table, title="Context", border_style="cyan"))

    def _render_assistant_prefix(self) -> None:
        self.shell_ui.render_assistant_prefix()

    def _render_task_panel(self, tool_calls: list) -> None:
        has_task_tool = any(tc.name in {"task_create", "task_update"} for tc in tool_calls)
        if not has_task_tool:
            return

        tasks = self.task_tracker.list_all()
        visible = [t for t in tasks if t.status != "deleted"]
        if not visible:
            return

        status_icons = {
            "pending": "◻",
            "in_progress": "◐",
            "completed": "✓",
        }

        lines = ["[bold cyan]Tasks[/bold cyan]"]
        for task in visible:
            icon = status_icons.get(task.status, "?")
            if task.status == "completed":
                color = "green"
            elif task.status == "in_progress":
                color = "yellow"
            else:
                color = "dim"
            lines.append(f"  [{color}]{icon} {task.subject}[/{color}]")

        self.console.print()
        self.console.print("\n".join(lines))

    def _run_llm_loop(
        self,
        history: list[dict[str, Any]],
        system_prompt: str,
        tool_scope: ToolScope | None = None,
        session_id: str | None = None,
        render_output: bool = True,
        update_runtime_stats: bool = True,
        turn_blocked_tools: set[str] | None = None,
    ) -> str:
        cfg = self.config_store.load()
        render_mode = cfg.response_render_mode
        assistant_turn_started = False
        transcript_session_id = self._session_id if session_id is None else session_id
        active_blocked_tools = self._current_blocked_tools if turn_blocked_tools is None else turn_blocked_tools

        renderer = (
            StreamingTurnRenderer(
                self.console,
                render_mode=render_mode,
                render_markdown=lambda text: self._print_assistant_bubble(text),
            )
            if render_output
            else None
        )

        while True:
            if self.context.should_compress(history):
                outcome = self.compactor.compact_history(history)
                if outcome is not None:
                    before_messages = outcome.before_messages
                    after_messages = outcome.after_messages
                    history[:] = outcome.messages
                    saved_tokens = max(outcome.before_tokens - outcome.after_tokens, 0)
                    if render_output:
                        self.console.print(
                            f"[dim]Context compressed: {before_messages} -> {after_messages} messages, "
                            f"saved ~{saved_tokens} tokens.[/dim]"
                        )
                    if transcript_session_id:
                        self.compactor.write_checkpoint(transcript_session_id, outcome)

            content_buffer: list[str] = []
            reasoning_buffer: list[str] = []
            start_time = time.monotonic()
            first_text_token_elapsed_ms: float | None = None
            assistant_prefix_printed = False

            thinking_stop = threading.Event()
            thinking_thread: threading.Thread | None = None
            thinking_live = Live(
                Text("Thinking (0.0s)...", style="dim"),
                console=self.console,
                refresh_per_second=8,
                transient=True,
            )
            thinking_stopped = False

            def thinking_loop() -> None:
                while not thinking_stop.is_set():
                    elapsed = time.monotonic() - start_time
                    thinking_live.update(Text(f"Thinking ({elapsed:.1f}s)...", style="dim"))
                    time.sleep(0.1)

            def stop_thinking() -> None:
                nonlocal thinking_stopped
                if thinking_stopped:
                    return
                thinking_stopped = True
                thinking_stop.set()
                if thinking_thread is not None:
                    thinking_thread.join(timeout=0.2)
                if render_output:
                    thinking_live.stop()

            def on_token(token: str) -> None:
                nonlocal first_text_token_elapsed_ms, assistant_prefix_printed, assistant_turn_started
                if first_text_token_elapsed_ms is None:
                    elapsed = time.monotonic() - start_time
                    first_text_token_elapsed_ms = elapsed * 1000
                    stop_thinking()
                content_buffer.append(token)
                if not render_output:
                    return
                if not assistant_prefix_printed:
                    if not assistant_turn_started:
                        self._render_assistant_prefix()
                        assistant_turn_started = True
                    assistant_prefix_printed = True
                if renderer is not None:
                    renderer.on_text_token(token)

            def on_reasoning_token(token: str) -> None:
                reasoning_buffer.append(token)
                if render_output and renderer is not None:
                    renderer.on_reasoning_token(token)

            if render_output:
                thinking_live.start()
                thinking_thread = threading.Thread(target=thinking_loop, daemon=True)
                thinking_thread.start()

            try:
                self._drain_mcp_refresh_events()
                response = self.llm.complete(
                    system_prompt=system_prompt,
                    messages=history,
                    tool_schemas=self.tools.get_openai_schemas(
                        blocked_tools=active_blocked_tools,
                        visible_tools=tool_scope.visible_tools if tool_scope is not None else None,
                    ),
                    on_text_token=on_token,
                    on_reasoning_token=on_reasoning_token,
                )
            except KeyboardInterrupt:
                stop_thinking()
                if render_output:
                    self.console.print("[dim]Interrupted.[/dim]")
                return "Interrupted."
            except Exception as exc:
                stop_thinking()
                friendly = _friendly_llm_error(exc)
                return f"[v0] LLM request failed: {friendly}"
            finally:
                stop_thinking()
            if update_runtime_stats:
                self._estimated_tokens = self.context.estimate_tokens(history)

            total_ms = (time.monotonic() - start_time) * 1000

            if render_output and (content_buffer or reasoning_buffer):
                first_text_ms = int(first_text_token_elapsed_ms or total_ms)
                response_ms = max(int(total_ms - first_text_ms), 0)
                self.console.print(f"[dim](思考 {first_text_ms}ms / 回复 {response_ms}ms)[/dim]")

            if not response.tool_calls:
                final_text = response.content or ""
                if render_output and renderer is not None:
                    turn_result = renderer.finish(final_text)
                    if final_text and turn_result.needs_final_render:
                        if not assistant_turn_started:
                            self._render_assistant_prefix()
                            assistant_turn_started = True
                        if render_mode == "buffer_then_render":
                            self._print_assistant_bubble(final_text)
                if not final_text:
                    return "No response."
                return final_text

            tool_result = self.tool_executor.execute(
                response,
                blocked_tools=active_blocked_tools,
                tool_scope=tool_scope,
                render_output=render_output,
            )
            if tool_result.blocked_tools:
                active_blocked_tools.update(tool_result.blocked_tools)
            if update_runtime_stats:
                self._tool_call_count += tool_result.executed_count
            history.append(tool_result.assistant_message)
            history.extend(tool_result.tool_messages)
            if render_output:
                self._render_task_panel(response.tool_calls)

            if transcript_session_id:
                self.sessions.append_message(transcript_session_id, tool_result.assistant_message)
                for tm in tool_result.tool_messages:
                    self.sessions.append_message(transcript_session_id, tm)
                for invocation in tool_result.skill_invocations:
                    self.sessions.append_event(
                        transcript_session_id,
                        {"type": "skill_invocation", **invocation},
                    )


def _short_fingerprint(fingerprint: str) -> str:
    if fingerprint.startswith("sha256:"):
        return fingerprint[:19]
    return fingerprint[:16]


def _mcp_command_is_risky(server: MCPServerConfig) -> bool:
    command = server.command.lower()
    args = [arg.lower() for arg in server.args]
    joined = " ".join([command, *args])
    if command in {"uvx"}:
        return True
    if command in {"npx", "pnpm"} and ("-y" in args or "dlx" in args):
        return True
    if command == "npm" and "exec" in args:
        return True
    if command == "docker" and "run" in args:
        return True
    return any(pattern in joined for pattern in ("pnpm dlx", "docker run", "npx -y"))


def _mcp_usage() -> str:
    return (
        "Usage: /mcp status [--verbose]|tools [server]|enable <server>|disable <server>|"
        "tool enable|disable <server> <tool>|refresh [server]|reconnect [server]|events [server]|"
        "output-limit <server> <tool> <chars|default>|trust <server>|untrust <server>|reload"
    )


def _invalid_mcp_output_limit_message() -> str:
    return f"Invalid output limit; expected 1..{MAX_MCP_TOOL_OUTPUT_LIMIT} or default."


def _table_text(value: object) -> Text:
    return Text(str(value))
