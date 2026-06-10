from __future__ import annotations

from pathlib import Path

from xcode_cli.core.config import Config


def test_build_system_prompt_does_not_inject_enabled_skill_files(tmp_path, monkeypatch):
    from xcode_cli.core.config import Config
    from xcode_cli.core.prompting import build_system_prompt

    _setup_xcode_home(tmp_path, monkeypatch)
    cfg = Config()
    assert not hasattr(cfg, "enabled_skills")

    prompt = build_system_prompt(cfg, cwd=str(tmp_path))

    assert "Enabled skills:" not in prompt


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_xcode_home(tmp_path: Path, monkeypatch) -> Path:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    for sub in ("sessions", "skills", "bin"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)
    return xcode_dir


def _make_memory_manager(tmp_path: Path, monkeypatch, cwd: str):
    _setup_xcode_home(tmp_path, monkeypatch)
    from xcode_cli.core.memory import MemoryManager

    return MemoryManager(cwd=cwd)


# ---------------------------------------------------------------------------
# build_system_prompt — memory integration
# ---------------------------------------------------------------------------

class TestBuildSystemPromptMemory:
    def test_includes_memory_context_when_files_exist(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from xcode_cli.core.prompting import build_system_prompt

        project_dir = tmp_path / "myapp"
        project_dir.mkdir(parents=True, exist_ok=True)
        mm = _make_memory_manager(tmp_path, monkeypatch, cwd=str(project_dir))

        mm.write_project_memory("## Project Rules\n- No asyncio", append=False)
        mm.write_user_memory("## About\n- Senior Python dev", append=False)

        cfg = Config(auto_memory=False)
        prompt = build_system_prompt(cfg, cwd=str(project_dir))

        assert "Project Memory" in prompt
        assert "No asyncio" in prompt
        assert "User Memory" in prompt
        assert "Senior Python dev" in prompt

    def test_no_memory_context_when_files_missing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from xcode_cli.core.prompting import build_system_prompt

        project_dir = tmp_path / "emptyproject"
        project_dir.mkdir(parents=True, exist_ok=True)
        _setup_xcode_home(tmp_path, monkeypatch)

        cfg = Config(auto_memory=False)
        prompt = build_system_prompt(cfg, cwd=str(project_dir))

        assert "## Project Memory" not in prompt
        assert "## User Memory" not in prompt
        assert "## Auto Memory Index" not in prompt

    def test_passes_cwd_to_memory_manager(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from xcode_cli.core.prompting import build_system_prompt

        project_dir = tmp_path / "specific_app"
        project_dir.mkdir(parents=True, exist_ok=True)
        _setup_xcode_home(tmp_path, monkeypatch)

        cfg = Config(auto_memory=False)
        prompt = build_system_prompt(cfg, cwd=str(project_dir))

        assert str(project_dir) in prompt
        assert "Resolved memory paths" in prompt

    def test_auto_memory_block_is_index_only(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from xcode_cli.core.prompting import build_system_prompt

        project_dir = tmp_path / "index_test"
        project_dir.mkdir(parents=True, exist_ok=True)
        mm = _make_memory_manager(tmp_path, monkeypatch, cwd=str(project_dir))

        mm.memory_dir_path().mkdir(parents=True, exist_ok=True)
        mm.memory_index_path().write_text("- [One](one.md) — first\n", encoding="utf-8")
        (mm.memory_dir_path() / "one.md").write_text(
            "---\nname: one\ndescription: test\nmetadata:\n  type: feedback\n---\nBody text here.\n",
            encoding="utf-8",
        )

        cfg = Config(auto_memory=True)
        prompt = build_system_prompt(cfg, cwd=str(project_dir))

        assert "Auto Memory Index" in prompt
        assert "one.md" in prompt
        assert "Body text here" not in prompt

    def test_skills_compose_with_memory_context(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from xcode_cli.core.prompting import build_system_prompt

        project_dir = tmp_path / "skill_test"
        project_dir.mkdir(parents=True, exist_ok=True)
        mm = _make_memory_manager(tmp_path, monkeypatch, cwd=str(project_dir))

        mm.write_project_memory("## Project Rules\n- Prefer edit_file", append=False)

        cfg = Config(auto_memory=False)
        prompt = build_system_prompt(cfg, cwd=str(project_dir))

        assert "Project Memory" in prompt
        assert "Prefer edit_file" in prompt

    def test_working_directory_in_prompt(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from xcode_cli.core.prompting import build_system_prompt

        project_dir = tmp_path / "wd_test"
        project_dir.mkdir(parents=True, exist_ok=True)
        _setup_xcode_home(tmp_path, monkeypatch)

        cfg = Config(auto_memory=False)
        prompt = build_system_prompt(cfg, cwd=str(project_dir))

        assert "Working directory" in prompt
        assert str(project_dir) in prompt

    def test_resolved_memory_paths_in_prompt(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from xcode_cli.core.prompting import build_system_prompt

        project_dir = tmp_path / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        mm = _make_memory_manager(tmp_path, monkeypatch, cwd=str(project_dir))

        prompt = build_system_prompt(Config(auto_memory=True), cwd=str(project_dir))

        assert str(mm.memory_dir_path()) in prompt
        assert str(mm.memory_index_path()) in prompt
        assert str(mm.project_memory_path()) in prompt
        assert str(mm.user_memory_path()) in prompt
