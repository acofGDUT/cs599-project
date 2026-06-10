from __future__ import annotations

from pathlib import Path

XCODE_DIR = Path.home() / ".xcode"


def xcode_home() -> Path:
    return XCODE_DIR


def ensure_xcode_home() -> Path:
    root = XCODE_DIR
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(parents=True, exist_ok=True)
    return root
