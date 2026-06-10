from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from xcode_cli.core.conversation.compaction import ConversationCompactor


class TestCompactHistoryProgress:
    """测试 compact_history 的进度显示功能"""

    def test_compact_history_shows_live_progress(self, tmp_path):
        """压缩成功时显示 Live 进度"""
        mock_context = MagicMock()
        mock_context.estimate_tokens.return_value = 100
        mock_context.compress.return_value = MagicMock(
            checkpoint_message={"role": "system", "content": "summary"},
            messages=[{"role": "system", "content": "summary"}],
            summary="test summary"
        )

        mock_llm = MagicMock()
        mock_sessions = MagicMock()
        mock_console = MagicMock()

        compactor = ConversationCompactor(mock_context, mock_llm, mock_sessions, mock_console)
        history = [{"role": "user", "content": "test"}]

        with patch('xcode_cli.core.conversation.compaction.Live') as mock_live_cls:
            mock_live = MagicMock()
            mock_live_cls.return_value = mock_live

            result = compactor.compact_history(history)

            # 验证 Live 被创建和启动
            mock_live_cls.assert_called_once()
            mock_live.start.assert_called_once()
            mock_live.stop.assert_called_once()
            assert result is not None

    def test_compact_history_stops_live_on_exception(self, tmp_path):
        """compress() 抛异常时 Live 仍然停止"""
        mock_context = MagicMock()
        mock_context.estimate_tokens.return_value = 100
        mock_context.compress.side_effect = Exception("LLM error")

        mock_llm = MagicMock()
        mock_sessions = MagicMock()
        mock_console = MagicMock()

        compactor = ConversationCompactor(mock_context, mock_llm, mock_sessions, mock_console)
        history = [{"role": "user", "content": "test"}]

        with patch('xcode_cli.core.conversation.compaction.Live') as mock_live_cls:
            mock_live = MagicMock()
            mock_live_cls.return_value = mock_live

            with pytest.raises(Exception, match="LLM error"):
                compactor.compact_history(history)

            # 即使异常，Live 也应该停止
            mock_live.start.assert_called_once()
            mock_live.stop.assert_called_once()

    def test_compact_history_no_checkpoint_no_live(self, tmp_path):
        """Nothing to compact 路径不启动 Live"""
        mock_context = MagicMock()
        mock_context.estimate_tokens.return_value = 100
        mock_context.compress.return_value = MagicMock(
            checkpoint_message=None,
            messages=[],
            summary=""
        )

        mock_llm = MagicMock()
        mock_sessions = MagicMock()
        mock_console = MagicMock()

        compactor = ConversationCompactor(mock_context, mock_llm, mock_sessions, mock_console)
        history = [{"role": "user", "content": "test"}]

        with patch('xcode_cli.core.conversation.compaction.Live') as mock_live_cls:
            mock_live = MagicMock()
            mock_live_cls.return_value = mock_live

            result = compactor.compact_history(history)

            # 即使没有 checkpoint，Live 也会被启动（因为 compress 被调用了）
            # 但结果应该是 None
            assert result is None
            mock_live.start.assert_called_once()
            mock_live.stop.assert_called_once()

    def test_compaction_keeps_loaded_skill_marker_in_source_history(self, tmp_path):
        captured = {}

        class FakeContext:
            def estimate_tokens(self, history):
                return len(str(history))

            def compress(self, history, llm, previous_summary):
                captured["history"] = history
                return MagicMock(
                    messages=history,
                    summary="summary",
                    checkpoint_message={"role": "system", "content": "Conversation summary checkpoint:\nsummary"},
                )

        history = [
            {"role": "user", "content": "please review src/foo.py"},
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "<xcode_loaded_skill name=\"review\">Review src/foo.py</xcode_loaded_skill>",
            },
        ]
        compactor = ConversationCompactor(FakeContext(), MagicMock(), MagicMock(), MagicMock())

        compactor.compact_history(history)

        assert any("<xcode_loaded_skill name=\"review\"" in str(message) for message in captured["history"])
