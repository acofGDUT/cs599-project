from __future__ import annotations

import json
from pathlib import Path

from xcode_cli.core.agent import AgentRuntime
from xcode_cli.core.llm import LLMResponse, ToolCall


def _setup_tmp_xcode_home(tmp_path: Path, monkeypatch) -> Path:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    xcode_dir.mkdir(parents=True, exist_ok=True)
    (xcode_dir / "config.json").write_text(
        json.dumps({"model": "test", "auto_memory": True}),
        encoding="utf-8",
    )
    for sub in ("sessions", "skills", "bin"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)
    return xcode_dir


def _make_agent(tmp_path: Path, monkeypatch) -> AgentRuntime:
    """Create AgentRuntime against a temp project dir with temp xcode home."""
    import xcode_cli.core.agent as agent_mod
    from unittest.mock import MagicMock

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    _setup_tmp_xcode_home(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True,
    )
    monkeypatch.setattr(
        agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True,
    )
    monkeypatch.setattr(
        agent_mod, "resolve_project_root", MagicMock(return_value=str(project_dir)), raising=True,
    )
    agent = AgentRuntime()
    agent._session_id = "test-session"
    return agent


def _single_tool_call_llm(tool_calls: list[ToolCall]) -> object:
    """Return a callable that produces tool_calls on first call, final text after."""
    counter = [0]

    def complete(**kwargs):
        counter[0] += 1
        if counter[0] == 1:
            return LLMResponse(content="", tool_calls=tool_calls)
        return LLMResponse(content="done", tool_calls=[])

    return complete


# ---------------------------------------------------------------------------
# memory write bypass — write_file
# ---------------------------------------------------------------------------

def test_write_file_to_auto_memory_bypasses_user_approval(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    memory_path = agent.memory.memory_dir_path() / "project_tech_stack.md"
    approvals: list[str] = []
    executed: list[dict] = []

    def fake_approval(tool_name: str, scope: str | None) -> str:
        approvals.append(f"{tool_name}:{scope}")
        return "no"

    monkeypatch.setattr(agent.approval, "prompt", fake_approval)
    agent.tools._tools["write_file"].execute = lambda **kwargs: executed.append(kwargs) or "ok"
    agent.llm.complete = _single_tool_call_llm([
        ToolCall(
            id="call_memory",
            name="write_file",
            args={"path": str(memory_path), "content": "memory body"},
        )
    ])

    result = agent._run_llm_loop([], "system")

    assert result == "done"
    assert approvals == []
    assert executed == [{"path": str(memory_path), "content": "memory body"}]


def test_edit_file_to_project_memory_bypasses_user_approval(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    memory_path = agent.memory.project_memory_path()
    memory_path.write_text("old", encoding="utf-8")
    approvals: list[str] = []
    executed: list[dict] = []

    monkeypatch.setattr(
        agent.approval,
        "prompt",
        lambda tool_name, scope: approvals.append(f"{tool_name}:{scope}") or "no",
    )
    agent.tools._tools["edit_file"].execute = lambda **kwargs: executed.append(kwargs) or "edited"
    agent.llm.complete = _single_tool_call_llm([
        ToolCall(
            id="call_project_memory",
            name="edit_file",
            args={
                "path": str(memory_path),
                "old_string": "old",
                "new_string": "new",
            },
        )
    ])

    agent._run_llm_loop([], "system")

    assert approvals == []
    assert executed == [
        {
            "path": str(memory_path),
            "old_string": "old",
            "new_string": "new",
        }
    ]


def test_write_file_to_normal_project_file_still_asks(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    normal_path = Path(agent.cwd) / "src" / "app.py"
    approvals: list[str] = []
    executed: list[dict] = []

    monkeypatch.setattr(
        agent.approval,
        "prompt",
        lambda tool_name, scope: approvals.append(f"{tool_name}:{scope}") or "no",
    )
    agent.tools._tools["write_file"].execute = lambda **kwargs: executed.append(kwargs) or "ok"
    agent.llm.complete = _single_tool_call_llm([
        ToolCall(
            id="call_normal",
            name="write_file",
            args={"path": str(normal_path), "content": "print('hi')"},
        )
    ])

    agent._run_llm_loop([], "system")

    assert approvals == ["write_file:write"]
    assert executed == []


def test_invalid_memory_like_path_still_asks(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    bad_path = r"C:\Users\%USERNAME%\.xcode\projects\D:\Xcode\memory\project_tech_stack.md"
    approvals: list[str] = []
    executed: list[dict] = []

    monkeypatch.setattr(
        agent.approval,
        "prompt",
        lambda tool_name, scope: approvals.append(f"{tool_name}:{scope}") or "no",
    )
    agent.tools._tools["write_file"].execute = lambda **kwargs: executed.append(kwargs) or "ok"
    agent.llm.complete = _single_tool_call_llm([
        ToolCall(
            id="call_bad",
            name="write_file",
            args={"path": bad_path, "content": "bad memory"},
        )
    ])

    agent._run_llm_loop([], "system")

    assert approvals == ["write_file:write"]
    assert executed == []


# ---------------------------------------------------------------------------
# explicit deny regression (Batch 0 safety net)
# ---------------------------------------------------------------------------

def test_explicit_deny_memory_write_does_not_execute(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    memory_path = agent.memory.memory_dir_path() / "project_tech_stack.md"
    executed: list[dict] = []
    approvals: list[str] = []

    agent.permissions.set_session_rule("write_file", "deny")
    monkeypatch.setattr(
        agent.approval,
        "prompt",
        lambda tool_name, scope: approvals.append(f"{tool_name}:{scope}") or "yes",
    )
    agent.tools._tools["write_file"].execute = lambda **kwargs: executed.append(kwargs) or "ok"
    agent.llm.complete = _single_tool_call_llm([
        ToolCall(
            id="call_denied_memory",
            name="write_file",
            args={"path": str(memory_path), "content": "memory body"},
        )
    ])

    result = agent._run_llm_loop([], "system")

    assert result == "done"
    assert approvals == []
    assert executed == []
