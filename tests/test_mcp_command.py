from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from xcode_cli.core.agent import AgentRuntime
from xcode_cli.mcp.config import MCPConfig, MCPServerConfig
from xcode_cli.mcp.status import MCPServerStatus
from xcode_cli.mcp.trust import MCPTrustStore


class FakeManager:
    def __init__(self) -> None:
        self.shutdown_called = False
        self._statuses = [
            MCPServerStatus(
                name="filesystem",
                status="untrusted",
                fingerprint="sha256:" + "a" * 64,
                tool_count=0,
            )
        ]

    def statuses(self):
        return self._statuses

    def shutdown(self):
        self.shutdown_called = True


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=True, width=120)


def _output(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


def _server(command: str = "python", args: tuple[str, ...] = ("server.py",)) -> MCPServerConfig:
    return MCPServerConfig(
        name="filesystem",
        type="stdio",
        command=command,
        args=args,
        cwd=Path.cwd(),
        env={"TOKEN": "secret"},
    )


def _runtime(tmp_path: Path, server: MCPServerConfig | None = None):
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.console = _console()
    runtime.cwd = str(tmp_path)
    runtime._project_key = "project"
    runtime.mcp_config = MCPConfig(servers=(server or _server(),))
    runtime.mcp_trust = MCPTrustStore(tmp_path / "trust.json")
    runtime.mcp_manager = FakeManager()
    runtime._mcp_tool_warnings = []
    runtime._reload_mcp_servers = MagicMock()
    return runtime


def test_mcp_status_prints_server_state(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    runtime._handle_mcp_command(["/mcp", "status"])

    output = _output(runtime.console)
    assert "filesystem" in output
    assert "untrusted" in output


def test_mcp_trust_requires_server_argument(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    runtime._handle_mcp_command(["/mcp", "trust"])

    assert "Usage: /mcp trust <server>" in _output(runtime.console)


def test_mcp_trust_flow_writes_trust_and_reloads(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime._confirm_mcp_trust = lambda server: True

    runtime._handle_mcp_command(["/mcp", "trust", "filesystem"])

    assert runtime.mcp_trust.is_trusted("project", runtime.mcp_config.servers[0])
    runtime._reload_mcp_servers.assert_called_once()
    output = _output(runtime.console)
    assert "command: python" in output
    assert "env keys: TOKEN" in output
    assert "hash: sha256:" in output


def test_mcp_trust_shows_risky_command_warning(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, _server(command="npx", args=("-y", "@modelcontextprotocol/server-filesystem")))
    runtime._confirm_mcp_trust = lambda server: False

    runtime._handle_mcp_command(["/mcp", "trust", "filesystem"])

    assert "may download or execute external code" in _output(runtime.console)
    assert not runtime.mcp_trust.is_trusted("project", runtime.mcp_config.servers[0])
    runtime._reload_mcp_servers.assert_not_called()


def test_mcp_untrust_removes_trust_and_reloads(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    server = runtime.mcp_config.servers[0]
    runtime.mcp_trust.trust("project", server)

    runtime._handle_mcp_command(["/mcp", "untrust", "filesystem"])

    assert not runtime.mcp_trust.is_trusted("project", server)
    runtime._reload_mcp_servers.assert_called_once()


def test_mcp_reload_calls_reload_and_prints_status(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    runtime._handle_mcp_command(["/mcp", "reload"])

    runtime._reload_mcp_servers.assert_called_once()
    assert "filesystem" in _output(runtime.console)


def test_mcp_unknown_subcommand_prints_usage(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    runtime._handle_mcp_command(["/mcp", "bogus"])

    output = _output(runtime.console)
    assert "Usage: /mcp status [--verbose]" in output
    assert "output-limit <server> <tool>" in output
