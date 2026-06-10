from __future__ import annotations

import os
from pathlib import Path

ROOT_MARKERS = (".git", "pyproject.toml", "package.json")


def _is_windows_drive_root(path: Path) -> bool:
    resolved = path.resolve()
    return resolved.parent == resolved and bool(resolved.drive)


def _looks_like_unsafe_root(path: Path) -> bool:
    resolved = path.resolve()
    if _is_windows_drive_root(resolved):
        return True
    if os.name != "nt" and str(resolved) == "/":
        return True
    return False


def _find_root_from(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        for marker in ROOT_MARKERS:
            if (candidate / marker).exists():
                return candidate
    return None


def resolve_project_root(start: str | Path | None = None, explicit_root: str | None = None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()

    env_root = os.getenv("XCODE_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()

    base = Path(start).resolve() if start else Path.cwd().resolve()
    detected = _find_root_from(base)
    return detected or base


def ensure_safe_search_root(path: str | Path) -> tuple[bool, Path]:
    resolved = Path(path).resolve()
    return (not _looks_like_unsafe_root(resolved), resolved)
