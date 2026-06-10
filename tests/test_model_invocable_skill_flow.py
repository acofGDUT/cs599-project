from pathlib import Path
import json
from unittest.mock import MagicMock

from xcode_cli.core.llm import LLMResponse, ToolCall


def make_runtime_with_review_skill(tmp_path, monkeypatch, allowed_tools=None):
    import xcode_cli.core.agent as agent_mod
    import xcode_cli.paths
    from xcode_cli.core.agent import AgentRuntime

    project_dir = tmp_path / "project"
    skill_dir = project_dir / ".xcode" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    allowed_tools_block = ""
    if allowed_tools is not None:
        allowed_tools_block = "allowed-tools:\n" + "".join(f"  - {name}\n" for name in allowed_tools)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: Review code changes\n"
        f"{allowed_tools_block}"
        "---\n"
        "Review $ARGUMENTS\n",
        encoding="utf-8",
    )
    xcode_dir = tmp_path / ".xcode-home"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "resolve_project_root", MagicMock(return_value=str(project_dir)), raising=True)

    runtime = AgentRuntime()
    return runtime


def fake_skill_then_final_response():
    calls = [0]

    def fake_complete(system_prompt, messages, tool_schemas, on_text_token=None, on_reasoning_token=None):
        calls[0] += 1
        if calls[0] == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="skill", args={"skill": "review", "args": "src/foo.py"})],
            )
        return LLMResponse(content="review complete", tool_calls=[])

    return fake_complete


def read_session_events(runtime):
    path = runtime.sessions.transcript_path(runtime._session_id)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_skill_tool_loads_prompt_without_treating_allowed_tools_as_schema_whitelist(tmp_path, monkeypatch):
    runtime = make_runtime_with_review_skill(tmp_path, monkeypatch, allowed_tools=["read"])
    runtime._session_id = runtime.sessions.new_session_id()

    seen_schemas = []
    seen_messages = []

    def fake_complete(system_prompt, messages, tool_schemas, on_text_token=None, on_reasoning_token=None):
        seen_schemas.append([schema["function"]["name"] for schema in tool_schemas])
        seen_messages.append(messages.copy())
        if len(seen_schemas) == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="skill", args={"skill": "review", "args": "src/foo.py"})],
            )
        return LLMResponse(content="review complete", tool_calls=[])

    runtime.llm.complete = fake_complete

    runtime._run_user_turn("review src/foo.py")

    assert "skill" in seen_schemas[0]
    assert "skill" not in seen_schemas[1]
    assert "read_file" in seen_schemas[1]
    assert "grep" in seen_schemas[1]
    assert "write_file" in seen_schemas[1]
    assert any('<xcode_loaded_skill name="review"' in str(msg) for msg in seen_messages[1])


def test_skill_tool_is_removed_after_loading_even_without_allowed_tools(tmp_path, monkeypatch):
    runtime = make_runtime_with_review_skill(tmp_path, monkeypatch, allowed_tools=None)
    runtime._session_id = runtime.sessions.new_session_id()
    seen_schemas = []

    def fake_complete(system_prompt, messages, tool_schemas, on_text_token=None, on_reasoning_token=None):
        seen_schemas.append([schema["function"]["name"] for schema in tool_schemas])
        if len(seen_schemas) == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="skill", args={"skill": "review", "args": "src/foo.py"})],
            )
        return LLMResponse(content="review complete", tool_calls=[])

    runtime.llm.complete = fake_complete

    runtime._run_user_turn("review src/foo.py")

    assert "skill" in seen_schemas[0]
    assert "skill" not in seen_schemas[1]
    assert "read_file" in seen_schemas[1]


