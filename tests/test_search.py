from __future__ import annotations

import subprocess

from xcode_cli.core.tools import search


def test_grep_uses_utf8_and_replace_for_rg_output(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(search, "_resolve_rg_binary", lambda: "rg")
    monkeypatch.setattr(search, "resolve_project_root", lambda: tmp_path)

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = search.grep("needle")

    assert result == "ok"
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
