from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from xcode_cli.paths import ensure_xcode_home


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    updated_at: float
    last_user_input: str
    message_count: int
    has_checkpoint: bool


class SessionStore:
    def __init__(self, cwd: str | None = None) -> None:
        root = ensure_xcode_home()
        self._cwd = cwd or os.getcwd()
        self._projects_dir = root / "projects"
        self._history_path = root / "history.jsonl"

    def new_session_id(self) -> str:
        return str(uuid.uuid4())

    def project_key(self) -> str:
        path = os.path.abspath(self._cwd)
        key = path.replace(":", "").replace("\\", "--").replace("/", "--")
        while key.startswith("-"):
            key = key[1:]
        return key

    @property
    def sessions_dir(self) -> Path:
        return self._projects_dir / self.project_key() / "sessions"

    def transcript_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def append_event(self, session_id: str, event: dict[str, Any]) -> None:
        event["ts"] = datetime.utcnow().isoformat()
        path = self.transcript_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        event: dict[str, Any] = {"type": "message"}
        event.update(message)
        self.append_event(session_id, event)

    def append_user_history(self, session_id: str, display: str) -> None:
        entry: dict[str, Any] = {
            "display": display,
            "timestamp": int(time.time() * 1000),
            "project": self._cwd,
            "sessionId": session_id,
        }
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        with self._history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def list_sessions(self) -> list[SessionInfo]:
        if not self.sessions_dir.exists():
            return []

        sessions: list[SessionInfo] = []
        for f in self.sessions_dir.glob("*.jsonl"):
            session_id = f.stem
            updated_at = f.stat().st_mtime
            message_count = 0
            has_checkpoint = False
            last_user_input = ""

            with f.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "message":
                        message_count += 1
                        if event.get("role") == "user":
                            last_user_input = event.get("content", "")
                    elif event.get("type") == "compaction_checkpoint":
                        has_checkpoint = True

            sessions.append(SessionInfo(
                session_id=session_id,
                path=f,
                updated_at=updated_at,
                last_user_input=last_user_input,
                message_count=message_count,
                has_checkpoint=has_checkpoint,
            ))

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def load_history(self, session_id: str) -> list[dict[str, Any]]:
        path = self.transcript_path(session_id)
        if not path.exists():
            return []

        messages: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "message":
                    msg: dict[str, Any] = {}
                    for key, value in event.items():
                        if key not in ("type", "ts"):
                            msg[key] = value
                    messages.append(msg)

        return messages
