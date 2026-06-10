from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from xcode_cli.core.config import Config, ConfigStore
from xcode_cli.core.ui.env_dashboard import EnvDashboard, PARAMS


def _make_dashboard(tmp_path: Path) -> tuple[EnvDashboard, ConfigStore]:
    config_path = tmp_path / "config.json"
    store = ConfigStore()
    store.path = config_path
    console = MagicMock()
    dashboard = EnvDashboard(store, console)
    return dashboard, store


class TestDashboardInit:
    def test_init_loads_default_config(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        assert dashboard.cfg.max_tokens == 128000
        assert dashboard.cfg.max_summary_chars == 6000
        assert dashboard.cfg.auto_memory is True
        assert dashboard.selected == 0

    def test_init_params_count(self) -> None:
        assert len(PARAMS) == 5


class TestDashboardToggleBool:
    def test_toggle_auto_memory_off(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        assert dashboard.cfg.auto_memory is True
        # 模拟 bool 参数编辑
        param = PARAMS[4]  # auto_memory
        dashboard._edit_param(param)
        assert dashboard.cfg.auto_memory is False

    def test_toggle_auto_memory_back_on(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        dashboard.cfg.auto_memory = False
        param = PARAMS[4]
        dashboard._edit_param(param)
        assert dashboard.cfg.auto_memory is True


class TestDashboardChoiceCycle:
    def test_choice_cycle_render_mode(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        assert dashboard.cfg.response_render_mode == "buffer_then_render"
        param = PARAMS[2]  # response_render_mode
        dashboard._edit_param(param)
        assert dashboard.cfg.response_render_mode == "streaming_plus_final_render"
        dashboard._edit_param(param)
        assert dashboard.cfg.response_render_mode == "buffer_then_render"


class TestDashboardIntInput:
    def test_int_input_valid(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        param = PARAMS[0]  # max_tokens
        with patch("builtins.input", return_value="64000"):
            dashboard._edit_param(param)
        assert dashboard.cfg.max_tokens == 64000

    def test_int_input_zero_rejected_for_max_tokens(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        param = PARAMS[0]  # max_tokens
        with patch("builtins.input", return_value="0"):
            dashboard._edit_param(param)
        # 值不变
        assert dashboard.cfg.max_tokens == 128000

    def test_int_input_negative_rejected_for_max_summary_chars(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        param = PARAMS[1]  # max_summary_chars
        with patch("builtins.input", return_value="-1"):
            dashboard._edit_param(param)
        assert dashboard.cfg.max_summary_chars == 6000

    def test_int_input_empty_keeps_value(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        param = PARAMS[0]  # max_tokens
        with patch("builtins.input", return_value=""):
            dashboard._edit_param(param)
        assert dashboard.cfg.max_tokens == 128000

    def test_int_input_non_numeric_rejected(self, tmp_path: Path) -> None:
        dashboard, _ = _make_dashboard(tmp_path)
        param = PARAMS[0]  # max_tokens
        with patch("builtins.input", return_value="abc"):
            dashboard._edit_param(param)
        assert dashboard.cfg.max_tokens == 128000


class TestDashboardSave:
    def test_save_persists_config(self, tmp_path: Path) -> None:
        dashboard, store = _make_dashboard(tmp_path)
        dashboard.cfg.max_summary_chars = 3000
        store.save(dashboard.cfg)

        loaded = store.load()
        assert loaded.max_summary_chars == 3000


class TestDashboardQuitNoSave:
    def test_quit_no_save_keeps_original(self, tmp_path: Path) -> None:
        dashboard, store = _make_dashboard(tmp_path)
        store.save(Config(max_tokens=128000))

        # 编辑内存中的值但不保存
        dashboard.cfg.max_tokens = 64000

        # 重新加载应该是原值
        loaded = store.load()
        assert loaded.max_tokens == 128000


class TestDashboardNonTTY:
    def test_non_tty_prints_hint(self, tmp_path: Path) -> None:
        dashboard, store = _make_dashboard(tmp_path)
        with patch("sys.stdin.isatty", return_value=False):
            dashboard.run()
        # 应该打印提示信息
        dashboard.console.print.assert_called()
