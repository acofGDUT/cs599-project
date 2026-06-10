from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from xcode_cli.core.session import SessionInfo, SessionStore


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path, monkeypatch, cwd: str = "D:\\Xcode") -> SessionStore:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    for sub in ("sessions", "skills", "bin"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)

    return SessionStore(cwd=cwd)


# ---------------------------------------------------------------------------
# session id
# ---------------------------------------------------------------------------

class TestSessionId:
    def test_new_session_id_is_valid_uuid(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        uuid.UUID(sid)

    def test_new_session_id_is_unique(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        ids = {store.new_session_id() for _ in range(20)}
        assert len(ids) == 20


# ---------------------------------------------------------------------------
# project-key
# ---------------------------------------------------------------------------

class TestProjectKey:
    def test_windows_drive_letter(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch, cwd="D:\\Xcode")
        assert store.project_key() == "D--Xcode"

    def test_windows_nested_path(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch, cwd="D:\\Work\\Xcode")
        assert store.project_key() == "D--Work--Xcode"

    def test_windows_long_path(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch, cwd="C:\\Users\\dev\\projects\\myapp")
        assert store.project_key() == "C--Users--dev--projects--myapp"

    def test_unix_path(self, tmp_path: Path, monkeypatch) -> None:
        import os as _os
        store = _make_store(tmp_path, monkeypatch, cwd="/home/user/project")
        key = store.project_key()
        if _os.name == "nt":
            assert "home--user--project" in key
        else:
            assert key == "--home--user--project"

    def test_no_colon_in_key(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch, cwd="D:\\Xcode")
        assert ":" not in store.project_key()

    def test_key_contains_only_safe_chars(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch, cwd="D:\\Xcode")
        key = store.project_key()
        for ch in key:
            assert ch.isalnum() or ch == "-"


# ---------------------------------------------------------------------------
# transcript paths
# ---------------------------------------------------------------------------

class TestTranscriptPaths:
    def test_sessions_dir_under_projects(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch, cwd="D:\\Xcode")
        sd = store.sessions_dir
        assert ".xcode" in str(sd)
        assert "projects" in str(sd)
        assert "D--Xcode" in str(sd)
        assert sd.name == "sessions"

    def test_transcript_path_uses_uuid_name(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        path = store.transcript_path(sid)
        assert path.name == f"{sid}.jsonl"

    def test_transcript_path_in_sessions_dir(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        path = store.transcript_path(sid)
        assert path.parent == store.sessions_dir


# ---------------------------------------------------------------------------
# append_message / append_event
# ---------------------------------------------------------------------------

class TestAppendMessage:
    def test_append_user_message_creates_file(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "hello"})
        path = store.transcript_path(sid)
        assert path.exists()

    def test_append_message_writes_type_field(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "hello"})
        path = store.transcript_path(sid)
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
        assert len(events) == 1
        assert events[0]["type"] == "message"
        assert events[0]["role"] == "user"
        assert events[0]["content"] == "hello"
        assert "ts" in events[0]

    def test_append_message_preserves_extra_fields(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "assistant", "content": "ok", "tool_calls": [{"id": "c1"}]})
        path = store.transcript_path(sid)
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
        assert events[0]["tool_calls"] == [{"id": "c1"}]

    def test_append_event_writes_generic_event(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_event(sid, {"type": "compaction_checkpoint", "summary": "test"})
        path = store.transcript_path(sid)
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
        assert events[0]["type"] == "compaction_checkpoint"
        assert events[0]["summary"] == "test"

    def test_append_message_multiple_messages(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "q1"})
        store.append_message(sid, {"role": "assistant", "content": "a1"})
        store.append_message(sid, {"role": "user", "content": "q2"})
        path = store.transcript_path(sid)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# user history
# ---------------------------------------------------------------------------

class TestUserHistory:
    def test_append_user_history_creates_file(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_user_history(sid, "hello world")
        path = store._history_path
        assert path.exists()

    def test_append_user_history_structure(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch, cwd="D:\\Xcode")
        sid = store.new_session_id()
        store.append_user_history(sid, "test input")
        path = store._history_path
        entry = json.loads(path.read_text(encoding="utf-8").strip())
        assert entry["display"] == "test input"
        assert entry["project"] == "D:\\Xcode"
        assert entry["sessionId"] == sid
        assert isinstance(entry["timestamp"], int)


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_empty_when_no_sessions(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        assert store.list_sessions() == []

    def test_lists_single_session(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "hello"})
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_id == sid
        assert sessions[0].message_count == 1
        assert sessions[0].last_user_input == "hello"
        assert sessions[0].has_checkpoint is False

    def test_lists_multiple_sessions_ordered_by_time(self, tmp_path: Path, monkeypatch) -> None:
        import time as _time

        store = _make_store(tmp_path, monkeypatch)
        sid1 = store.new_session_id()
        store.append_message(sid1, {"role": "user", "content": "first"})
        _time.sleep(0.05)

        sid2 = store.new_session_id()
        store.append_message(sid2, {"role": "user", "content": "second"})

        sessions = store.list_sessions()
        assert len(sessions) == 2
        assert sessions[0].session_id == sid2
        assert sessions[1].session_id == sid1

    def test_last_user_input_returns_last_user_message(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "q1"})
        store.append_message(sid, {"role": "assistant", "content": "a1"})
        store.append_message(sid, {"role": "user", "content": "q2"})
        sessions = store.list_sessions()
        assert sessions[0].last_user_input == "q2"

    def test_has_checkpoint_true(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "hello"})
        store.append_event(sid, {"type": "compaction_checkpoint", "summary": "s"})
        sessions = store.list_sessions()
        assert sessions[0].has_checkpoint is True

    def test_message_count_only_counts_messages(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "q"})
        store.append_event(sid, {"type": "compaction_checkpoint", "summary": "s"})
        store.append_message(sid, {"role": "assistant", "content": "a"})
        sessions = store.list_sessions()
        assert sessions[0].message_count == 2

    def test_path_field_is_correct(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "hello"})
        sessions = store.list_sessions()
        assert sessions[0].path == store.transcript_path(sid)
        assert isinstance(sessions[0].path, Path)


