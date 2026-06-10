from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_tmp_xcode_home(tmp_path: Path, monkeypatch, auto_memory: bool = True) -> Path:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    for sub in ("sessions", "skills", "bin"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)

    config_path = xcode_dir / "config.json"
    config_path.write_text(
        json.dumps({
            "max_tokens": 128000,
            "model": "test",
            "auto_memory": auto_memory,
        }),
        encoding="utf-8",
    )
    return xcode_dir


def _make_agent(tmp_path: Path, monkeypatch, auto_memory: bool = True):
    _setup_tmp_xcode_home(tmp_path, monkeypatch, auto_memory=auto_memory)
    from unittest.mock import MagicMock
    import xcode_cli.core.agent as agent_mod

    monkeypatch.setattr(
        agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True,
    )
    monkeypatch.setattr(
        agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True,
    )

    from xcode_cli.core.agent import AgentRuntime
    return AgentRuntime()


# ---------------------------------------------------------------------------
# /memory — real command path via AgentRuntime._handle_memory_command
# ---------------------------------------------------------------------------

class TestMemoryCommand:
    def test_memory_prints_status(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch, auto_memory=True)
        agent._handle_memory_command(["/memory"])

        captured = capsys.readouterr()
        assert "Auto-memory: on" in captured.out
        assert "Project memory" in captured.out
        assert "User memory" in captured.out
        assert "Memory dir" in captured.out

    def test_memory_prints_auto_memory_off(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch, auto_memory=False)
        agent._handle_memory_command(["/memory"])

        captured = capsys.readouterr()
        assert "Auto-memory: off" in captured.out

    def test_memory_auto_on_persists(self, tmp_path: Path, monkeypatch) -> None:
        agent = _make_agent(tmp_path, monkeypatch, auto_memory=False)
        agent._handle_memory_command(["/memory", "auto", "on"])

        cfg = agent.config_store.load()
        assert cfg.auto_memory is True

    def test_memory_auto_off_persists(self, tmp_path: Path, monkeypatch) -> None:
        agent = _make_agent(tmp_path, monkeypatch, auto_memory=True)
        agent._handle_memory_command(["/memory", "auto", "off"])

        cfg = agent.config_store.load()
        assert cfg.auto_memory is False

    def test_memory_auto_on_output(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch, auto_memory=False)
        agent._handle_memory_command(["/memory", "auto", "on"])

        captured = capsys.readouterr()
        assert "on" in captured.out

    def test_memory_auto_off_output(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch, auto_memory=True)
        agent._handle_memory_command(["/memory", "auto", "off"])

        captured = capsys.readouterr()
        assert "off" in captured.out

    def test_memory_invalid_usage_shows_help(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        agent._handle_memory_command(["/memory", "bad", "arg"])

        captured = capsys.readouterr()
        assert "Usage" in captured.out

    def test_memory_paths_use_resolved_locations(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        agent._handle_memory_command(["/memory"])

        captured = capsys.readouterr()
        flat = captured.out.replace("\n", " ")
        # Rich may word-wrap long paths; check partial components
        assert "Project memory" in flat
        assert "User memory" in flat
        assert "Memory dir" in flat
        assert ".xcode" in flat
        assert "XCODE.md" in flat
        assert "memory" in flat

    def test_memory_isolated_from_real_xcode_home(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        mem_dir = str(agent.memory.memory_dir_path())
        # memory dir must be inside our temp tree
        assert str(tmp_path) in mem_dir
        # must NOT be inside the real ~/.xcode directory
        real_xcode = str(Path.home() / ".xcode")
        assert not mem_dir.startswith(real_xcode)
