from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

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
    import xcode_cli.core.agent as agent_mod

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


def _single_tool_call_llm(tool_calls: list[ToolCall]):
    counter = [0]

    def complete(**kwargs):
        counter[0] += 1
        if counter[0] == 1:
            return LLMResponse(content="", tool_calls=tool_calls)
        return LLMResponse(content="done", tool_calls=[])

    return complete


def test_render_task_panel_with_tasks(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    agent.task_tracker.create(subject="添加用户认证", description="desc1")
    agent.task_tracker.create(subject="修复登录 bug", description="desc2")

    printed: list[str] = []
    agent.console.print = lambda *args, **kwargs: printed.append(str(args[0]) if args else "")

    agent.llm.complete = _single_tool_call_llm([
        ToolCall(id="c1", name="task_create", args={"subject": "新任务", "description": "desc"}),
    ])

    agent._run_llm_loop([], "system")

    panel_output = " ".join(printed)
    assert "Tasks" in panel_output
    assert "添加用户认证" in panel_output
    assert "修复登录 bug" in panel_output
    assert "新任务" in panel_output


def test_render_task_panel_all_deleted(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    task = agent.task_tracker.create(subject="临时任务", description="desc")
    agent.task_tracker.update(task.id, "deleted")

    printed: list[str] = []
    agent.console.print = lambda *args, **kwargs: printed.append(str(args[0]) if args else "")

    agent.llm.complete = _single_tool_call_llm([
        ToolCall(id="c1", name="task_update", args={"task_id": task.id, "status": "deleted"}),
    ])

    agent._run_llm_loop([], "system")

    panel_output = " ".join(printed)
    assert "Tasks" not in panel_output


def test_render_task_panel_no_task_tool(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    agent.task_tracker.create(subject="某个任务", description="desc")

    printed: list[str] = []
    agent.console.print = lambda *args, **kwargs: printed.append(str(args[0]) if args else "")

    agent.llm.complete = _single_tool_call_llm([
        ToolCall(id="c1", name="read_file", args={"path": "/tmp/test.txt"}),
    ])
    agent.tools._tools["read_file"].execute = lambda **kwargs: "file content"

    agent._run_llm_loop([], "system")

    panel_output = " ".join(printed)
    assert "Tasks" not in panel_output


def test_render_task_panel_status_icons(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    t1 = agent.task_tracker.create(subject="待办任务", description="desc")
    t2 = agent.task_tracker.create(subject="进行中任务", description="desc")
    t3 = agent.task_tracker.create(subject="已完成任务", description="desc")
    agent.task_tracker.update(t2.id, "in_progress")
    agent.task_tracker.update(t3.id, "completed")

    printed: list[str] = []
    agent.console.print = lambda *args, **kwargs: printed.append(str(args[0]) if args else "")

    agent.llm.complete = _single_tool_call_llm([
        ToolCall(id="c1", name="task_create", args={"subject": "触发渲染", "description": "desc"}),
    ])

    agent._run_llm_loop([], "system")

    panel_output = " ".join(printed)
    assert "◻" in panel_output
    assert "◐" in panel_output
    assert "✓" in panel_output
