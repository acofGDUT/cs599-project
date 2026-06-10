from __future__ import annotations

from pathlib import Path

from xcode_cli.core.config import Config
from xcode_cli.paths import ensure_xcode_home


class MemoryManager:
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        self.xcode_home = ensure_xcode_home()
        self.user_memory = self.xcode_home / "XCODE.md"
        self.project_memory = self.cwd / "XCODE.md"
        project_name = self.cwd.name or "default"
        self.memory_dir = self.xcode_home / "projects" / project_name / "memory"
        self.memory_index = self.memory_dir / "MEMORY.md"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def user_memory_path(self) -> Path:
        return self.user_memory

    def project_memory_path(self) -> Path:
        return self.project_memory

    def has_user_memory(self) -> bool:
        return self.user_memory.exists()

    def has_project_memory(self) -> bool:
        return self.project_memory.exists()

    def read_user_memory(self) -> str:
        if not self.has_user_memory():
            return ""
        return self.user_memory.read_text(encoding="utf-8").strip()

    def read_project_memory(self) -> str:
        if not self.has_project_memory():
            return ""
        return self.project_memory.read_text(encoding="utf-8").strip()

    def write_user_memory(self, content: str, append: bool = True) -> None:
        self._write_memory(self.user_memory, content, append=append)

    def write_project_memory(self, content: str, append: bool = True) -> None:
        self._write_memory(self.project_memory, content, append=append)

    def is_auto_memory_enabled(self, cfg: Config) -> bool:
        return bool(cfg.auto_memory)

    def memory_dir_path(self) -> Path:
        return self.memory_dir

    def memory_index_path(self) -> Path:
        return self.memory_index

    def read_memory_index(self) -> str:
        if not self.memory_index.exists():
            return ""
        return self.memory_index.read_text(encoding="utf-8").strip()

    def get_context_for_prompt(self, cfg: Config) -> str:
        blocks: list[str] = []

        project = self._truncate(self.read_project_memory(), 2000)
        if project:
            blocks.append(f"## Project Memory (XCODE.md)\n{project}")

        user = self._truncate(self.read_user_memory(), 2000)
        if user:
            blocks.append(f"## User Memory (XCODE.md)\n{user}")

        if self.is_auto_memory_enabled(cfg):
            index_content = self._truncate(self.read_memory_index(), 1200)
            if index_content:
                blocks.append(
                    f"## Auto Memory Index\n{index_content}\n\n"
                    "(Use read_file on individual memory files for full details.)"
                )

        context = "\n\n".join(blocks).strip()
        return self._truncate(context, 5000)

    def _write_memory(self, path: Path, content: str, append: bool) -> None:
        cleaned = content.strip()
        if not cleaned:
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.exists():
            existing = path.read_text(encoding="utf-8").rstrip()
            payload = f"{existing}\n\n{cleaned}\n" if existing else f"{cleaned}\n"
            path.write_text(payload, encoding="utf-8")
            return

        path.write_text(cleaned + "\n", encoding="utf-8")

    def is_memory_write_target(self, path: str | Path) -> bool:
        try:
            target = Path(path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return False

        exact_targets = {
            self.user_memory.resolve(strict=False),
            self.project_memory.resolve(strict=False),
            self.memory_index.resolve(strict=False),
        }
        if target in exact_targets:
            return True

        memory_root = self.memory_dir.resolve(strict=False)
        try:
            return target.is_relative_to(memory_root) and target.suffix.lower() == ".md"
        except ValueError:
            return False

    def _truncate(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n...[truncated]"

