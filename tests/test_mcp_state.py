from __future__ import annotations

import json
from pathlib import Path

import pytest

import xcode_cli.paths as xcode_paths
from xcode_cli.core.agent import AgentRuntime
from xcode_cli.mcp.state import MAX_MCP_TOOL_OUTPUT_LIMIT, MCPStateStore


def _setup_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home" / ".xcode"
    monkeypatch.setattr(xcode_paths, "XCODE_DIR", home, raising=True)
    home.mkdir(parents=True)
    return home


def test_default_state_path_is_project_scoped_local_home(tmp_path: Path, monkeypatch) -> None:
    home = _setup_home(tmp_path, monkeypatch)

    store = MCPStateStore(project_key="D--Xcode")

    assert store.path == home / "projects" / "D--Xcode" / "mcp_state.json"


def test_state_store_does_not_write_project_mcp_config(tmp_path: Path, monkeypatch) -> None:
    _setup_home(tmp_path, monkeypatch)
    project = tmp_path / "project"
    config_dir = project / ".xcode"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "mcp.json"
    config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

    store = MCPStateStore(project_key="project-key")
    store.set_server_enabled("github", False)

    assert config_path.read_text(encoding="utf-8") == '{"mcpServers": {}}'
    assert store.path.exists()
    assert project not in store.path.parents


def test_missing_state_file_returns_empty_state(tmp_path: Path) -> None:
    store = MCPStateStore(project_key="project", path=tmp_path / "missing.json")

    state = store.load()

    assert state.servers == {}
    assert state.warnings == ()


def test_corrupt_state_file_returns_empty_state_with_safe_warning(tmp_path: Path) -> None:
    path = tmp_path / "mcp_state.json"
    path.write_text('{"servers": {"github": "SUPER_SECRET_TOKEN"', encoding="utf-8")
    store = MCPStateStore(project_key="project", path=path)

    state = store.load()

    assert state.servers == {}
    assert state.warnings
    assert "SUPER_SECRET_TOKEN" not in "\n".join(state.warnings)


def test_server_and_tool_enabled_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "mcp_state.json"
    store = MCPStateStore(project_key="project", path=path)

    store.set_server_enabled("github", False)
    store.set_tool_enabled("github", "create_issue", True)

    state = MCPStateStore(project_key="project", path=path).load()
    assert state.servers["github"].enabled is False
    assert state.servers["github"].tools["create_issue"].enabled is True


def test_tool_output_limit_round_trip_and_default_clear(tmp_path: Path) -> None:
    path = tmp_path / "mcp_state.json"
    store = MCPStateStore(project_key="project", path=path)

    store.set_tool_output_limit("github", "list_issues", 12000)
    assert MCPStateStore(project_key="project", path=path).load().servers["github"].tools["list_issues"].max_output_chars == 12000

    store.set_tool_output_limit("github", "list_issues", None)
    state = MCPStateStore(project_key="project", path=path).load()
    assert "github" not in state.servers


@pytest.mark.parametrize("value", [0, -1, MAX_MCP_TOOL_OUTPUT_LIMIT + 1])
def test_tool_output_limit_rejects_invalid_values(tmp_path: Path, value: int) -> None:
    store = MCPStateStore(project_key="project", path=tmp_path / "mcp_state.json")

    with pytest.raises(ValueError):
        store.set_tool_output_limit("github", "list_issues", value)

    assert not store.path.exists()


def test_state_write_does_not_persist_secret_like_values(tmp_path: Path) -> None:
    path = tmp_path / "mcp_state.json"
    store = MCPStateStore(project_key="project", path=path)

    store.set_server_enabled("github", True)
    store.set_tool_enabled("github", "list_issues", False)
    store.set_tool_output_limit("github", "list_issues", 5000)

    raw = path.read_text(encoding="utf-8")
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in raw
    assert "ghp_SUPER_SECRET" not in raw
    assert "Authorization" not in raw
    assert "token" not in raw.lower()


def test_agent_runtime_initializes_mcp_state_store(tmp_path: Path, monkeypatch) -> None:
    from unittest.mock import MagicMock

    import xcode_cli.core.agent as agent_mod

    home = _setup_home(tmp_path, monkeypatch)
    (home / "config.json").write_text(json.dumps({"model": "test"}), encoding="utf-8")
    for sub in ("sessions", "skills", "bin"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "resolve_project_root", MagicMock(return_value=str(project)), raising=True)

    agent = AgentRuntime()

    assert isinstance(agent.mcp_state_store, MCPStateStore)
    assert agent.mcp_state_store.path == home / "projects" / agent._project_key / "mcp_state.json"
