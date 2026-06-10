from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI

from xcode_cli.core.session_resume import ResumeReplayMessage
from xcode_cli.core.session_resume import SessionResumeBuilder
from xcode_cli.core.session_resume import build_resume_replay_messages
from xcode_cli.core.tooling.approval import read_key


VISIBLE_RESUME_ROWS = 9


@dataclass
class ResumeResult:
    history: list[dict[str, Any]]
    session_id: str
    restored_from_checkpoint: bool
    message_count: int
    estimated_tokens: int
    last_user_input: str | None


class ResumeCommandService:
    def __init__(self, sessions, context, console, prompt: PromptSession) -> None:
        self.sessions = sessions
        self.context = context
        self.console = console
        self.prompt = prompt

    def run(self) -> ResumeResult | None:
        sessions = self.sessions.list_sessions()
        if not sessions:
            self.console.print("No recent sessions found for this project.")
            return None

        # 非 TTY 环境回退到数字输入
        if not sys.stdin.isatty():
            return self._run_number_input(sessions)

        # TTY 环境：方向键菜单
        selected = 0
        self._render_session_list(sessions, selected)

        while True:
            key = read_key()
            if key in {"up", "k"}:
                selected = (selected - 1) % len(sessions)
                self._refresh_session_list(sessions, selected)
            elif key in {"down", "j"}:
                selected = (selected + 1) % len(sessions)
                self._refresh_session_list(sessions, selected)
            elif key == "enter":
                self.console.print()
                break
            elif key in {"escape", "q"}:
                self.console.print()
                self.console.print("Cancelled.")
                return None
            # 数字快捷键
            elif key in {str(i) for i in range(1, len(sessions) + 1)}:
                selected = int(key) - 1
                self._refresh_session_list(sessions, selected)
            elif key == "c":
                raise KeyboardInterrupt

        # 选中后执行恢复
        selected_session = sessions[selected]
        return self._restore_selected_session(selected_session)

    def _restore_selected_session(self, selected_session) -> ResumeResult | None:
        resume_budget = int(self.context.max_tokens * 0.6)
        builder = SessionResumeBuilder(self.context, resume_budget)
        result = builder.build(selected_session.path)
        if not result.history:
            self.console.print("Failed to load session history.")
            return None

        self.console.print(f"Resumed session {selected_session.session_id}")
        self.console.print(f"Restored from checkpoint: {'yes' if result.restored_from_checkpoint else 'no'}")
        self.console.print(f"Restored messages: {result.message_count}")
        self.console.print(f"Estimated context: ~{result.estimated_tokens} tokens")
        if selected_session.last_user_input:
            self.console.print(f"Latest user input: {selected_session.last_user_input[:100]}")

        replay_messages = build_resume_replay_messages(selected_session.path)
        self._render_recent_conversation(replay_messages)

        return ResumeResult(
            history=result.history,
            session_id=selected_session.session_id,
            restored_from_checkpoint=result.restored_from_checkpoint,
            message_count=result.message_count,
            estimated_tokens=result.estimated_tokens,
            last_user_input=selected_session.last_user_input,
        )

    def _run_number_input(self, sessions) -> ResumeResult | None:
        """非 TTY 环境的数字输入方式"""
        self.console.print("Recent sessions:")
        for i, s in enumerate(sessions, 1):
            ts = datetime.utcfromtimestamp(s.updated_at).strftime("%Y-%m-%d %H:%M")
            preview = self._single_line_preview(s.last_user_input, max_chars=60)
            cp_mark = " [checkpoint]" if s.has_checkpoint else ""
            self.console.print(
                f"  {i}. {s.session_id[:8]}...  {ts}  {preview}{cp_mark}",
                markup=False,
                highlight=False,
            )

        choice = self.prompt.prompt(
            ANSI("\x1b[96mSelect session number (empty to cancel)\x1b[0m ▸ ")
        ).strip()

        if not choice:
            self.console.print("Cancelled.")
            return None

        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(sessions):
                self.console.print("Invalid selection.")
                return None
        except ValueError:
            self.console.print("Invalid selection.")
            return None

        selected = sessions[idx]
        return self._restore_selected_session(selected)

    def _render_recent_conversation(self, messages: list[ResumeReplayMessage]) -> None:
        self.console.print()
        if not messages:
            self.console.print(
                "No user/assistant messages after the latest checkpoint.",
                style="dim",
                markup=False,
                highlight=False,
            )
            return

        self.console.print(
            "Recent conversation since checkpoint:",
            style="bold",
            markup=False,
            highlight=False,
        )
        for message in messages:
            label = "you" if message.role == "user" else "assistant"
            style = "bold cyan" if message.role == "user" else "bold green"
            self.console.print(label, style=style, markup=False, highlight=False)
            for line in message.content.splitlines() or [""]:
                self.console.print(f"  {line}", markup=False, highlight=False)

    def _render_session_list(self, sessions, selected: int) -> None:
        """渲染 session 列表"""
        total = len(sessions)
        start, end = self._visible_window(total, selected)
        self.console.print(f"Select session to resume: {selected + 1}/{total}", style="bold", markup=False)

        for idx in range(start, end):
            s = sessions[idx]
            ts = datetime.utcfromtimestamp(s.updated_at).strftime("%Y-%m-%d %H:%M")
            cp_mark = self._checkpoint_mark(s.has_checkpoint)
            preview = self._single_line_preview(
                s.last_user_input,
                max_chars=self._preview_width_budget(checkpoint_mark=cp_mark),
            )
            prefix = ">" if idx == selected else " "
            style = "bold cyan" if idx == selected else "dim"
            self.console.print(
                f"  {prefix} {ts}  {preview}{cp_mark}",
                style=style,
                markup=False,
                highlight=False,
            )

        for _ in range(VISIBLE_RESUME_ROWS - (end - start)):
            self.console.print("")

        self.console.print("↑/↓ move · Enter resume · Esc cancel", style="dim", markup=False)

    def _refresh_session_list(self, sessions, selected: int) -> None:
        """刷新 session 列表显示"""
        count = self._resume_menu_line_count()
        self._clear_rendered_session_list(count)
        self._render_session_list(sessions, selected)

    def _clear_rendered_session_list(self, count: int) -> None:
        sys.stdout.write(f"\x1b[{count}A")
        for _ in range(count):
            sys.stdout.write("\x1b[2K")
            sys.stdout.write("\x1b[1B")
        sys.stdout.write(f"\x1b[{count}A")
        sys.stdout.flush()

    @staticmethod
    def _visible_window(total: int, selected: int, limit: int = VISIBLE_RESUME_ROWS) -> tuple[int, int]:
        if total <= 0 or limit <= 0:
            return 0, 0
        if total <= limit:
            return 0, total
        selected = max(0, min(selected, total - 1))
        half = limit // 2
        start = max(0, selected - half)
        start = min(start, total - limit)
        return start, start + limit

    @staticmethod
    def _single_line_preview(text: str | None, max_chars: int = 60) -> str:
        normalized = " ".join(str(text or "").split())
        if not normalized:
            return "(empty)"
        return ResumeCommandService._truncate_display_width(normalized, max_chars)

    @staticmethod
    def _truncate_display_width(text: str, max_width: int) -> str:
        if max_width <= 0:
            return ""
        if ResumeCommandService._display_width(text) <= max_width:
            return text
        ellipsis = "..."
        if max_width <= len(ellipsis):
            return ellipsis[:max_width]
        target_width = max_width - len(ellipsis)
        result: list[str] = []
        current_width = 0
        for char in text:
            char_width = ResumeCommandService._char_display_width(char)
            if current_width + char_width > target_width:
                break
            result.append(char)
            current_width += char_width
        return "".join(result).rstrip() + ellipsis

    @staticmethod
    def _display_width(text: str) -> int:
        return sum(ResumeCommandService._char_display_width(char) for char in text)

    @staticmethod
    def _char_display_width(char: str) -> int:
        if unicodedata.combining(char):
            return 0
        return 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1

    @staticmethod
    def _resume_menu_line_count(limit: int = VISIBLE_RESUME_ROWS) -> int:
        return limit + 2

    def _checkpoint_mark(self, has_checkpoint: bool) -> str:
        if not has_checkpoint:
            return ""
        return " [checkpoint]" if self._console_width() >= 48 else " [cp]"

    def _preview_width_budget(self, *, checkpoint_mark: str) -> int:
        width = self._console_width()
        reserved_width = len("  > ") + len("YYYY-MM-DD HH:MM") + len("  ") + len(checkpoint_mark)
        return max(0, min(60, width - reserved_width - 1))

    def _console_width(self) -> int:
        raw_width = getattr(getattr(self.console, "size", None), "width", None)
        if isinstance(raw_width, int):
            return max(raw_width, 20)
        return 80
