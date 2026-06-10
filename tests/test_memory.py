from __future__ import annotations

import json
from pathlib import Path

import pytest

from xcode_cli.core.config import Config


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_xcode_home(tmp_path: Path, monkeypatch) -> Path:
    """Point XCODE_DIR at a temp directory."""
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    for sub in ("sessions", "skills", "bin"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)
    return xcode_dir


def _make_memory_manager(
    tmp_path: Path, monkeypatch, project_name: str = "myproject"
):
    """Create a MemoryManager against a temp project dir and temp xcode home."""
    xcode_dir = _setup_xcode_home(tmp_path, monkeypatch)
    project_dir = tmp_path / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    from xcode_cli.core.memory import MemoryManager

    return MemoryManager(cwd=str(project_dir))


# ---------------------------------------------------------------------------
# path resolution
# ---------------------------------------------------------------------------

class TestMemoryPaths:
    def test_user_memory_path(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        assert mm.user_memory_path() == mm.xcode_home / "XCODE.md"

    def test_project_memory_path(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="myapp")
        assert mm.project_memory_path() == mm.cwd / "XCODE.md"
        assert mm.project_memory_path().name == "XCODE.md"
        assert mm.project_memory_path().parent == mm.cwd

    def test_memory_dir_path(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        expected = mm.xcode_home / "projects" / "demo" / "memory"
        assert mm.memory_dir_path() == expected

    def test_memory_index_path(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        assert mm.memory_index_path() == mm.memory_dir_path() / "MEMORY.md"

    def test_memory_dir_created_on_init(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        assert mm.memory_dir_path().exists()
        assert mm.memory_dir_path().is_dir()


# ---------------------------------------------------------------------------
# exists checks
# ---------------------------------------------------------------------------

class TestMemoryExists:
    def test_has_user_memory_true(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.user_memory_path().write_text("hello", encoding="utf-8")
        assert mm.has_user_memory() is True

    def test_has_user_memory_false(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        assert mm.has_user_memory() is False

    def test_has_project_memory_true(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.project_memory_path().write_text("hello", encoding="utf-8")
        assert mm.has_project_memory() is True

    def test_has_project_memory_false(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        assert mm.has_project_memory() is False


# ---------------------------------------------------------------------------
# read / write
# ---------------------------------------------------------------------------

class TestMemoryReadWrite:
    def test_read_user_memory_returns_content(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.user_memory_path().write_text("  user pref content  ", encoding="utf-8")
        assert mm.read_user_memory() == "user pref content"

    def test_read_user_memory_empty_when_missing(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        assert mm.read_user_memory() == ""

    def test_read_project_memory_returns_content(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.project_memory_path().write_text("  project rules  ", encoding="utf-8")
        assert mm.read_project_memory() == "project rules"

    def test_read_project_memory_empty_when_missing(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        assert mm.read_project_memory() == ""

    def test_write_user_memory_new_file(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_user_memory("## About\n- Python dev", append=False)
        content = mm.user_memory_path().read_text(encoding="utf-8").strip()
        assert "Python dev" in content

    def test_write_user_memory_append(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_user_memory("line one", append=False)
        mm.write_user_memory("line two", append=True)
        content = mm.read_user_memory()
        assert "line one" in content
        assert "line two" in content

    def test_write_project_memory_append(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_project_memory("rule 1", append=False)
        mm.write_project_memory("rule 2", append=True)
        content = mm.read_project_memory()
        assert "rule 1" in content
        assert "rule 2" in content

    def test_write_empty_content_is_noop(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_user_memory("   ", append=False)
        assert mm.has_user_memory() is False

    def test_read_memory_index_empty(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        assert mm.read_memory_index() == ""

    def test_read_memory_index_returns_content(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.memory_index_path().parent.mkdir(parents=True, exist_ok=True)
        mm.memory_index_path().write_text(
            "- [Role](feedback_role.md) — coding agent role\n", encoding="utf-8"
        )
        content = mm.read_memory_index()
        assert "feedback_role.md" in content


# ---------------------------------------------------------------------------
# get_context_for_prompt
# ---------------------------------------------------------------------------

class TestGetContextForPrompt:
    def test_includes_project_memory(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_project_memory("## Project Rules\n- No asyncio", append=False)
        ctx = mm.get_context_for_prompt(Config())
        assert "Project Memory" in ctx
        assert "No asyncio" in ctx

    def test_includes_user_memory(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_user_memory("## About\n- Senior dev", append=False)
        ctx = mm.get_context_for_prompt(Config())
        assert "User Memory" in ctx
        assert "Senior dev" in ctx

    def test_includes_auto_memory_index_when_enabled(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.memory_index_path().parent.mkdir(parents=True, exist_ok=True)
        mm.memory_index_path().write_text(
            "- [Role](feedback_role.md) — coding agent\n", encoding="utf-8"
        )
        cfg = Config(auto_memory=True)
        ctx = mm.get_context_for_prompt(cfg)
        assert "Auto Memory Index" in ctx
        assert "feedback_role.md" in ctx

    def test_skips_auto_memory_index_when_disabled(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.memory_index_path().parent.mkdir(parents=True, exist_ok=True)
        mm.memory_index_path().write_text(
            "- [Role](feedback_role.md) — coding agent\n", encoding="utf-8"
        )
        cfg = Config(auto_memory=False)
        ctx = mm.get_context_for_prompt(cfg)
        assert "Auto Memory Index" not in ctx

    def test_empty_when_no_memory(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        ctx = mm.get_context_for_prompt(Config(auto_memory=True))
        assert ctx == ""

    def test_auto_memory_block_is_index_only(self, tmp_path: Path, monkeypatch) -> None:
        """Auto memory block injects index, not individual .md file bodies."""
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.memory_dir_path().mkdir(parents=True, exist_ok=True)
        mm.memory_index_path().write_text("- [One](one.md) — first\n", encoding="utf-8")
        # Write an actual .md file body in the memory dir
        (mm.memory_dir_path() / "one.md").write_text(
            "---\nname: one\ndescription: test\nmetadata:\n  type: feedback\n---\nBody text here.\n",
            encoding="utf-8",
        )
        cfg = Config(auto_memory=True)
        ctx = mm.get_context_for_prompt(cfg)
        assert "Auto Memory Index" in ctx
        assert "one.md" in ctx  # index entry
        assert "Body text here" not in ctx  # file body NOT injected


# ---------------------------------------------------------------------------
# truncation
# ---------------------------------------------------------------------------

class TestTruncation:
    def test_long_content_truncated(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_project_memory("x" * 3000, append=False)
        ctx = mm.get_context_for_prompt(Config())
        assert "...[truncated]" in ctx
        assert len(ctx) <= 5000 + len("\n...[truncated]")

    def test_short_content_not_truncated(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_project_memory("short rule", append=False)
        ctx = mm.get_context_for_prompt(Config())
        assert "short rule" in ctx
        assert "...[truncated]" not in ctx

    def test_context_total_not_exceeds_5000(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        mm.write_project_memory("P" * 2500, append=False)
        mm.write_user_memory("U" * 2500, append=False)
        ctx = mm.get_context_for_prompt(Config(auto_memory=False))
        assert len(ctx) <= 5000 + len("\n...[truncated]")

    def test_is_auto_memory_enabled(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch)
        assert mm.is_auto_memory_enabled(Config(auto_memory=True)) is True
        assert mm.is_auto_memory_enabled(Config(auto_memory=False)) is False


# ---------------------------------------------------------------------------
# memory write target detection
# ---------------------------------------------------------------------------


class TestMemoryWriteTargets:
    def test_project_xcode_is_memory_write_target(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        assert mm.is_memory_write_target(str(mm.project_memory_path())) is True

    def test_user_xcode_is_memory_write_target(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        assert mm.is_memory_write_target(str(mm.user_memory_path())) is True

    def test_auto_memory_file_is_memory_write_target(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        target = mm.memory_dir_path() / "project_tech_stack.md"
        assert mm.is_memory_write_target(str(target)) is True

    def test_memory_index_is_memory_write_target(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        assert mm.is_memory_write_target(str(mm.memory_index_path())) is True

    def test_non_memory_project_file_is_not_memory_write_target(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        target = mm.cwd / "src" / "app.py"
        assert mm.is_memory_write_target(str(target)) is False

    def test_sibling_of_memory_dir_is_not_memory_write_target(self, tmp_path: Path, monkeypatch) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        target = mm.memory_dir_path().parent / "memory_notes.md"
        assert mm.is_memory_write_target(str(target)) is False

    def test_invalid_windows_memory_like_path_is_not_memory_write_target(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        mm = _make_memory_manager(tmp_path, monkeypatch, project_name="demo")
        bad_path = r"C:\Users\%USERNAME%\.xcode\projects\D:\Xcode\memory\project_tech_stack.md"
        assert mm.is_memory_write_target(bad_path) is False
