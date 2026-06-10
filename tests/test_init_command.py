from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from prompt_toolkit.document import Document

from xcode_cli.core.commands.slash import INIT_PROMPT, PROMPT_COMMANDS, SlashCompleter, init_handler


def test_init_handler_returns_repository_initialization_prompt() -> None:
    prompt = init_handler("")

    assert prompt == INIT_PROMPT
    assert "create an XCODE.md file" in prompt
    assert "future instances of xcode" in prompt
    assert "AGENTS.md" in prompt
    assert "CLAUDE.md" in prompt
    assert ".github/copilot-instructions.md" in prompt
    assert "README.md" in prompt
    assert "# XCODE.md" in prompt
    assert "This file provides guidance to xcode" in prompt
    assert "which files you used as sources" in prompt


def test_init_prompt_protects_existing_xcode_md_from_overwrite() -> None:
    prompt = init_handler("")

    assert "First use read_file to check whether XCODE.md already exists." in prompt
    assert "If XCODE.md already exists, do not use write_file to overwrite it." in prompt
    assert "Use edit_file to make incremental changes to an existing XCODE.md." in prompt
    assert "If you cannot safely edit the existing XCODE.md, do not write the file." in prompt
    assert "Only use write_file to create XCODE.md when read_file clearly reports that the file does not exist." in prompt


def test_init_is_registered_as_prompt_command() -> None:
    command = PROMPT_COMMANDS["/init"]

    assert command.name == "init"
    assert command.kind == "prompt"
    assert command.description == "Initialize a new XCODE.md file with codebase documentation"
    assert command.handler("") == INIT_PROMPT


def test_slash_completer_includes_init() -> None:
    completer = SlashCompleter()
    completions = list(completer.get_completions(Document("/in"), None))

    assert any(completion.text == "/init" for completion in completions)
    assert any("Initialize a new XCODE.md" in str(completion.display_text) for completion in completions)


def test_slash_completer_includes_dynamic_skill_command() -> None:
    completer = SlashCompleter(commands={"/review": "Review code [path]"})
    completions = list(completer.get_completions(Document("/re"), None))

    assert any(completion.text == "/review" for completion in completions)
    assert any("Review code [path]" in str(completion.display_text) for completion in completions)


def _setup_tmp_xcode_home(tmp_path: Path, monkeypatch) -> Path:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    xcode_dir.mkdir(parents=True, exist_ok=True)
    (xcode_dir / "config.json").write_text(
        json.dumps({"model": "test-model", "api_key": "test-key"}),
        encoding="utf-8",
    )
    for subdir in ("sessions", "skills", "bin"):
        (xcode_dir / subdir).mkdir(parents=True, exist_ok=True)
    return xcode_dir


def _make_agent(tmp_path: Path, monkeypatch):
    import xcode_cli.core.agent as agent_mod

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    _setup_tmp_xcode_home(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_mod, "PromptSession", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "AutoSuggestFromHistory", MagicMock(return_value=MagicMock()), raising=True)
    monkeypatch.setattr(agent_mod, "resolve_project_root", MagicMock(return_value=str(project_dir)), raising=True)

    from xcode_cli.core.agent import AgentRuntime

    agent = AgentRuntime()
    agent._session_id = "test-session"
    agent._history = []
    return agent


def test_handle_slash_command_returns_init_prompt(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)

    result = agent._handle_slash_command("/init")

    assert result is not None
    assert result.display_content == "/init"
    assert result.model_content == INIT_PROMPT
    assert agent._history == []


def test_run_chat_feeds_init_prompt_through_normal_user_turn(tmp_path: Path, monkeypatch) -> None:
    agent = _make_agent(tmp_path, monkeypatch)
    # 隔离网络依赖：render_welcome → ensure_ripgrep_installed 会尝试从 GitHub 下载 rg
    monkeypatch.setattr("xcode_cli.core.ui.shell.ensure_ripgrep_installed", lambda: None)
    prompts = iter(["/init", "/exit"])
    agent.prompt.prompt.side_effect = lambda *args, **kwargs: next(prompts)
    agent._run_llm_loop = MagicMock(return_value="created XCODE.md")

    agent.run_chat()

    assert agent._run_llm_loop.call_count == 1
    assert agent._history[0] == {"role": "user", "content": INIT_PROMPT}
    assert agent._history[1] == {"role": "assistant", "content": "created XCODE.md"}


def test_shell_command_suggestions_include_init(tmp_path: Path, monkeypatch) -> None:
    from io import StringIO

    from rich.console import Console

    from xcode_cli.core.ui.shell import ShellUI

    agent = _make_agent(tmp_path, monkeypatch)
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    shell = ShellUI(
        console=console,
        config_store=agent.config_store,
        context=agent.context,
        session_start_getter=lambda: 0.0,
        tool_count_getter=lambda: 0,
        token_getter=lambda: 0,
        cwd=agent.cwd,
    )

    shell.show_command_suggestions()

    rendered = output.getvalue()
    assert "/init" in rendered
    assert "Initialize a new XCODE.md" in rendered


def test_shell_command_suggestions_include_dynamic_skill_command(tmp_path: Path, monkeypatch) -> None:
    from io import StringIO

    from rich.console import Console

    from xcode_cli.core.ui.shell import ShellUI

    agent = _make_agent(tmp_path, monkeypatch)
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    shell = ShellUI(
        console=console,
        config_store=agent.config_store,
        context=agent.context,
        session_start_getter=lambda: 0.0,
        tool_count_getter=lambda: 0,
        token_getter=lambda: 0,
        cwd=agent.cwd,
    )

    shell.show_command_suggestions(commands={"/review": "Review code [path]"})

    rendered = output.getvalue()
    assert "/review" in rendered
    assert "Review code [path]" in rendered
