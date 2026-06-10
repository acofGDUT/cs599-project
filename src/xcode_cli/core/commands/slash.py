from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from prompt_toolkit.completion import Completer, Completion


@dataclass(frozen=True)
class SlashCommand:
    name: str
    kind: str
    description: str
    handler: Callable[[str], object]
    source: str = "builtin"
    argument_hint: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


INIT_PROMPT = """Please analyze this codebase and create an XCODE.md file, which will be given to future instances of xcode to operate in this repository.

What to add:
1. Commands that will be commonly used, such as how to build, lint, and run tests. Include the necessary commands to develop in this codebase, such as how to run a single test.
2. High-level code architecture and structure so that future instances can be productive more quickly. Focus on the "big picture" architecture that requires reading multiple files to understand.

Usage notes:
- First use read_file to check whether XCODE.md already exists.
- If XCODE.md already exists, do not use write_file to overwrite it.
- Use edit_file to make incremental changes to an existing XCODE.md.
- If you cannot safely edit the existing XCODE.md, do not write the file. Instead, briefly suggest the improvements you would make.
- Only use write_file to create XCODE.md when read_file clearly reports that the file does not exist.
- When you make the initial XCODE.md, do not repeat yourself and do not include obvious instructions like "Provide helpful error messages to users", "Write unit tests for all new utilities", "Never include sensitive information (API keys, tokens) in code or commits".
- Avoid listing every component or file structure that can be easily discovered.
- Don't include generic development practices.
- If there are existing AI coding instructions such as AGENTS.md, CLAUDE.md, .cursor/rules/, .cursorrules, .github/copilot-instructions.md, .windsurfrules, or .clinerules, make sure to include the important parts.
- If there is a README.md, make sure to include the important parts.
- Do not make up information such as "Common Development Tasks", "Tips for Development", "Support and Documentation" unless this is expressly included in other files that you read.
- Be sure to prefix the file with the following text:

```markdown
# XCODE.md

This file provides guidance to xcode when working with code in this repository.
```

After creating or updating XCODE.md, briefly summarize what you learned about the project and which files you used as sources.
"""


def init_handler(args: str) -> str:
    return INIT_PROMPT


PROMPT_COMMANDS = {
    "/init": SlashCommand(
        name="init",
        kind="prompt",
        description="Initialize a new XCODE.md file with codebase documentation",
        handler=init_handler,
    ),
}

COMMANDS = {
    "/help": "Show available commands",
    "/init": PROMPT_COMMANDS["/init"].description,
    "/context": "Show token usage and context budget",
    "/dashboard": "Open API configuration dashboard",
    "/skill": "Manage project skills (list/show/validate)",
    "/env": "Open interactive config dashboard",
    "/plan": "Plan mode controls (enter/show/approve/reject)",
    "/memory": "Memory status and auto-memory toggle",
    "/resume": "List and resume previous sessions",
    "/compact": "Compress current conversation context",
    "/mcp": "Manage MCP servers and tools",
    "/QQchat": "Start, stop, or inspect QQ chat bridge",
    "/exit": "Exit chat",
}


class SlashCompleter(Completer):
    def __init__(self, commands: dict[str, str] | None = None) -> None:
        self._commands = commands or COMMANDS

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        if text.startswith("/init"):
            yield Completion(
                "/init",
                start_position=-len(text),
                display="/init — Initialize a new XCODE.md file with codebase documentation",
            )
            return

        if text.startswith("/dashboard"):
            yield Completion(
                "/dashboard",
                start_position=-len(text),
                display="/dashboard — Open API configuration dashboard",
            )
            return

        if text.startswith("/skill"):
            for cmd, desc in [
                ("/skill list", "List project skills"),
                ("/skill show ", "Show project skill"),
                ("/skill validate", "Validate project skills"),
            ]:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text), display=f"{cmd} — {desc}")
            return

        if text.startswith("/env"):
            yield Completion(
                "/env",
                start_position=-len(text),
                display="/env — Open interactive config dashboard",
            )
            return

        if text.startswith("/resume"):
            yield Completion("/resume", start_position=-len(text), display="/resume — List and resume previous sessions")
            return

        if text.startswith("/compact"):
            yield Completion("/compact", start_position=-len(text), display="/compact — Compress current conversation context")
            return

        if text.lower().startswith("/qqchat"):
            for cmd, desc in [
                ("/QQchat start", "Start QQ chat bridge"),
                ("/QQchat stop", "Stop QQ chat bridge"),
                ("/QQchat status", "Inspect QQ chat bridge"),
            ]:
                if cmd.lower().startswith(text.lower()):
                    yield Completion(cmd, start_position=-len(text), display=f"{cmd} - {desc}")
            return

        if text.startswith("/mcp"):
            for cmd, desc in [
                ("/mcp status", "Inspect MCP servers"),
                ("/mcp status --verbose", "Inspect MCP servers and tools"),
                ("/mcp tools", "List MCP tool catalog"),
                ("/mcp tools ", "List one MCP server tool catalog"),
                ("/mcp enable ", "Enable an MCP server in local state"),
                ("/mcp disable ", "Disable an MCP server in local state"),
                ("/mcp tool enable ", "Enable an MCP tool in local state"),
                ("/mcp tool disable ", "Disable an MCP tool in local state"),
                ("/mcp refresh", "Refresh MCP tool registration"),
                ("/mcp reconnect", "Reconnect MCP servers"),
                ("/mcp events", "Show MCP lifecycle events"),
                ("/mcp output-limit ", "Set MCP tool output limit"),
                ("/mcp trust ", "Trust an MCP server config"),
                ("/mcp untrust ", "Remove trust for an MCP server"),
                ("/mcp reload", "Reload MCP config and trusted servers"),
            ]:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text), display=f"{cmd} — {desc}")
            return

        for cmd, desc in self._commands.items():
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text), display=f"{cmd} — {desc}")
