from __future__ import annotations

import shutil
import subprocess
from xcode_cli.core.project_root import ensure_safe_search_root, resolve_project_root
from xcode_cli.paths import XCODE_DIR

from xcode_cli.core.tool_registry import ToolDef


def _resolve_rg_binary() -> str | None:
    import os

    bundled = XCODE_DIR / "bin" / ("rg.exe" if os.name == "nt" else "rg")
    if bundled.exists():
        return str(bundled)
    system_rg = shutil.which("rg")
    if system_rg:
        return system_rg
    return None


def grep(
    pattern: str,
    path: str = ".",
    glob_filter: str | None = None,
    output_mode: str = "content",
    head_limit: int = 250,
    offset: int = 0,
    case_insensitive: bool = False,
) -> str:
    rg_bin = _resolve_rg_binary()
    if not rg_bin:
        return "Error: rg (ripgrep) is not installed. Install it from https://github.com/BurntSushi/ripgrep"

    args = [rg_bin, "--no-heading", "-n"]

    if output_mode == "files_with_matches":
        args.append("-l")
    elif output_mode == "count":
        args.append("-c")

    if case_insensitive:
        args.append("-i")

    if glob_filter:
        args.append(f"--glob={glob_filter}")

    requested_path = path if path != "." else str(resolve_project_root())
    safe, resolved_path = ensure_safe_search_root(requested_path)
    if not safe:
        return (
            f"Error: refusing to search in filesystem root: {resolved_path}. "
            "Please specify a narrower project path."
        )

    args.extend([pattern, str(resolved_path)])

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return "Error: rg (ripgrep) is not installed. Install it from https://github.com/BurntSushi/ripgrep"
    except Exception as exc:
        return f"Error: failed to run rg: {exc}"

    if proc.returncode == 1:
        return f"No matches found for pattern: {pattern}"
    if proc.returncode not in {0, 1}:
        err = proc.stderr.strip() if proc.stderr else "unknown rg error"
        return f"Error: rg failed: {err}"

    lines = proc.stdout.splitlines()
    sliced = lines[offset : offset + head_limit]
    return "\n".join(sliced)


def glob(pattern: str, path: str = ".") -> str:
    requested_path = path if path != "." else str(resolve_project_root())
    safe, root = ensure_safe_search_root(requested_path)
    if not safe:
        return (
            f"Error: refusing to search in filesystem root: {root}. "
            "Please specify a narrower project path."
        )
    try:
        matched = [p for p in root.glob(pattern) if p.is_file()]
        matched = sorted(matched, key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception as exc:
        return f"Error: glob failed: {exc}"

    if not matched:
        return f"No files matched pattern: {pattern}"

    max_items = 500
    limited = matched[:max_items]
    out = [str(p.resolve()) for p in limited]

    if len(matched) > max_items:
        out.append(f"... truncated: showing {max_items} of {len(matched)} results")

    return "\n".join(out)


GREP_TOOL = ToolDef(
    name="grep",
    description="Search file contents using ripgrep regular expressions.",
    parameters={
        "pattern": {"type": "string", "description": "ripgrep pattern to search for."},
        "path": {"type": "string", "description": "Root path to search in.", "default": "."},
        "glob_filter": {"type": "string", "description": "Optional file glob filter, e.g. *.py."},
        "output_mode": {
            "type": "string",
            "enum": ["content", "files_with_matches", "count"],
            "default": "content",
        },
        "head_limit": {"type": "integer", "default": 250},
        "offset": {"type": "integer", "default": 0},
        "case_insensitive": {"type": "boolean", "default": False},
    },
    required=["pattern"],
    execute=grep,
    is_read_only=True,
)

GLOB_TOOL = ToolDef(
    name="glob",
    description="Find files by glob pattern under a directory.",
    parameters={
        "pattern": {"type": "string", "description": "Glob pattern such as **/*.py."},
        "path": {"type": "string", "description": "Root path to search in.", "default": "."},
    },
    required=["pattern"],
    execute=glob,
    is_read_only=True,
)
