from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class CompressionResult:
    messages: list[dict[str, Any]]
    summary: str
    checkpoint_message: dict[str, Any]


class ContextManager:
    """Manage chat history token usage with lightweight compression strategy."""

    def __init__(
        self,
        max_tokens: int = 128000,
        max_summary_chars: int | None = 6000,
    ) -> None:
        self.max_tokens = max_tokens
        self.max_summary_chars = max_summary_chars

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            parts = [str(msg.get("content", ""))]
            reasoning_content = msg.get("reasoning_content")
            if reasoning_content:
                parts.append(str(reasoning_content))
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                try:
                    parts.append(json.dumps(tool_calls, ensure_ascii=False))
                except Exception:
                    parts.append(str(tool_calls))
            tool_call_id = msg.get("tool_call_id")
            if tool_call_id:
                parts.append(str(tool_call_id))
            content = "\n".join(part for part in parts if part)
            ascii_chars = sum(1 for ch in content if ord(ch) < 128)
            non_ascii_chars = len(content) - ascii_chars
            total += int(ascii_chars / 4 + non_ascii_chars / 1.5) + 12
        return total

    def should_compress(self, messages: list[dict[str, Any]]) -> bool:
        return self.estimate_tokens(messages) >= int(self.max_tokens * 0.8)

    def compress(
        self,
        messages: list[dict[str, Any]],
        llm_client,
        previous_summary: str = "",
    ) -> CompressionResult:
        if len(messages) <= 20:
            return CompressionResult(
                messages=messages,
                summary="",
                checkpoint_message={},
            )

        first_user_idx = next((i for i, m in enumerate(messages) if m.get("role") == "user"), None)
        first_user = messages[first_user_idx] if first_user_idx is not None else None

        tail_count = 8
        tail = messages[-tail_count:]
        middle_start = (first_user_idx + 1) if first_user_idx is not None else 0
        middle_end = max(len(messages) - tail_count, middle_start)
        middle = messages[middle_start:middle_end]

        if previous_summary:
            middle = [
                m for m in middle
                if not (
                    m.get("role") == "system"
                    and "Conversation summary checkpoint:" in str(m.get("content", ""))
                )
            ]

        if not middle:
            return CompressionResult(
                messages=messages,
                summary="",
                checkpoint_message={},
            )

        if previous_summary:
            char_limit = f" under {self.max_summary_chars} characters" if self.max_summary_chars else ""
            summary_prompt = (
                "Below is a previous conversation summary and new conversation content since that summary. "
                "Produce an updated cumulative summary that merges old and new information. "
                "The new summary must preserve key decisions, constraints, file changes, errors, "
                "user preferences, pending items, current work, and next steps from BOTH the old summary "
                "and the new content. "
                f"Output only the cumulative summary text,{char_limit}."
            )
            middle_text = (
                f"Previous summary:\n{previous_summary}\n\n"
                f"New content:\n"
                + "\n".join(f"[{m.get('role','unknown')}] {m.get('content','')}" for m in middle)
            )
        else:
            char_limit = f" under {self.max_summary_chars} characters" if self.max_summary_chars else ""
            summary_prompt = (
                "Summarize the following conversation. Preserve key requirements, "
                "completed actions, pending items, constraints, file changes, errors, "
                "user preferences, current work, and next steps. "
                f"Output only the summary text,{char_limit}."
            )
            middle_text = "\n".join(f"[{m.get('role','unknown')}] {m.get('content','')}" for m in middle)

        summary_resp = llm_client.complete(
            system_prompt="You are a conversation summarization assistant.",
            messages=[{"role": "user", "content": f"{summary_prompt}\n\n{middle_text}"}],
            tool_schemas=[],
        )
        summary = summary_resp.content.strip() or "(middle conversation compressed)"

        if self.max_summary_chars and self.max_summary_chars > 0 and len(summary) > self.max_summary_chars:
            summary = summary[:self.max_summary_chars] + "...[summary truncated]"

        compressed: list[dict[str, Any]] = []
        if first_user:
            compressed.append(first_user)
        checkpoint_message: dict[str, Any] = {
            "role": "system",
            "content": f"Conversation summary checkpoint:\n{summary}",
        }
        compressed.append(checkpoint_message)
        compressed.extend(tail)

        return CompressionResult(
            messages=compressed,
            summary=summary,
            checkpoint_message=checkpoint_message,
        )
