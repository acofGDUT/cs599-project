from __future__ import annotations

from pathlib import Path

from xcode_cli.core.tool_registry import ToolDef


def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {path}"

    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: cannot read binary file: {path}"
    except Exception as exc:
        return f"Error: failed to read file {path}: {exc}"

    lines = text.splitlines()
    total = len(lines)
    start = max(offset, 0)
    end = start + max(limit, 0)
    sliced = lines[start:end]

    numbered = [f"{idx}\t{line}" for idx, line in enumerate(sliced, start=start + 1)]
    output = "\n".join(numbered)

    if end < total:
        output = f"{output}\n## Total lines: {total}" if output else f"## Total lines: {total}"

    return output


def write_file(path: str, content: str, append: bool = False) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if append and p.exists():
        existing = p.read_text(encoding="utf-8").rstrip()
        payload = f"{existing}\n{content.strip()}\n"
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(content, encoding="utf-8")
    return f"Wrote {p}"


def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    if new_string == old_string:
        return "Error: new_string must be different from old_string"

    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {path}"

    try:
        original = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: cannot read binary file: {path}"
    except Exception as exc:
        return f"Error: failed to read file {path}: {exc}"

    count = original.count(old_string)

    if not replace_all:
        if count == 0:
            preview = read_file(path=path, offset=0, limit=2000)
            return f"Error: old_string not found in file. File content:\n{preview}"
        if count > 1:
            return (
                f"Error: old_string found {count} times in file. "
                "Use more context to make it unique, or set replace_all=true"
            )
        updated = original.replace(old_string, new_string, 1)
        replacements = 1
    else:
        if count == 0:
            preview = read_file(path=path, offset=0, limit=2000)
            return f"Error: old_string not found in file. File content:\n{preview}"
        updated = original.replace(old_string, new_string)
        replacements = count

    p.write_text(updated, encoding="utf-8")
    return f"Edited {p}: replaced {replacements} occurrence(s)"


READ_FILE_TOOL = ToolDef(
    name="read_file",
    description="Read file content with line pagination.",
    parameters={
        "path": {"type": "string", "description": "Absolute file path to read."},
        "offset": {"type": "integer", "description": "Start line offset (0-indexed).", "default": 0},
        "limit": {"type": "integer", "description": "Maximum lines to read.", "default": 2000},
    },
    required=["path"],
    execute=read_file,
    is_read_only=True,
)

WRITE_FILE_TOOL = ToolDef(
    name="write_file",
    description="Write text content to a file, creating parent directories if needed.",
    parameters={
        "path": {"type": "string", "description": "Absolute file path to write."},
        "content": {"type": "string", "description": "Text content to write."},
        "append": {"type": "boolean", "description": "Append to file instead of overwriting.", "default": False},
    },
    required=["path", "content"],
    execute=write_file,
    is_read_only=False,
)

EDIT_FILE_TOOL = ToolDef(
    name="edit_file",
    description="Safely edit an existing file by exact string replacement.",
    parameters={
        "path": {"type": "string", "description": "Absolute file path to edit."},
        "old_string": {"type": "string", "description": "Exact string to replace."},
        "new_string": {"type": "string", "description": "Replacement string."},
        "replace_all": {
            "type": "boolean",
            "description": "Replace all occurrences; otherwise old_string must be unique.",
            "default": False,
        },
    },
    required=["path", "old_string", "new_string"],
    execute=edit_file,
    is_read_only=False,
)
