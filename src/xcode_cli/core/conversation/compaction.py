from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from rich.live import Live
from rich.text import Text


@dataclass
class CompactOutcome:
    messages: list[dict[str, Any]]
    summary: str
    checkpoint_message: dict[str, Any]
    before_messages: int
    after_messages: int
    before_tokens: int
    after_tokens: int


class ConversationCompactor:
    def __init__(self, context, llm, sessions, console) -> None:
        self.context = context
        self.llm = llm
        self.sessions = sessions
        self.console = console

    @staticmethod
    def find_previous_summary(history: list[dict[str, Any]]) -> str:
        for msg in reversed(history):
            if msg.get("role") == "system":
                content = str(msg.get("content", ""))
                if "Conversation summary checkpoint:" in content:
                    return content.split("Conversation summary checkpoint:\n", 1)[-1].strip()
        return ""

    def compact_history(self, history: list[dict[str, Any]]) -> CompactOutcome | None:
        before_messages = len(history)
        before_tokens = self.context.estimate_tokens(history)
        previous_summary = self.find_previous_summary(history)

        # 启动 Live 进度
        start_time = time.monotonic()
        stop_event = threading.Event()

        def _update_progress():
            while not stop_event.is_set():
                elapsed = time.monotonic() - start_time
                live.update(Text(f"Compacting context... ({elapsed:.1f}s)", style="dim"))
                time.sleep(0.1)

        live = Live(
            Text("Compacting context... (0.0s)", style="dim"),
            console=self.console,
            refresh_per_second=8,
            transient=True,
        )
        live.start()
        progress_thread = threading.Thread(target=_update_progress, daemon=True)
        progress_thread.start()

        try:
            result = self.context.compress(history, self.llm, previous_summary)
        finally:
            # 停止 Live 进度
            stop_event.set()
            progress_thread.join(timeout=0.2)
            live.stop()

        if not result.checkpoint_message:
            return None

        after_messages = len(result.messages)
        after_tokens = self.context.estimate_tokens(result.messages)

        return CompactOutcome(
            messages=result.messages,
            summary=result.summary,
            checkpoint_message=result.checkpoint_message,
            before_messages=before_messages,
            after_messages=after_messages,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
        )

    def write_checkpoint(self, session_id: str, outcome: CompactOutcome) -> None:
        self.sessions.append_message(session_id, outcome.checkpoint_message)
        self.sessions.append_event(session_id, {
            "type": "compaction_checkpoint",
            "summary": outcome.summary,
            "summary_format": "xcode.v1",
            "source_message_count": outcome.before_messages,
            "source_token_estimate": outcome.before_tokens,
            "remaining_message_count": outcome.after_messages,
        })
