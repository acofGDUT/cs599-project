from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_tmp_xcode_home(tmp_path: Path, monkeypatch) -> Path:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    for sub in ("sessions", "skills", "bin", "projects"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)
    config_path = xcode_dir / "config.json"
    config_path.write_text(
        json.dumps({"max_tokens": 128000, "model": "test", "auto_memory": True}),
        encoding="utf-8",
    )
    return xcode_dir


def _make_agent(tmp_path: Path, monkeypatch, cwd: str = "D:\\Xcode"):
    _setup_tmp_xcode_home(tmp_path, monkeypatch)
    from unittest.mock import MagicMock

    import xcode_cli.core.agent as agent_mod

    monkeypatch.setattr(
        agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True,
    )
    monkeypatch.setattr(
        agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True,
    )
    monkeypatch.setattr(
        agent_mod, "resolve_project_root", MagicMock(return_value=cwd), raising=True,
    )

    from xcode_cli.core.agent import AgentRuntime
    return AgentRuntime()


def _write_transcript(store, session_id: str, messages: list[dict]) -> None:
    for msg in messages:
        store.append_message(session_id, msg)


# ---------------------------------------------------------------------------
# /resume
# ---------------------------------------------------------------------------

class TestResumeCommand:
    def test_no_sessions_shows_message(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "No recent sessions" in captured.out

    def test_list_sessions(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)

        sid1 = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid1, [{"role": "user", "content": "hello"}])

        sid2 = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid2, [{"role": "user", "content": "world"}])

        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "Recent sessions" in captured.out
        assert sid1[:8] in captured.out
        assert sid2[:8] in captured.out
        assert "hello" in captured.out
        assert "world" in captured.out

    def test_shows_checkpoint_mark(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [{"role": "user", "content": "test"}])
        agent.sessions.append_event(sid, {"type": "compaction_checkpoint", "summary": "s"})

        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "[checkpoint]" in captured.out

    def test_list_sessions_isolated_from_real_home(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        agent = _make_agent(tmp_path, monkeypatch, cwd="D:\\IsolatedTest")
        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [{"role": "user", "content": "isolated"}])

        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "isolated" in captured.out
        real_xcode = str(Path.home() / ".xcode")
        sessions_dir_str = str(agent.sessions.sessions_dir)
        assert not sessions_dir_str.startswith(real_xcode)


class TestResumeSelection:
    def test_cancel_on_empty_input(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [{"role": "user", "content": "hello"}])

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = ""

        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "Cancelled" in captured.out

    def test_invalid_non_numeric(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [{"role": "user", "content": "hello"}])

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = "abc"

        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "Invalid selection" in captured.out

    def test_invalid_out_of_range(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [{"role": "user", "content": "hello"}])

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = "99"

        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "Invalid selection" in captured.out


class TestResumeSuccessful:
    def test_resume_loads_history(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ])
        old_session_id = agent._session_id

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = "1"

        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "Resumed session" in captured.out
        assert sid in captured.out
        assert "Restored messages: 3" in captured.out
        assert "Estimated context" in captured.out
        assert "q2" in captured.out

        assert agent._session_id == sid
        assert agent._session_id != old_session_id
        assert len(agent._history) == 3
        assert agent._history[0] == {"role": "user", "content": "q1"}

    def test_resume_renders_recent_conversation_after_checkpoint(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ])
        agent.sessions.append_event(sid, {"type": "compaction_checkpoint", "summary": "old summary"})
        _write_transcript(agent.sessions, sid, [
            {
                "role": "user",
                "content": "/review src/foo.py",
                "metadata": {"model_content": "FULL HIDDEN SKILL PROMPT"},
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "secret tool output"},
            {"role": "assistant", "content": "final answer"},
        ])

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = "1"

        agent._handle_resume_command()
        captured = capsys.readouterr()

        assert "Recent conversation since checkpoint:" in captured.out
        assert "/review src/foo.py" in captured.out
        assert "final answer" in captured.out
        assert "old question" not in captured.out
        assert "secret tool output" not in captured.out
        assert "FULL HIDDEN SKILL PROMPT" not in captured.out
        assert any(m.get("content") == "FULL HIDDEN SKILL PROMPT" for m in agent._history)

    def test_resume_loads_tool_calls(self, tmp_path: Path, monkeypatch) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        sid = agent.sessions.new_session_id()
        tool_calls = [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]
        _write_transcript(agent.sessions, sid, [
            {"role": "user", "content": "read file"},
            {"role": "assistant", "content": None, "tool_calls": tool_calls},
            {"role": "tool", "tool_call_id": "c1", "content": "file content"},
            {"role": "assistant", "content": "done"},
        ])

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = "1"

        agent._handle_resume_command()

        assert len(agent._history) == 4
        assert agent._history[1]["tool_calls"] == tool_calls
        assert agent._history[2]["role"] == "tool"
        assert agent._history[2]["tool_call_id"] == "c1"

    def test_resume_updates_runtime_status(self, tmp_path: Path, monkeypatch) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        agent._runtime_status.create("old-sid", agent.cwd)

        new_sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, new_sid, [{"role": "user", "content": "test"}])

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = "1"

        agent._handle_resume_command()

        import json
        data = json.loads(agent._runtime_status._path.read_text(encoding="utf-8"))
        assert data["sessionId"] == new_sid

    def test_resume_with_empty_load_shows_error(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [{"role": "user", "content": "hello"}])

        import xcode_cli.core.conversation.resume as resume_mod
        from xcode_cli.core.session_resume import ResumeResult

        class _EmptyBuilder:
            def __init__(self, context, token_budget) -> None:
                self.context = context
                self.token_budget = token_budget

            def build(self, transcript_path):
                return ResumeResult(
                    history=[],
                    message_count=0,
                    restored_from_checkpoint=False,
                    checkpoint_summary_chars=0,
                    tail_message_count=0,
                    estimated_tokens=0,
                )

        monkeypatch.setattr(resume_mod, "SessionResumeBuilder", _EmptyBuilder)

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = "1"

        agent._handle_resume_command()
        captured = capsys.readouterr()
        assert "Failed to load" in captured.out

    def test_resume_clears_existing_history(self, tmp_path: Path, monkeypatch) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        agent._history = [{"role": "user", "content": "old"}]

        sid = agent.sessions.new_session_id()
        _write_transcript(agent.sessions, sid, [{"role": "user", "content": "new"}])

        mock_prompt = agent.prompt.prompt
        mock_prompt.return_value = "1"

        agent._handle_resume_command()

        assert len(agent._history) == 1
        assert agent._history[0]["content"] == "new"


