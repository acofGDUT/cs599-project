from __future__ import annotations

import json
from pathlib import Path

from xcode_cli.mcp.config import load_mcp_config


def _write_mcp(project_root: Path, payload: dict) -> None:
    config_dir = project_root / ".xcode"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(json.dumps(payload), encoding="utf-8")


def test_missing_mcp_config_returns_empty_config(tmp_path: Path) -> None:
    cfg = load_mcp_config(tmp_path)

    assert cfg.servers == ()
    assert cfg.max_mcp_output_chars == 20000


def test_stdio_default_and_workspace_expansion(tmp_path: Path) -> None:
    _write_mcp(
        tmp_path,
        {
            "mcpServers": {
                "filesystem": {
                    "command": "python",
                    "args": ["server.py", "${workspace}"],
                    "cwd": "${workspace}",
                }
            }
        },
    )

    cfg = load_mcp_config(tmp_path)

    server = cfg.servers[0]
    assert server.type == "stdio"
    assert server.cwd == tmp_path.resolve()
    assert server.args == ("server.py", str(tmp_path.resolve()))


def test_relative_cwd_is_resolved_from_project_root(tmp_path: Path, monkeypatch) -> None:
    _write_mcp(
        tmp_path,
        {
            "mcpServers": {
                "filesystem": {
                    "command": "python",
                    "cwd": ".",
                }
            }
        },
    )
    subdir = tmp_path / "nested"
    subdir.mkdir()
    monkeypatch.chdir(subdir)

    cfg = load_mcp_config(tmp_path)

    assert cfg.servers[0].cwd == tmp_path.resolve()


def test_sanitized_server_name_conflicts_are_skipped(tmp_path: Path) -> None:
    _write_mcp(
        tmp_path,
        {
            "mcpServers": {
                "my-server": {"command": "python"},
                "my_server": {"command": "node"},
            }
        },
    )

    cfg = load_mcp_config(tmp_path)

    assert [server.name for server in cfg.servers] == ["my-server"]
    assert any("sanitized name" in warning and "conflicts" in warning for warning in cfg.warnings)


def test_only_stdio_servers_are_accepted(tmp_path: Path) -> None:
    _write_mcp(
        tmp_path,
        {
            "mcpServers": {
                "remote": {"type": "http", "command": "ignored"},
                "local": {"type": "stdio", "command": "python"},
            }
        },
    )

    cfg = load_mcp_config(tmp_path)

    assert [server.name for server in cfg.servers] == ["local"]
    assert any("remote" in warning and "unsupported type" in warning for warning in cfg.warnings)


def test_env_expansion_and_missing_env_warning(tmp_path: Path) -> None:
    _write_mcp(
        tmp_path,
        {
            "mcpServers": {
                "envy": {
                    "command": "python",
                    "env": {
                        "TOKEN": "${TOKEN}",
                        "MISSING": "${MISSING}",
                    },
                }
            }
        },
    )

    cfg = load_mcp_config(tmp_path, env={"TOKEN": "secret"})

    server = cfg.servers[0]
    assert server.env == {"TOKEN": "secret", "MISSING": ""}
    assert any("MISSING" in warning for warning in cfg.warnings)


def test_max_mcp_output_chars_defaults_for_invalid_values(tmp_path: Path) -> None:
    _write_mcp(tmp_path, {"max_mcp_output_chars": "bad", "mcpServers": {}})

    cfg = load_mcp_config(tmp_path)

    assert cfg.max_mcp_output_chars == 20000
    assert any("max_mcp_output_chars" in warning for warning in cfg.warnings)


def test_env_must_be_string_mapping(tmp_path: Path) -> None:
    _write_mcp(
        tmp_path,
        {
            "mcpServers": {
                "bad_env": {
                    "command": "python",
                    "env": {"TOKEN": 123, 9: "bad"},
                }
            }
        },
    )

    cfg = load_mcp_config(tmp_path)

    assert cfg.servers[0].env == {"9": "bad"}
    assert any("env" in warning for warning in cfg.warnings)
