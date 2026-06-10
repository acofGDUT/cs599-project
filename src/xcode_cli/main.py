from __future__ import annotations

from typing import Optional

import sys

import typer
from rich.console import Console

from xcode_cli.core.agent import AgentRuntime
from xcode_cli.core.commands.skill import SkillCommandService
from xcode_cli.core.dashboard import Dashboard
from xcode_cli.core.project_root import resolve_project_root
from xcode_cli.core.tools.files import edit_file, read_file, write_file
from xcode_cli.core.tools.search import glob as glob_files, grep
from xcode_cli.core.tools.shell import run_shell
from xcode_cli.skills.loader import SkillLoader

app = typer.Typer(
    help="Xcode CLI agent",
    invoke_without_command=True,
    no_args_is_help=False,
)
skill_app = typer.Typer(help="Manage skills")
tool_app = typer.Typer(help="Run built-in tools")
app.add_typer(skill_app, name="skill")
app.add_typer(tool_app, name="tool")

console = Console()


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        AgentRuntime().run_chat()


@app.command()
def chat() -> None:
    """Start interactive chat session."""
    AgentRuntime().run_chat()


@app.command()
def dashboard() -> None:
    """Open API configuration dashboard."""
    Dashboard().run()


@tool_app.command("run")
def tool_run(
    kind: str = typer.Argument(..., help="Tool type: read|write|edit|shell|grep|glob"),
    arg1: str = typer.Argument(..., help="Primary argument (path/pattern/command)"),
    arg2: Optional[str] = typer.Argument(None, help="Secondary argument (content/path/old_string)"),
    arg3: Optional[str] = typer.Argument(None, help="Tertiary argument (new_string for edit)"),
) -> None:
    if kind == "read":
        console.print(read_file(arg1))
    elif kind == "write":
        if arg2 is None:
            raise typer.BadParameter("write requires content as second argument")
        console.print(write_file(arg1, arg2))
    elif kind == "edit":
        if arg2 is None or arg3 is None:
            raise typer.BadParameter("edit requires old_string and new_string")
        console.print(edit_file(arg1, arg2, arg3))
    elif kind == "shell":
        console.print(run_shell(arg1))
    elif kind == "grep":
        console.print(
            "For grep/glob on PowerShell, prefer dedicated subcommands: "
            "`xcode tool grep --pattern <pattern> --path <path>`"
        )
        console.print(grep(pattern=arg1, path=arg2 or "."))
    elif kind == "glob":
        console.print(
            "For grep/glob on PowerShell, prefer dedicated subcommands: "
            "`xcode tool glob --pattern \"**/*.py\" --path <path>`"
        )
        console.print(glob_files(pattern=arg1, path=arg2 or "."))
    else:
        raise typer.BadParameter("kind must be one of: read, write, edit, shell, grep, glob")


@tool_app.command("grep")
def tool_grep(
    pattern: str = typer.Option(..., "--pattern", help="ripgrep pattern to search for"),
    path: str = typer.Option(".", "--path", help="Root path to search in"),
) -> None:
    console.print(grep(pattern=pattern, path=path))


@tool_app.command("glob")
def tool_glob(
    pattern: Optional[str] = typer.Option(None, "--pattern", help="Glob pattern, e.g. **/*.py"),
    path: str = typer.Option(".", "--path", help="Root path to search in"),
    literal_pattern: Optional[str] = typer.Option(None, "--literal-pattern", help="Literal pattern string for PowerShell wildcard issues"),
    stdin_pattern: bool = typer.Option(False, "--stdin-pattern", help="Read glob pattern from stdin (most reliable on PowerShell)"),
) -> None:
    chosen_pattern = literal_pattern or pattern

    if stdin_pattern:
        stdin_text = sys.stdin.read().strip()
        if not stdin_text:
            raise typer.BadParameter("stdin pattern is empty")
        chosen_pattern = stdin_text
        console.print("Using stdin pattern to avoid shell wildcard expansion.")
    elif literal_pattern:
        console.print("Using --literal-pattern to avoid shell wildcard expansion.")

    if not chosen_pattern:
        raise typer.BadParameter("Provide --pattern, --literal-pattern, or --stdin-pattern")

    console.print(glob_files(pattern=chosen_pattern, path=path))


def _make_skill_service() -> SkillCommandService:
    return SkillCommandService(SkillLoader(resolve_project_root(".")), console)


@skill_app.command("install")
def skill_install(path: str = typer.Argument(..., help="Local skill directory")) -> None:
    _make_skill_service().install(path)


@skill_app.command("list")
def skill_list() -> None:
    _make_skill_service().list_project_skills()


@skill_app.command("show")
def skill_show(name: str = typer.Argument(..., help="Skill name")) -> None:
    _make_skill_service().show_project_skill(name)


@skill_app.command("validate")
def skill_validate() -> None:
    _make_skill_service().validate_project_skills()


@skill_app.command("enable")
def skill_enable(name: str = typer.Argument(..., help="Skill name")) -> None:
    _make_skill_service().enable(name)


@skill_app.command("disable")
def skill_disable(name: str = typer.Argument(..., help="Skill name")) -> None:
    _make_skill_service().disable(name)


if __name__ == "__main__":
    app()