def test_blocked_skill_tool_call_is_rejected_at_execution_layer(tmp_path, monkeypatch):
    from xcode_cli.core.tool_registry import ToolOutput

    runtime = make_runtime_with_review_skill(tmp_path, monkeypatch, allowed_tools=None)
    runtime._session_id = runtime.sessions.new_session_id()
    runtime._current_blocked_tools = {"skill"}
    executed = []

    runtime.tools._tools["skill"].execute = (
        lambda **kwargs: executed.append(kwargs) or ToolOutput(content="loaded anyway")
    )

    calls = [0]

    def fake_complete(system_prompt, messages, tool_schemas, on_text_token=None, on_reasoning_token=None):
        calls[0] += 1
        if calls[0] == 1:
            assert "skill" not in [schema["function"]["name"] for schema in tool_schemas]
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_blocked", name="skill", args={"skill": "review"})],
            )
        assert any(
            msg.get("role") == "tool" and "blocked for the current turn" in str(msg.get("content", ""))
            for msg in messages
        )
        return LLMResponse(content="done", tool_calls=[])

    runtime.llm.complete = fake_complete

    result = runtime._run_llm_loop([], "system")

    assert result == "done"
    assert executed == []


def test_skill_tool_is_barrier_for_sibling_tool_calls(tmp_path, monkeypatch):
    runtime = make_runtime_with_review_skill(tmp_path, monkeypatch, allowed_tools=["read"])
    runtime._session_id = runtime.sessions.new_session_id()
    grep_calls = []
    seen_schemas = []

    runtime.tools._tools["grep"].execute = lambda **kwargs: grep_calls.append(kwargs) or "matched"

    calls = [0]

    def fake_complete(system_prompt, messages, tool_schemas, on_text_token=None, on_reasoning_token=None):
        calls[0] += 1
        seen_schemas.append([schema["function"]["name"] for schema in tool_schemas])
        if calls[0] == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="call_skill", name="skill", args={"skill": "review", "args": "src/foo.py"}),
                    ToolCall(id="call_grep", name="grep", args={"pattern": "x", "path": "."}),
                ],
            )
        assert any("<xcode_loaded_skill" in str(msg.get("content", "")) for msg in messages)
        assert any("after the loaded skill takes effect" in str(msg.get("content", "")) for msg in messages)
        return LLMResponse(content="done", tool_calls=[])

    runtime.llm.complete = fake_complete

    result = runtime._run_llm_loop([], "system")

    assert result == "done"
    assert grep_calls == []
    assert "skill" not in seen_schemas[1]
    assert "grep" in seen_schemas[1]


def test_plan_mode_system_prompt_includes_available_skill_listing(tmp_path, monkeypatch):
    runtime = make_runtime_with_review_skill(tmp_path, monkeypatch, allowed_tools=None)
    runtime._session_id = runtime.sessions.new_session_id()
    runtime.plan_mode.enter()
    runtime._run_llm_loop = MagicMock(return_value="plan ready")

    runtime._run_user_turn("plan this work")

    system_prompt = runtime._run_llm_loop.call_args.kwargs["system_prompt"]
    assert "Available skills:" in system_prompt
    assert "- review: Review code changes" in system_prompt
    assert "call the skill tool" in system_prompt


def test_skill_tool_writes_invocation_metadata_without_user_visible_prompt(tmp_path, monkeypatch):
    runtime = make_runtime_with_review_skill(tmp_path, monkeypatch, allowed_tools=["read"])
    runtime._session_id = runtime.sessions.new_session_id()
    runtime.llm.complete = fake_skill_then_final_response()

    runtime._run_user_turn("please review src/foo.py")

    events = read_session_events(runtime)
    user_event = next(e for e in events if e.get("role") == "user")
    skill_events = [e for e in events if e.get("type") == "skill_invocation"]
    assert user_event["content"] == "please review src/foo.py"
    assert "Review $ARGUMENTS" not in user_event["content"]
    assert skill_events
    assert skill_events[0]["skill"] == "review"
    assert skill_events[0]["source"] == "model"
    assert skill_events[0]["skill_source_hash"].startswith("sha256:")
    assert "model_content" not in skill_events[0]
