from __future__ import annotations

import json
from pathlib import Path

from xcode_cli.core.config import Config, ConfigStore


def test_config_default_max_tokens() -> None:
    c = Config()
    assert c.max_tokens == 128000


def test_config_max_tokens_is_stored(tmp_path: Path) -> None:
    """Save config with custom max_tokens and reload."""
    config_path = tmp_path / "config.json"
    store = ConfigStore()
    store.path = config_path

    cfg = Config()
    cfg.max_tokens = 64000
    cfg.model = "test-model"
    store.save(cfg)

    loaded = store.load()
    assert loaded.max_tokens == 64000
    assert loaded.model == "test-model"


def test_config_load_invalid_max_tokens_falls_back_to_default(tmp_path: Path) -> None:
    """Non-integer or negative max_tokens should fall back to 128000."""
    config_path = tmp_path / "config.json"
    store = ConfigStore()
    store.path = config_path

    # Write bad data directly
    config_path.write_text(json.dumps({"max_tokens": "not_an_integer"}), encoding="utf-8")
    loaded = store.load()
    assert loaded.max_tokens == 128000

    config_path.write_text(json.dumps({"max_tokens": -1}), encoding="utf-8")
    loaded = store.load()
    assert loaded.max_tokens == 128000

    config_path.write_text(json.dumps({"max_tokens": 0}), encoding="utf-8")
    loaded = store.load()
    assert loaded.max_tokens == 128000


def test_config_load_missing_max_tokens_uses_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    store = ConfigStore()
    store.path = config_path

    config_path.write_text(json.dumps({"model": "foo"}), encoding="utf-8")
    loaded = store.load()
    assert loaded.max_tokens == 128000
    assert loaded.model == "foo"


def test_config_ignores_legacy_enabled_skills_key(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    store = ConfigStore()
    store.path = config_path

    config_path.write_text(
        json.dumps({"enabled_skills": ["review"], "model": "foo"}),
        encoding="utf-8",
    )

    loaded = store.load()

    assert not hasattr(loaded, "enabled_skills")
    assert loaded.model == "foo"


def test_config_store_creates_new_config_when_missing() -> None:
    store = ConfigStore()
    store.path = Path("/nonexistent/path/config.json")
    loaded = store.load()
    assert loaded.max_tokens == 128000
    assert isinstance(loaded, Config)


def test_config_syntax_theme_default() -> None:
    c = Config()
    assert c.syntax_theme == "monokai"


def test_config_syntax_theme_invalid_fallback(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    store = ConfigStore()
    store.path = config_path

    config_path.write_text(json.dumps({"syntax_theme": ""}), encoding="utf-8")
    loaded = store.load()
    assert loaded.syntax_theme == "monokai"

    config_path.write_text(json.dumps({"syntax_theme": "   "}), encoding="utf-8")
    loaded = store.load()
    assert loaded.syntax_theme == "monokai"


def test_max_summary_chars_default() -> None:
    c = Config()
    assert c.max_summary_chars == 6000


def test_max_summary_chars_serialization(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    store = ConfigStore()
    store.path = config_path

    cfg = Config()
    cfg.max_summary_chars = 3000
    store.save(cfg)

    loaded = store.load()
    assert loaded.max_summary_chars == 3000


def test_max_summary_chars_invalid_fallback(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    store = ConfigStore()
    store.path = config_path

    config_path.write_text(json.dumps({"max_summary_chars": -1}), encoding="utf-8")
    loaded = store.load()
    assert loaded.max_summary_chars == 6000

    config_path.write_text(json.dumps({"max_summary_chars": "bad"}), encoding="utf-8")
    loaded = store.load()
    assert loaded.max_summary_chars == 6000


def test_project_config_merge(tmp_path: Path, monkeypatch) -> None:
    """项目级 .xcode/config.json 字段覆盖全局值"""
    global_path = tmp_path / "global_config.json"
    global_path.write_text(json.dumps({
        "max_tokens": 128000,
        "max_summary_chars": 6000,
        "syntax_theme": "monokai",
    }), encoding="utf-8")

    store = ConfigStore()
    store.path = global_path

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_xcode = project_dir / ".xcode"
    project_xcode.mkdir()
    project_config = project_xcode / "config.json"
    project_config.write_text(json.dumps({
        "max_tokens": 64000,
        "syntax_theme": "dracula",
    }), encoding="utf-8")

    monkeypatch.chdir(project_dir)
    loaded = store.load()
    assert loaded.max_tokens == 64000
    assert loaded.syntax_theme == "dracula"
    # 项目文件未写的字段保持全局值
    assert loaded.max_summary_chars == 6000


def test_project_config_not_exists(tmp_path: Path, monkeypatch) -> None:
    """项目文件不存在时全用全局值"""
    global_path = tmp_path / "global_config.json"
    global_path.write_text(json.dumps({
        "max_tokens": 64000,
        "syntax_theme": "dracula",
    }), encoding="utf-8")

    store = ConfigStore()
    store.path = global_path

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.chdir(project_dir)
    loaded = store.load()
    assert loaded.max_tokens == 64000
    assert loaded.syntax_theme == "dracula"


def test_project_config_malformed(tmp_path: Path, monkeypatch, capsys) -> None:
    """损坏的项目文件不崩，打印 warning"""
    global_path = tmp_path / "global_config.json"
    global_path.write_text(json.dumps({"max_tokens": 64000}), encoding="utf-8")

    store = ConfigStore()
    store.path = global_path

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_xcode = project_dir / ".xcode"
    project_xcode.mkdir()
    project_config = project_xcode / "config.json"
    project_config.write_text("{bad json", encoding="utf-8")

    monkeypatch.chdir(project_dir)
    loaded = store.load()
    # 全局值不受影响
    assert loaded.max_tokens == 64000
    # stderr 有 warning
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "Failed" in captured.err
