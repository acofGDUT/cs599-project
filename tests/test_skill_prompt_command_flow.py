import json
from pathlib import Path
from io import StringIO
from unittest.mock import MagicMock

from prompt_toolkit.document import Document
from rich.console import Console

from xcode_cli.core.commands.registry import CommandRegistry
from xcode_cli.core.commands.dispatcher import SlashCommandDispatcher
from xcode_cli.core.commands.slash import SlashCompleter
from xcode_cli.skills.loader import SkillLoader
from xcode_cli.skills.model import Skill


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=True, width=120)


def _handlers() -> dict:
    return {
        "help_handler": MagicMock(),
        "context_handler": MagicMock(),
        "dashboard_handler": MagicMock(),
        "skill_handler": MagicMock(),
        "env_handler": MagicMock(),
        "plan_handler": MagicMock(),
        "memory_handler": MagicMock(),
        "resume_handler": MagicMock(),
        "compact_handler": MagicMock(),
    }


def test_skill_dispatch_returns_user_turn_input_with_display_and_model_content():
    skill = Skill(
        name="review",
        display_name=None,
        description="Review code",
        body="Review this: $ARGUMENTS",
        root=Path("D:/Xcode/.xcode/skills/review"),
    )
    registry = CommandRegistry.from_skills([skill])
    dispatcher = SlashCommandDispatcher(
        console=_console(),
        registry=registry,
        **_handlers(),
    )

    result = dispatcher.dispatch("/review src/foo.py")

    assert result.kind == "prompt"
    assert result.turn_input.display_content == "/review src/foo.py"
    assert result.turn_input.model_content == "Review this: src/foo.py"
    assert result.turn_input.metadata["skill"] == "review"


def test_skill_dispatch_metadata_includes_source_path_and_hash(tmp_path):
    skill_dir = tmp_path / ".xcode" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "description: Review code\n"
        "---\n"
        "Review this: $ARGUMENTS\n",
        encoding="utf-8",
    )
    skill = SkillLoader(tmp_path).load().skills[0]
    registry = CommandRegistry.from_skills([skill])
    dispatcher = SlashCommandDispatcher(
        console=_console(),
        registry=registry,
        **_handlers(),
    )

    result = dispatcher.dispatch("/review src/foo.py")

    assert result.kind == "prompt"
    assert result.turn_input.metadata["source_path"] == str(skill_md)
    assert result.turn_input.metadata["skill_source_hash"].startswith("sha256:")
    assert len(result.turn_input.metadata["skill_source_hash"]) == len("sha256:") + 64


def test_context_fork_skill_prints_notice_and_is_handled():
    console = _console()
    skill = Skill(
        name="forked",
        display_name=None,
        description="Run in fork",
        body="Run elsewhere",
        root=Path("D:/Xcode/.xcode/skills/forked"),
        context="fork",
    )
    registry = CommandRegistry.from_skills([skill])
    dispatcher = SlashCommandDispatcher(
        console=console,
        registry=registry,
        **_handlers(),
    )

    result = dispatcher.dispatch("/forked")

    assert result.kind == "handled"
    assert result.turn_input is None
    assert "requires fork execution" in console.file.getvalue()


def test_loaded_skill_is_available_in_slash_completion(tmp_path):
    skill_dir = tmp_path / ".xcode" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: Review code\n"
        "argument-hint: [path]\n"
        "---\n"
        "Review this: $ARGUMENTS\n",
        encoding="utf-8",
    )
    registry = CommandRegistry.from_skills(SkillLoader(tmp_path).load().skills)
    completer = SlashCompleter(commands=registry.visible_commands())

    completions = list(completer.get_completions(Document("/"), None))

    assert any(completion.text == "/review" for completion in completions)
    assert any("Review code [path]" in str(completion.display_text) for completion in completions)


def test_skill_turn_writes_display_content_and_metadata_to_session(tmp_path, monkeypatch):
    import xcode_cli.core.agent as agent_mod
    import xcode_cli.paths
    from xcode_cli.core.agent import AgentRuntime
    from xcode_cli.core.turn import UserTurnInput

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    xcode_dir = tmp_path / ".xcode"
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    monkeypatch.setattr(agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "resolve_project_root", MagicMock(return_value=str(project_dir)), raising=True)

    runtime = AgentRuntime()
    runtime._session_id = runtime.sessions.new_session_id()
    monkeypatch.setattr(runtime, "_run_llm_loop", lambda history, system_prompt: "ok")

    turn_input = UserTurnInput(
        display_content="/review src/foo.py",
        model_content="Review this: src/foo.py",
        metadata={
            "kind": "skill_invocation",
            "skill": "review",
            "args": "src/foo.py",
            "skill_source_hash": "sha256:test",
        },
    )

    runtime._run_user_turn(turn_input)
    session_path = runtime.sessions.transcript_path(runtime._session_id)
    events = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    user_event = next(e for e in events if e["type"] == "message" and e["role"] == "user")
    assert user_event["content"] == "/review src/foo.py"
    assert user_event["metadata"]["kind"] == "skill_invocation"
    assert user_event["metadata"]["skill"] == "review"
    assert user_event["metadata"]["model_content"] == "Review this: src/foo.py"
    assert user_event["metadata"]["skill_source_hash"] == "sha256:test"
