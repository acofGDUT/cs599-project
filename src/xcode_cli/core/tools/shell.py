from __future__ import annotations

import subprocess

from xcode_cli.core.tool_registry import ToolDef


def run_shell(command: str, cwd: str | None = None, timeout: int = 120000) -> str:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout / 1000,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}ms"
    except Exception as exc:
        return f"Error: failed to run command: {exc}"

    output = []
    if proc.stdout:
        output.append(proc.stdout.strip())
    if proc.stderr:
        output.append(proc.stderr.strip())
    output.append(f"exit_code={proc.returncode}")
    return "\n".join(part for part in output if part)


RUN_SHELL_TOOL = ToolDef(
    name="run_shell",
    description="Execute a shell command in the local environment.",
    parameters={
        "command": {"type": "string", "description": "Shell command to execute."},
        "cwd": {"type": "string", "description": "Optional working directory."},
        "timeout": {"type": "integer", "description": "Timeout in milliseconds.", "default": 120000},
    },
    required=["command"],
    execute=run_shell,
    is_read_only=False,
)
