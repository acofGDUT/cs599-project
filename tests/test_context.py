from __future__ import annotations

from pathlib import Path

from xcode_cli.core.config import Config
from xcode_cli.core.context import CompressionResult, ContextManager


class _FakeLLMClient:
    """Returns a canned English summary so we can verify compress()."""

    def __init__(self, response_text: str = "test summary") -> None:
        self.response_text = response_text
        self.calls: list[dict] = []

    def complete(self, system_prompt: str, messages: list[dict], tool_schemas: list) -> object:
        self.calls.append({
            "system_prompt": system_prompt,
            "messages": messages,
        })
        return _FakeResponse(self.response_text)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


def test_context_manager_uses_configured_max_tokens() -> None:
    cm = ContextManager(max_tokens=64000)
    assert cm.max_tokens == 64000


def test_default_max_tokens_is_128000() -> None:
    cm = ContextManager()
    assert cm.max_tokens == 128000


def test_should_compress_below_threshold() -> None:
    cm = ContextManager(max_tokens=128000)
    short = [{"role": "user", "content": "hello"}] * 5
    tokens = cm.estimate_tokens(short)
    assert tokens < 10000
    assert cm.should_compress(short) is False


def test_should_compress_above_threshold_triggers() -> None:
    cm = ContextManager(max_tokens=2000)
    many = [{"role": "user", "content": "a" * 100}] * 100
    assert cm.should_compress(many) is True


def test_should_compress_small_max_tokens() -> None:
    cm = ContextManager(max_tokens=1000)
    long_content = [{"role": "user", "content": "x" * 3000}]
    tokens = cm.estimate_tokens(long_content)
    assert cm.should_compress(long_content) is (tokens >= int(1000 * 0.8))


def test_compress_short_history_returns_unchanged() -> None:
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    result = cm.compress(msgs, llm)
    assert len(result.messages) == len(msgs)
    assert result.summary == ""
    assert result.checkpoint_message == {}
    assert llm.calls == []


def test_compress_uses_english_prompts() -> None:
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient(response_text="a concise summary")
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = cm.compress(msgs, llm)

    assert len(llm.calls) >= 1
    call = llm.calls[0]
    assert "You are a conversation summarization assistant" in call["system_prompt"]
    user_content = call["messages"][0]["content"]
    assert "Summarize the following conversation" in user_content
    assert "preserve key" in user_content.lower()

    system_msgs = [m for m in result.messages if m.get("role") == "system"]
    assert len(system_msgs) >= 1
    summary_msg = system_msgs[0]["content"]
    assert "Conversation summary checkpoint:" in summary_msg
    assert "a concise summary" in summary_msg


def test_compress_with_previous_summary_uses_cumulative_prompt() -> None:
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient(response_text="cumulative summary")
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = cm.compress(msgs, llm, previous_summary="old summary text")

    call = llm.calls[0]
    user_content = call["messages"][0]["content"]
    assert "Previous summary" in user_content
    assert "old summary text" in user_content
    assert "cumulative" in user_content.lower() or "Cumulative" in user_content


def test_compress_preserves_first_user_message() -> None:
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient("summary")
    first = {"role": "user", "content": "first message"}
    msgs = [first] + [{"role": "user", "content": f"msg {i}"} for i in range(25)]
    result = cm.compress(msgs, llm)
    assert result.messages[0]["content"] == "first message"
    assert result.messages[0]["role"] == "user"


def test_compress_preserves_tail_messages() -> None:
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient("summary")
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    tail = msgs[-8:]
    result = cm.compress(msgs, llm)
    assert result.messages[-8:] == tail


def test_compress_result_has_checkpoint_message() -> None:
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient("checkpoint test")
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = cm.compress(msgs, llm)
    assert result.checkpoint_message["role"] == "system"
    assert "Conversation summary checkpoint:" in result.checkpoint_message["content"]
    assert "checkpoint test" in result.summary


def test_estimate_tokens_includes_tool_calls() -> None:
    cm = ContextManager()
    plain = [{"role": "user", "content": "x"}]
    with_tool_calls = [{
        "role": "assistant",
        "content": "x",
        "tool_calls": [{"id": "1", "type": "function", "function": {"name": "read", "arguments": '{"path":"f.py"}'}}],
    }]
    assert cm.estimate_tokens(with_tool_calls) > cm.estimate_tokens(plain)


def test_estimate_tokens_includes_reasoning() -> None:
    cm = ContextManager()
    without = [{"role": "assistant", "content": "x"}]
    with_reasoning = [{"role": "assistant", "content": "x", "reasoning_content": "Let me think about this carefully."}]
    assert cm.estimate_tokens(with_reasoning) > cm.estimate_tokens(without)


def test_compress_empty_middle_returns_unchanged() -> None:
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient()
    msgs = [{"role": "user", "content": "hi"}] + [{"role": "assistant", "content": "hey"}] * 8
    result = cm.compress(msgs, llm)
    assert len(result.messages) == len(msgs)
    assert result.summary == ""


def test_summary_truncated_when_too_long() -> None:
    cm = ContextManager(max_tokens=128000, max_summary_chars=6000)
    long_summary = "x" * 9000
    llm = _FakeLLMClient(response_text=long_summary)
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = cm.compress(msgs, llm)

    assert len(result.summary) <= 6000 + len("...[summary truncated]")
    assert "...[summary truncated]" in result.summary
    assert result.summary in result.checkpoint_message["content"]


def test_summary_not_truncated_when_disabled() -> None:
    cm = ContextManager(max_tokens=128000, max_summary_chars=None)
    long_summary = "x" * 9000
    llm = _FakeLLMClient(response_text=long_summary)
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = cm.compress(msgs, llm)

    assert result.summary == long_summary
    assert "...[summary truncated]" not in result.summary


def test_summary_not_truncated_when_zero() -> None:
    cm = ContextManager(max_tokens=128000, max_summary_chars=0)
    long_summary = "x" * 9000
    llm = _FakeLLMClient(response_text=long_summary)
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = cm.compress(msgs, llm)

    assert result.summary == long_summary
    assert "...[summary truncated]" not in result.summary


def test_previous_summary_filters_old_checkpoint_messages() -> None:
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient("new cumulative summary")
    msgs = [{"role": "user", "content": "first"}] + [
        {"role": "system", "content": "Conversation summary checkpoint:\nold summary text"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ] + [{"role": "user", "content": f"extra {i}"} for i in range(20)]

    cm.compress(msgs, llm, previous_summary="old summary text")

    call = llm.calls[0]
    user_content = call["messages"][0]["content"]
    assert "New content:" in user_content
    new_content_section = user_content.split("New content:\n", 1)[-1]
    assert "Conversation summary checkpoint:" not in new_content_section


def test_short_history_returns_no_checkpoint() -> None:
    """4-20 messages with empty middle: compress returns no checkpoint."""
    cm = ContextManager(max_tokens=128000)
    llm = _FakeLLMClient()
    msgs = [{"role": "user", "content": "hi"}] + [
        {"role": "assistant", "content": f"msg {i}"} for i in range(8)
    ]
    result = cm.compress(msgs, llm)
    assert result.checkpoint_message == {}
    assert result.summary == ""
