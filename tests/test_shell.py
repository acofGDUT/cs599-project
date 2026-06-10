from __future__ import annotations

import subprocess

from xcode_cli.core.tools.shell import run_shell


def test_run_shell_uses_utf8_and_replace(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_shell("echo hello", cwd="D:\\Xcode", timeout=5000)

    assert result == "ok\nexit_code=0"
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