# ---------------------------------------------------------------------------
# load_history
# ---------------------------------------------------------------------------

class TestLoadHistory:
    def test_empty_when_missing_session(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        assert store.load_history("nonexistent") == []

    def test_loads_messages(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "hello"})
        store.append_message(sid, {"role": "assistant", "content": "world"})

        msgs = store.load_history(sid)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "hello"}
        assert msgs[1] == {"role": "assistant", "content": "world"}

    def test_strips_type_and_ts_fields(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "user", "content": "test"})

        msgs = store.load_history(sid)
        assert "type" not in msgs[0]
        assert "ts" not in msgs[0]

    def test_preserves_tool_calls(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        tool_calls = [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]
        store.append_message(sid, {"role": "assistant", "content": None, "tool_calls": tool_calls})

        msgs = store.load_history(sid)
        assert msgs[0]["tool_calls"] == tool_calls
        assert msgs[0]["content"] is None

    def test_preserves_tool_message(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "tool", "tool_call_id": "call_123", "content": "result"})

        msgs = store.load_history(sid)
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "call_123"
        assert msgs[0]["content"] == "result"

    def test_skips_non_message_events(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_event(sid, {"type": "compaction_checkpoint", "summary": "s"})
        store.append_message(sid, {"role": "user", "content": "hello"})
        store.append_event(sid, {"type": "compaction_checkpoint", "summary": "s2"})

        msgs = store.load_history(sid)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_message_has_required_openai_fields(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        store.append_message(sid, {"role": "assistant", "content": "ok"})

        msgs = store.load_history(sid)
        assert "role" in msgs[0]
        assert "content" in msgs[0]

    def test_handles_malformed_lines(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        sid = store.new_session_id()
        path = store.transcript_path(sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write("not valid json\n")
            f.write(json.dumps({"type": "message", "role": "user", "content": "valid"}) + "\n")
            f.write("also bad\n")

        msgs = store.load_history(sid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "valid"