# ---------------------------------------------------------------------------
# /compact
# ---------------------------------------------------------------------------

class TestCompactCommand:
    def test_compact_short_history_shows_message(self, tmp_path: Path, monkeypatch, capsys) -> None:
        agent = _make_agent(tmp_path, monkeypatch)
        agent._history = [{"role": "user", "content": "hi"}]
        agent._handle_compact_command()
        captured = capsys.readouterr()
        assert "Nothing to compact" in captured.out

    def test_compact_writes_checkpoint_to_transcript(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from xcode_cli.core.context import CompressionResult

        agent = _make_agent(tmp_path, monkeypatch)
        agent._session_id = agent.sessions.new_session_id()
        agent._history = [
            {"role": "user", "content": "a" * 200},
            {"role": "assistant", "content": "b" * 200},
            {"role": "user", "content": "c" * 200},
            {"role": "assistant", "content": "d" * 200},
        ]

        fake_result = CompressionResult(
            messages=[
                agent._history[0],
                {"role": "system", "content": "Conversation summary checkpoint:\nfake summary"},
                agent._history[-2],
                agent._history[-1],
            ],
            summary="fake summary",
            checkpoint_message={"role": "system", "content": "Conversation summary checkpoint:\nfake summary"},
        )
        monkeypatch.setattr(agent.context, "compress", lambda *a, **kw: fake_result)

        agent._handle_compact_command()
        captured = capsys.readouterr()
        assert "compacted" in captured.out.lower()

        path = agent.sessions.transcript_path(agent._session_id)
        events = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        msg_types = [e.get("type") for e in events]
        assert "message" in msg_types
        assert "compaction_checkpoint" in msg_types
        cp = next(e for e in events if e.get("type") == "compaction_checkpoint")
        assert cp["summary_format"] == "xcode.v1"
        assert cp["source_message_count"] == 4
        assert isinstance(cp["summary"], str) and len(cp["summary"]) > 0

    def test_compact_preserves_tail_messages(self, tmp_path: Path, monkeypatch) -> None:
        from xcode_cli.core.context import CompressionResult

        agent = _make_agent(tmp_path, monkeypatch)
        agent._session_id = agent.sessions.new_session_id()
        last_msg = {"role": "user", "content": "this is the last message"}
        agent._history = [
            {"role": "user", "content": "a" * 200},
            {"role": "assistant", "content": "b" * 200},
            {"role": "user", "content": "c" * 200},
            {"role": "assistant", "content": "d" * 200},
            last_msg,
        ]

        fake_result = CompressionResult(
            messages=[
                agent._history[0],
                {"role": "system", "content": "Conversation summary checkpoint:\nfake"},
                last_msg,
            ],
            summary="fake",
            checkpoint_message={"role": "system", "content": "Conversation summary checkpoint:\nfake"},
        )
        monkeypatch.setattr(agent.context, "compress", lambda *a, **kw: fake_result)

        agent._handle_compact_command()
        assert any(last_msg["content"] in str(m.get("content", "")) for m in agent._history)

    def test_compact_no_checkpoint_shows_nothing(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from xcode_cli.core.context import CompressionResult

        agent = _make_agent(tmp_path, monkeypatch)
        agent._session_id = agent.sessions.new_session_id()
        agent._history = [
            {"role": "user", "content": f"msg {i}"} for i in range(5)
        ]

        fake_result = CompressionResult(
            messages=list(agent._history),
            summary="",
            checkpoint_message={},
        )
        monkeypatch.setattr(agent.context, "compress", lambda *a, **kw: fake_result)

        history_before = list(agent._history)
        agent._handle_compact_command()
        captured = capsys.readouterr()
        assert "Nothing to compact" in captured.out
        assert agent._history == history_before

        path = agent.sessions.transcript_path(agent._session_id)
        events = []
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        cp_events = [e for e in events if e.get("type") == "compaction_checkpoint"]
        assert len(cp_events) == 0
