from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from xcode_cli.core.commands.slash import INIT_PROMPT


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_tmp_xcode_home(tmp_path: Path, monkeypatch) -> Path:
    import xcode_cli.paths

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    xcode_dir.mkdir(parents=True, exist_ok=True)
    (xcode_dir / "config.json").write_text(
        json.dumps({"model": "test-model", "api_key": "test-key"}),
        encoding="utf-8",
    )
    for subdir in ("sessions", "skills", "bin"):
        (xcode_dir / subdir).mkdir(parents=True, exist_ok=True)
    return xcode_dir


def _make_agent(tmp_path: Path, monkeypatch):
    import xcode_cli.core.agent as agent_mod

    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    monkeypatch.chdir(project_dir)
    _setup_tmp_xcode_home(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "resolve_project_root", MagicMock(return_value=str(project_dir)), raising=True)

    from xcode_cli.core.agent import AgentRuntime

    agent = AgentRuntime()
    agent._session_id = "test-session"
    agent._history = []
    return agent


# ---------------------------------------------------------------------------
# _run_user_turn 行为测试
# ---------------------------------------------------------------------------

class TestRunUserTurn:
    def test_appends_user_and_assistant_to_history(self, tmp_path: Path, monkeypatch) -> None:
        """_run_user_turn('hello') 将 user 和 assistant 消息写入 _history"""
        agent = _make_agent(tmp_path, monkeypatch)
        agent._run_llm_loop = MagicMock(return_value="hi there")

        agent._run_user_turn("hello")

        assert len(agent._history) == 2
        assert agent._history[0] == {"role": "user", "content": "hello"}
        assert agent._history[1] == {"role": "assistant", "content": "hi there"}

    def test_init_prompt_behaves_as_normal_turn(self, tmp_path: Path, monkeypatch) -> None:
        """_run_user_turn(INIT_PROMPT) 与普通 prompt 行为相同"""
        agent = _make_agent(tmp_path, monkeypatch)
        agent._run_llm_loop = MagicMock(return_value="created XCODE.md")

        agent._run_user_turn(INIT_PROMPT)

        assert len(agent._history) == 2
        assert agent._history[0] == {"role": "user", "content": INIT_PROMPT}
        assert agent._history[1] == {"role": "assistant", "content": "created XCODE.md"}

    def test_user_turn_input_uses_model_content_for_llm_history(self, tmp_path: Path, monkeypatch) -> None:
        from xcode_cli.core.turn import UserTurnInput

        agent = _make_agent(tmp_path, monkeypatch)
        agent._run_llm_loop = MagicMock(return_value="reviewed")

        agent._run_user_turn(
            UserTurnInput(
                display_content="/review src/foo.py",
                model_content="Review this: src/foo.py",
                metadata={"kind": "skill_invocation", "skill": "review"},
            )
        )

        assert agent._history[0] == {"role": "user", "content": "Review this: src/foo.py"}
        saved = agent.sessions.load_history(agent._session_id)
        assert saved[0]["content"] == "/review src/foo.py"
        assert saved[0]["metadata"]["model_content"] == "Review this: src/foo.py"
        assert saved[0]["metadata"]["skill"] == "review"

    def test_llm_error_does_not_append_assistant(self, tmp_path: Path, monkeypatch) -> None:
        """LLM 错误结果不追加 assistant 到 _history"""
        agent = _make_agent(tmp_path, monkeypatch)
        agent._run_llm_loop = MagicMock(return_value="[v0] LLM request failed: timeout")

        agent._run_user_turn("hello")

        assert len(agent._history) == 1
        assert agent._history[0] == {"role": "user", "content": "hello"}

    def test_missing_key_does_not_append_assistant(self, tmp_path: Path, monkeypatch) -> None:
        """Missing API key 错误不追加 assistant 到 _history"""
        agent = _make_agent(tmp_path, monkeypatch)
        agent._run_llm_loop = MagicMock(return_value="[v0] Missing API key")

        agent._run_user_turn("hello")

        assert len(agent._history) == 1
        assert agent._history[0] == {"role": "user", "content": "hello"}

    def test_missing_package_does_not_append_assistant(self, tmp_path: Path, monkeypatch) -> None:
        """openai package 缺失错误不追加 assistant 到 _history"""
        agent = _make_agent(tmp_path, monkeypatch)
        agent._run_llm_loop = MagicMock(return_value="[v0] openai package not installed")

        agent._run_user_turn("hello")

        assert len(agent._history) == 1
        assert agent._history[0] == {"role": "user", "content": "hello"}


def test_missing_qq_config_does_not_break_normal_turn(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("QQ_BOT_APP_ID", raising=False)
    monkeypatch.delenv("QQ_BOT_CLIENT_SECRET", raising=False)

    agent = _make_agent(tmp_path, monkeypatch)
    agent._run_llm_loop = MagicMock(return_value="hi there")

    assert agent.qqchat_service is None
    assert "QQchat requires" in str(agent._qqchat_init_error)

    agent._run_user_turn("hello")

    assert agent._history[-1] == {"role": "assistant", "content": "hi there"}


def test_agent_runtime_passes_full_qqchat_config_to_service(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QQ_BOT_APP_ID", "app")
    monkeypatch.setenv("QQ_BOT_CLIENT_SECRET", "secret")

    agent = _make_agent(tmp_path, monkeypatch)
    project_config = Path(agent.cwd) / ".xcode" / "config.json"
    project_config.parent.mkdir()
    project_config.write_text(
        json.dumps({"qqchat": {"enable_c2c": False, "max_reply_chars": 7}}),
        encoding="utf-8",
    )

    agent = _make_agent(tmp_path, monkeypatch)

    assert agent.qqchat_service is not None
    assert agent.qqchat_service.status()["config"]["enable_c2c"] is False
    assert agent.qqchat_service.status()["config"]["max_reply_chars"] == 7
