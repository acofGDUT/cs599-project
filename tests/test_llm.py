from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from xcode_cli.core.llm import LLMClient


def _setup_tmp_xcode_home(tmp_path: Path, monkeypatch) -> Path:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    xcode_dir.mkdir(parents=True, exist_ok=True)
    (xcode_dir / "config.json").write_text(
        json.dumps({"model": "test-model", "api_key": "test-key"}),
        encoding="utf-8",
    )
    for subdir in ("sessions", "skills", "bin"):
        (xcode_dir / subdir).mkdir(parents=True, exist_ok=True)
    return xcode_dir


def test_stream_error_while_iterating_returns_llm_error(tmp_path: Path, monkeypatch) -> None:
    _setup_tmp_xcode_home(tmp_path, monkeypatch)

    class BrokenStream:
        def __iter__(self):
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="partial",
                            tool_calls=None,
                        )
                    )
                ]
            )
            raise RuntimeError(
                "peer closed connection without sending complete message body "
                "(incomplete chunked read)"
            )

    class FakeOpenAI:
        def __init__(self, **_: object) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **__: BrokenStream())
            )

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    streamed_tokens: list[str] = []
    response = LLMClient().complete(
        system_prompt="system",
        messages=[],
        tool_schemas=[],
        on_text_token=streamed_tokens.append,
    )

    assert streamed_tokens == ["partial"]
    assert response.tool_calls == []
    assert response.content.startswith("[v0] LLM request failed:")
    assert "incomplete chunked read" in response.content
