from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xcode_cli.core.context import ContextManager


@dataclass(frozen=True)
class ResumeReplayMessage:
    role: str
    content: str


@dataclass
class ResumeResult:
    history: list[dict[str, Any]]
    message_count: int
    restored_from_checkpoint: bool
    checkpoint_summary_chars: int
    tail_message_count: int
    estimated_tokens: int


class SessionResumeBuilder:
    def __init__(self, context: ContextManager, token_budget: int) -> None:
        self._context = context
        self._token_budget = token_budget

    def build(self, transcript_path: Path) -> ResumeResult:
        if not transcript_path.exists():
            return ResumeResult(
                history=[],
                message_count=0,
                restored_from_checkpoint=False,
                checkpoint_summary_chars=0,
                tail_message_count=0,
                estimated_tokens=0,
            )

        last_checkpoint: dict[str, Any] | None = None
        post_checkpoint_messages: list[dict[str, Any]] = []
        found_checkpoint = False

        with transcript_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "compaction_checkpoint":
                    last_checkpoint = event
                    post_checkpoint_messages = []
                    found_checkpoint = True
                elif event.get("type") == "message":
                    msg = _message_for_model_history(event)
                    if found_checkpoint:
                        post_checkpoint_messages.append(msg)

        if last_checkpoint:
            return self._build_from_checkpoint(last_checkpoint, post_checkpoint_messages)
        else:
            return self._build_tail_only(transcript_path)

    def _build_from_checkpoint(
        self,
        checkpoint: dict[str, Any],
        post_messages: list[dict[str, Any]],
    ) -> ResumeResult:
        summary = checkpoint.get("summary", "")
        checkpoint_msg: dict[str, Any] = {
            "role": "system",
            "content": f"Conversation summary checkpoint:\n{summary}",
        }

        history: list[dict[str, Any]] = [checkpoint_msg]
        history.extend(post_messages)
        history = self._trim_to_budget(history, keep_first=1)
        estimated = self._context.estimate_tokens(history)
        tail_count = len(history) - 1

        return ResumeResult(
            history=history,
            message_count=len(history),
            restored_from_checkpoint=True,
            checkpoint_summary_chars=len(summary),
            tail_message_count=max(tail_count, 0),
            estimated_tokens=estimated,
        )

    def _build_tail_only(self, transcript_path: Path) -> ResumeResult:
        events: list[dict[str, Any]] = []
        with transcript_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        history = self._trim_tail_to_budget(build_model_history_from_events(events))
        estimated = self._context.estimate_tokens(history)

        return ResumeResult(
            history=history,
            message_count=len(history),
            restored_from_checkpoint=False,
            checkpoint_summary_chars=0,
            tail_message_count=len(history),
            estimated_tokens=estimated,
        )

    def _trim_to_budget(
        self, history: list[dict[str, Any]], keep_first: int = 0
    ) -> list[dict[str, Any]]:
        result = list(history)
        while self._context.estimate_tokens(result) > self._token_budget and len(result) > keep_first:
            remove_idx = keep_first
            if remove_idx >= len(result):
                break
            removed = result.pop(remove_idx)
            result = self._remove_orphans(result, removed, remove_idx)
        return result

    def _trim_tail_to_budget(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = list(messages)
        while self._context.estimate_tokens(result) > self._token_budget and len(result) > 0:
            removed = result.pop(0)
            result = self._remove_orphans(result, removed, 0)
        return result

    @staticmethod
    def _remove_orphans(
        history: list[dict[str, Any]],
        removed: dict[str, Any],
        at_idx: int,
    ) -> list[dict[str, Any]]:
        if removed.get("role") == "assistant" and removed.get("tool_calls"):
            tool_ids = {tc["id"] for tc in removed["tool_calls"]}
            history = [
                m for m in history
                if not (m.get("role") == "tool" and m.get("tool_call_id") in tool_ids)
            ]
        elif removed.get("role") == "tool":
            orphan_id = removed.get("tool_call_id")
            if orphan_id:
                for i, m in enumerate(history):
                    if m.get("role") == "assistant" and m.get("tool_calls"):
                        m_tool_ids = {tc["id"] for tc in m["tool_calls"]}
                        if orphan_id in m_tool_ids:
                            m["tool_calls"] = [tc for tc in m["tool_calls"] if tc["id"] != orphan_id]
                            if not m["tool_calls"]:
                                del m["tool_calls"]
                            break
        return history


def build_model_history_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _message_for_model_history(event)
        for event in events
        if event.get("type") == "message"
    ]


def build_resume_replay_messages(transcript_path: Path | str) -> list[ResumeReplayMessage]:
    transcript = Path(transcript_path)
    if not transcript.exists():
        return []

    replay: list[ResumeReplayMessage] = []
    try:
        with transcript.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event_type == "compaction_checkpoint":
                    replay = []
                    continue
                if event_type != "message":
                    continue

                message = _message_for_resume_replay(event)
                if message is not None:
                    replay.append(message)
    except OSError:
        return []

    return replay


def _message_for_model_history(event: dict[str, Any]) -> dict[str, Any]:
    msg: dict[str, Any] = {}
    for key, value in event.items():
        if key not in ("type", "ts"):
            msg[key] = value

    metadata = msg.pop("metadata", None)
    if (
        msg.get("role") == "user"
        and isinstance(metadata, dict)
        and isinstance(metadata.get("model_content"), str)
    ):
        # Transcript keeps the visible slash command; resumed LLM history needs
        # the hidden expanded prompt that originally reached the model.
        msg["content"] = metadata["model_content"]

    return msg


def _message_for_resume_replay(event: dict[str, Any]) -> ResumeReplayMessage | None:
    role = event.get("role")
    content = event.get("content")
    if role == "user" and isinstance(content, str):
        return ResumeReplayMessage(role="user", content=content)
    if role == "assistant" and isinstance(content, str) and content:
        return ResumeReplayMessage(role="assistant", content=content)
    return None
