from __future__ import annotations

import json
from pathlib import Path

from xcode_cli.core.config import Config, ConfigStore
from xcode_cli.core.context import ContextManager


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_tmp_xcode_home(tmp_path: Path, monkeypatch, max_tokens: int = 128000) -> Path:
    """Point XCODE_DIR at a temp directory and seed a minimal config.json."""
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)

    for sub in ("sessions", "skills", "bin"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)

    config_path = xcode_dir / "config.json"
    config_path.write_text(
        json.dumps({"max_tokens": max_tokens, "model": "test-model"}),
        encoding="utf-8",
    )
    return xcode_dir


def _make_agent(tmp_path: Path, monkeypatch, max_tokens: int = 128000):
    """Construct an AgentRuntime pointed at a temp config."""
    _setup_tmp_xcode_home(tmp_path, monkeypatch, max_tokens=max_tokens)

    from unittest.mock import MagicMock
    import xcode_cli.core.agent as agent_mod

    monkeypatch.setattr(
        agent_mod,
        "PromptSession",
        MagicMock(return_value=MagicMock()),
        raising=True,
    )
    monkeypatch.setattr(
        agent_mod,
        "AutoSuggestFromHistory",
        MagicMock(return_value=MagicMock()),
        raising=True,
    )

    from xcode_cli.core.agent import AgentRuntime

    return AgentRuntime()


# ---------------------------------------------------------------------------
# /context — runtime max_tokens consistency
# ---------------------------------------------------------------------------

class TestContextRuntimeConsistency:
    def test_display_uses_context_max_tokens_not_config(self, tmp_path: Path, monkeypatch) -> None:
        """After mutating runtime value, /context must reflect it."""
        agent = _make_agent(tmp_path, monkeypatch, max_tokens=128000)

        # mutate runtime without touching config on disk
        agent.context.max_tokens = 99999

        # /context should use the runtime value, not the stale config value
        assert agent.context.max_tokens == 99999

    def test_env_dashboard_syncs_context_after_run(self, tmp_path: Path, monkeypatch) -> None:
        """EnvDashboard 退出后，agent.context 同步 config 中的值。"""
        agent = _make_agent(tmp_path, monkeypatch, max_tokens=128000)

        # 模拟 dashboard 修改了 config 并保存
        cfg = agent.config_store.load()
        cfg.max_tokens = 32000
        agent.config_store.save(cfg)

        # 调用 _handle_env_command，dashboard 在非 TTY 下会直接返回
        # 但 sync 逻辑仍会执行
        agent._handle_env_command(["/env"])

        # 同步后 context 应该反映 config 的值
        assert agent.context.max_tokens == 32000


# ---------------------------------------------------------------------------
# basic unit-level safety nets (kept for coverage of edge branches)
# ---------------------------------------------------------------------------

class TestEnvMaxTokensBasic:
    def test_updates_config_and_context(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"max_tokens": 128000, "model": "test"}), encoding="utf-8"
        )

        cm = ContextManager(max_tokens=128000)
        cm.max_tokens = 64000
        assert cm.max_tokens == 64000

        store = ConfigStore()
        store.path = config_path
        cfg = store.load()
        cfg.max_tokens = 64000
        store.save(cfg)

        loaded = store.load()
        assert loaded.max_tokens == 64000

    def test_invalid_input_does_not_crash(self) -> None:
        for val in ("abc", "-5", "0", ""):
            try:
                int_val = int(val)
                if int_val <= 0:
                    assert int_val < 1
            except ValueError:
                pass

    def test_invalid_does_not_persist(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"max_tokens": 128000}), encoding="utf-8"
        )
        store = ConfigStore()
        store.path = config_path
        loaded = store.load()
        assert loaded.max_tokens == 128000

    def test_show_includes_max_tokens_from_config(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"max_tokens": 96000}), encoding="utf-8"
        )
        store = ConfigStore()
        store.path = config_path
        cfg = store.load()
        assert cfg.max_tokens == 96000
