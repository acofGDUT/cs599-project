import json

from xcode_cli.qqchat.config import QQChatConfig, load_qqchat_config


def test_env_loads_app_id_and_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("QQ_BOT_APP_ID", "app-from-env")
    monkeypatch.setenv("QQ_BOT_CLIENT_SECRET", "secret-from-env")

    cfg = load_qqchat_config(project_root=tmp_path, user_config_path=tmp_path / "missing.json")

    assert cfg.app_id == "app-from-env"
    assert cfg.client_secret == "secret-from-env"


def test_project_config_cannot_override_client_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("QQ_BOT_APP_ID", "app-from-env")
    monkeypatch.setenv("QQ_BOT_CLIENT_SECRET", "secret-from-env")
    project_config = tmp_path / ".xcode" / "config.json"
    project_config.parent.mkdir()
    project_config.write_text(
        json.dumps(
            {
                "qqchat": {
                    "client_secret": "project-secret-must-not-win",
                    "enable_group_at": False,
                    "group_allowlist": ["group-a"],
                    "max_reply_chars": 1200,
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = load_qqchat_config(project_root=tmp_path, user_config_path=tmp_path / "missing.json")

    assert cfg.client_secret == "secret-from-env"
    assert cfg.enable_group_at is False
    assert cfg.group_allowlist == ["group-a"]
    assert cfg.max_reply_chars == 1200


def test_user_config_can_supply_secret_when_env_is_missing(tmp_path):
    user_config = tmp_path / "qqchat.json"
    user_config.write_text(
        json.dumps({"app_id": "app-from-user", "client_secret": "secret-from-user"}),
        encoding="utf-8",
    )

    cfg = load_qqchat_config(project_root=tmp_path, user_config_path=user_config, env={})

    assert cfg.app_id == "app-from-user"
    assert cfg.client_secret == "secret-from-user"


def test_default_tool_scope_is_read_only():
    cfg = QQChatConfig(app_id="app", client_secret="secret")

    assert cfg.tool_scope == {
        "visible_tools": ["read_file", "grep", "glob", "task_list"],
        "execution_allowlist": ["read_file", "grep", "glob", "task_list"],
        "remote_approval": False,
    }


def test_safe_summary_masks_secret():
    cfg = QQChatConfig(app_id="app", client_secret="super-secret")

    summary = cfg.safe_summary()

    assert "super-secret" not in str(summary)
    assert summary["client_secret"] == "<set>"


def test_status_and_errors_do_not_include_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("QQ_BOT_APP_ID", "app")
    monkeypatch.setenv("QQ_BOT_CLIENT_SECRET", "super-secret")
    cfg = load_qqchat_config(project_root=tmp_path, user_config_path=tmp_path / "missing.json")

    rendered = str(cfg.safe_summary())

    assert "super-secret" not in rendered
    assert "<set>" in rendered
