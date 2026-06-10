from __future__ import annotations

import json
import sys
from dataclasses import dataclass, fields
from pathlib import Path

from xcode_cli.paths import ensure_xcode_home


@dataclass
class Config:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    provider: str = "openai-compatible"
    auto_memory: bool = True
    max_tokens: int = 128000
    response_render_mode: str = "buffer_then_render"
    syntax_theme: str = "monokai"
    max_summary_chars: int = 6000


class ConfigStore:
    def __init__(self) -> None:
        root = ensure_xcode_home()
        self.path: Path = root / "config.json"

    def load(self) -> Config:
        if not self.path.exists():
            return Config()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        allowed_fields = {f.name for f in fields(Config)}
        data = {k: v for k, v in data.items() if k in allowed_fields}
        response_render_mode = data.get("response_render_mode", "streaming_plus_final_render")
        if response_render_mode not in {"streaming_plus_final_render", "buffer_then_render"}:
            response_render_mode = "buffer_then_render"

        max_tokens = data.get("max_tokens", 128000)
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            max_tokens = 128000

        syntax_theme = data.get("syntax_theme", "monokai")
        if not isinstance(syntax_theme, str) or not syntax_theme.strip():
            syntax_theme = "monokai"

        max_summary_chars = data.get("max_summary_chars", 6000)
        if not isinstance(max_summary_chars, int) or max_summary_chars < 0:
            max_summary_chars = 6000

        cfg = Config(
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url", ""),
            model=data.get("model", ""),
            provider=data.get("provider", "openai-compatible"),
            auto_memory=data.get("auto_memory", True),
            max_tokens=max_tokens,
            response_render_mode=response_render_mode,
            syntax_theme=syntax_theme.strip(),
            max_summary_chars=max_summary_chars,
        )

        # 项目级 config merge
        project_config_path = Path.cwd() / ".xcode" / "config.json"
        if project_config_path.exists():
            try:
                project_data = json.loads(project_config_path.read_text(encoding="utf-8"))
                if isinstance(project_data, dict):
                    for field_name in allowed_fields:
                        if field_name in project_data:
                            setattr(cfg, field_name, project_data[field_name])
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[warning] Failed to read project config {project_config_path}: {exc}", file=sys.stderr)

        return cfg

    def save(self, config: Config) -> None:
        payload = {
            "api_key": config.api_key,
            "base_url": config.base_url,
            "model": config.model,
            "provider": config.provider,
            "auto_memory": config.auto_memory,
            "max_tokens": config.max_tokens,
            "response_render_mode": config.response_render_mode,
            "syntax_theme": config.syntax_theme,
            "max_summary_chars": config.max_summary_chars,
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
