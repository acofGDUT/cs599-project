from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from rich.console import Console

from xcode_cli.core.config import Config, ConfigStore
from xcode_cli.core.tooling.approval import read_key


@dataclass
class ParamDef:
    key: str
    label: str
    description: str
    type: str  # "int" | "str" | "bool" | "choice"
    choices: list[str] | None = None


PARAMS = [
    ParamDef("max_tokens", "Max Tokens", "上下文 token 预算上限，超出 80% 触发自动压缩", "int"),
    ParamDef("max_summary_chars", "Summary Chars", "压缩摘要最大字符数，0 关闭硬截断", "int"),
    ParamDef("response_render_mode", "渲染模式", "streaming: 逐 token 流式 / buffer: 完成后渲染", "choice", ["streaming_plus_final_render", "buffer_then_render"]),
    ParamDef("syntax_theme", "语法主题", "代码高亮配色方案 (monokai, dracula, one-dark 等)", "str"),
    ParamDef("auto_memory", "自动记忆", "关闭后不再自动写入项目记忆文件", "bool"),
]

# 初次渲染后，参数区域和帮助栏的总行数（不含 banner），用于 ANSI 局部刷新
_REFRESH_LINES = 13


class EnvDashboard:
    def __init__(self, config_store: ConfigStore, console: Console) -> None:
        self.config_store = config_store
        self.console = console
        self.cfg: Config = config_store.load()
        self.selected: int = 0
        self.params: list[ParamDef] = PARAMS

    def run(self) -> None:
        if not sys.stdin.isatty():
            self.console.print("当前终端不支持交互式仪表盘。")
            self.console.print(f"请手动编辑配置文件: {self.config_store.path}")
            return

        self.console.clear()
        self._render_params()
        self._render_help()

        while True:
            try:
                key = read_key()
            except KeyboardInterrupt:
                self.console.print("\n[dim]未保存，已退出。[/dim]")
                return

            if key in {"up", "k"}:
                self.selected = (self.selected - 1) % len(self.params)
                self._refresh_params()
                self._render_help()
            elif key in {"down", "j"}:
                self.selected = (self.selected + 1) % len(self.params)
                self._refresh_params()
                self._render_help()
            elif key == "enter":
                self._edit_param(self.params[self.selected])
                self._refresh_params()
                self._render_help()
            elif key == "s":
                self.config_store.save(self.cfg)
                self.console.print(f"\n[green]配置已保存到[/green] {self.config_store.path}")
                self.console.print("[dim]部分参数（max_tokens、response_render_mode）在下次启动时生效。[/dim]")
                return
            elif key in {"q", "escape"}:
                self.console.print("\n[dim]未保存，已退出。[/dim]")
                return

    # ── rendering ────────────────────────────────────────────

    def _print_banner(self) -> None:
        self.console.print("[bold cyan]╔══════════════════════════════════════════════╗[/bold cyan]")
        self.console.print("[bold cyan]║        Xcode /env — 上下文 · 压缩 · 输出     ║[/bold cyan]")
        self.console.print("[bold cyan]╚══════════════════════════════════════════════╝[/bold cyan]")

    def _render_params(self) -> None:
        """完整初次渲染：banner + 参数区域。"""
        self._print_banner()
        self._print_param_section()

    def _print_param_section(self) -> None:
        """渲染参数分区。"""
        self.console.print("\n  [bold]Context[/bold]")
        self._print_param_row(0)  # max_tokens
        self._print_param_row(1)  # max_summary_chars

        self.console.print("\n  [bold]输出[/bold]")
        self._print_param_row(2)  # response_render_mode
        self._print_param_row(3)  # syntax_theme

        self.console.print("\n  [bold]记忆[/bold]")
        self._print_param_row(4)  # auto_memory

    def _refresh_params(self) -> None:
        """ANSI 局部刷新：只重绘参数区域和帮助栏，不动 banner。"""
        sys.stdout.write(f"\x1b[{_REFRESH_LINES}A")
        for _ in range(_REFRESH_LINES):
            sys.stdout.write("\x1b[2K")
            sys.stdout.write("\x1b[1B")
        sys.stdout.write(f"\x1b[{_REFRESH_LINES}A")
        sys.stdout.flush()
        self._print_param_section()

    def _print_param_row(self, idx: int) -> None:
        param = self.params[idx]
        value = getattr(self.cfg, param.key)

        if param.type == "bool":
            display_value = "开启" if value else "关闭"
        elif param.type == "choice":
            display_value = str(value)
        else:
            display_value = str(value)

        prefix = ">" if idx == self.selected else " "
        style = "bold cyan" if idx == self.selected else ""

        label_col_width = 20
        self.console.print(
            f"  {prefix} {param.label:<{label_col_width}} {display_value:<20} [dim]{param.description}[/dim]",
            style=style,
        )

    def _render_help(self) -> None:
        self.console.print()
        self.console.print("  [dim]操作: ↑↓ 导航  Enter 编辑  s 保存  q 不保存退出[/dim]")

    # ── editing ──────────────────────────────────────────────

    def _edit_param(self, param: ParamDef) -> None:
        current = getattr(self.cfg, param.key)

        self.console.print()
        self.console.print(f"  [bold]编辑: {param.label}[/bold]")
        self.console.print(f"  当前值: {current}")
        self.console.print(f"  [dim]{param.description}[/dim]")

        if param.type == "bool":
            new_value = not current
            setattr(self.cfg, param.key, new_value)
            self.console.print(f"  [green]-> {'开启' if new_value else '关闭'}[/green]")
            time.sleep(0.5)
            return

        if param.type == "choice":
            assert param.choices is not None
            current_idx = param.choices.index(current) if current in param.choices else 0
            new_value = param.choices[(current_idx + 1) % len(param.choices)]
            setattr(self.cfg, param.key, new_value)
            self.console.print(f"  [green]-> {new_value}[/green]")
            time.sleep(0.5)
            return

        try:
            self.console.print("  新值: ", end="")
            raw = input().strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print("  [dim]已取消[/dim]")
            time.sleep(0.3)
            return

        if not raw:
            self.console.print("  [dim]保持原值[/dim]")
            time.sleep(0.3)
            return

        if param.type == "int":
            try:
                value = int(raw)
            except ValueError:
                self.console.print(f"  [red]无效整数: {raw}[/red]")
                time.sleep(0.5)
                return
            if param.key == "max_tokens" and value <= 0:
                self.console.print("  [red]max_tokens 必须 > 0[/red]")
                time.sleep(0.5)
                return
            if param.key == "max_summary_chars" and value < 0:
                self.console.print("  [red]max_summary_chars 必须 >= 0[/red]")
                time.sleep(0.5)
                return
            setattr(self.cfg, param.key, value)

        if param.type == "str":
            setattr(self.cfg, param.key, raw.strip())

        self.console.print(f"  [green]-> {getattr(self.cfg, param.key)}[/green]")
        time.sleep(0.5)
