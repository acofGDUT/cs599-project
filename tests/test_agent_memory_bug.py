from __future__ import annotations

import builtins
import io
import json
from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from xcode_cli.core.llm import LLMResponse, ToolCall


def _setup_tmp_xcode_home(tmp_path: Path, monkeypatch) -> Path:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)

    for sub in ("sessions", "skills", "bin"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)

    (xcode_dir / "config.json").write_text(
        json.dumps({"model": "test-model", "max_tokens": 128000}),
        encoding="utf-8",
    )
    return xcode_dir


def _make_agent(tmp_path: Path, monkeypatch):
    _setup_tmp_xcode_home(tmp_path, monkeypatch)

    import xcode_cli.core.agent as agent_mod

    monkeypatch.setattr(
        agent_mod,
        "PromptSession",
        MagicMock(return_value=MagicMock()),
        raising=True,
    )
    monkeypatch.setattr(
        agent_mod,
        "AutoSuggestFromHistory",
        MagicMock(return_value=MagicMock()),
        raising=True,
    )

    from xcode_cli.core.agent import AgentRuntime

    agent = AgentRuntime()
    agent.console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
    return agent


class _FakeLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self.calls = 0

    def complete(self, **_: object) -> LLMResponse:
        response = self._responses[self.calls]
        self.calls += 1
        return response


def test_run_llm_loop_recovers_from_invalid_write_file_preview_path(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    agent.permissions.set_session_rule("write_file", "allow")

    bad_path = r"C:\Users\%USERNAME%\.xcode\projects\D:\Xcode\memory\project_tech_stack.md"
    real_open = builtins.open

    def fake_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(file) == bad_path:
            raise OSError(22, "Invalid argument")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    agent.tools._tools["write_file"].execute = lambda **kwargs: "ok"
    agent.llm = _FakeLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="write_file",
                        args={"path": bad_path, "content": "test memory"},
                    )
                ],
            ),
            LLMResponse(content="done", tool_calls=[]),
        ]
    )

    result = agent._run_llm_loop(
        history=[{"role": "user", "content": "remember this project fact"}],
        system_prompt="test prompt",
    )

    assert result == "done"

