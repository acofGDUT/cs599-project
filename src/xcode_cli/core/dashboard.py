from __future__ import annotations

import os

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt
from rich import box

from xcode_cli.core.config import ConfigStore

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def _is_ascii_text(value: str) -> bool:
    try:
        value.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _test_connection(base_url: str, api_key: str, model: str, timeout: float = 15.0) -> tuple[bool, str]:
    if not api_key:
        return False, "未设置 API Key"
    try:
        from openai import OpenAI
    except Exception:
        return False, "未安装 openai 包，请执行 pip install openai"

    kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    try:
        # chat completion 有时需要 models 权限，所以直接用 models.list()
        client.models.list()
        return True, f"连接成功！平台可用 (model: {model or '未指定'})"
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "403" in msg or "auth" in msg.lower():
            return False, "认证失败，请检查 API Key"
        if "404" in msg or "not found" in msg.lower():
            return False, "端点未找到，请检查 Base URL"
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            return False, "连接超时，请检查网络或 Base URL"
        return False, f"连接失败: {msg[:120]}"


class Dashboard:
    def __init__(self) -> None:
        self.console = Console()
        self.config_store = ConfigStore()
        self.cfg = self.config_store.load()

    # ── entry ──────────────────────────────────────────────
    def run(self) -> None:
        self.console.clear()
        self._print_banner()
        self._main_loop()

    # ── main loop ──────────────────────────────────────────
    def _main_loop(self) -> None:
        while True:
            self._show_status_bar()
            self.console.print()
            self._show_api_format_guide()
            self.console.print()
            self._show_menu_options()

            choice = Prompt.ask(
                "\n请选择操作",
                choices=["c", "t", "s", "q"],
                default="q",
                show_choices=False,
            )

            if choice == "q":
                self.console.print("\n[dim]已退出 Dashboard[/dim]")
                break
            elif choice == "c":
                self._configure_api()
            elif choice == "t":
                self._do_test()
            elif choice == "s":
                self._do_save()
            else:
                self.console.print("[red]无效选择[/red]")

    # ── display helpers ────────────────────────────────────
    def _print_banner(self) -> None:
        banner = Text(
            """
╔══════════════════════════════════════════════════╗
║            Xcode API 配置中心                     ║
║           选择平台 · 配置密钥 · 测试连接            ║
╚══════════════════════════════════════════════════╝
""",
            style="bold cyan",
        )
        self.console.print(banner)

    def _show_status_bar(self) -> None:
        model = self.cfg.model or DEFAULT_MODEL

        key_source = ""
        if self.cfg.api_key:
            key_source = "配置文件"
        elif os.getenv("XCODE_API_KEY"):
            key_source = "环境变量 XCODE_API_KEY"
        elif os.getenv("OPENAI_API_KEY"):
            key_source = "环境变量 OPENAI_API_KEY"

        has_key = bool(key_source)
        key_status = f"[green]已设置[/green] ([dim]{key_source}[/dim])" if has_key else "[red]未设置[/red]"

        tbl = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        tbl.add_column(style="bold white")
        tbl.add_column(style="yellow")
        tbl.add_row("协议", "OpenAI 兼容 API")
        tbl.add_row("当前模型", model)
        tbl.add_row("API Key", key_status)
        tbl.add_row("Base URL", self.cfg.base_url or DEFAULT_BASE_URL)
        self.console.print(Panel(tbl, title="当前配置", border_style="blue", title_align="left"))

    def _show_api_format_guide(self) -> None:
        guide = Table(title="OpenAI 兼容 API 输入格式", box=box.ROUNDED, border_style="cyan", show_header=True)
        guide.add_column("字段", style="bold white", width=16)
        guide.add_column("说明", style="dim", width=66)
        guide.add_row("Base URL", "形如 https://xxx.com/v1 （必须是 OpenAI 兼容接口根路径）")
        guide.add_row("API Key", "平台分配的密钥，建议使用 ASCII 字符")
        guide.add_row("Model", "平台提供的模型名，如 gpt-4o-mini / deepseek-chat / qwen-plus")
        self.console.print(guide)

    def _show_menu_options(self) -> None:
        opts = Table(show_header=False, box=None, padding=(0, 1))
        opts.add_column(style="dim")
        opts.add_column(style="dim")
        opts.add_row("[bold cyan]c[/bold cyan]", "配置 API（Base URL / Key / Model）")
        opts.add_row("[bold cyan]t[/bold cyan]", "测试当前连接")
        opts.add_row("[bold cyan]s[/bold cyan]", "保存配置到文件")
        opts.add_row("[bold cyan]q[/bold cyan]", "退出 Dashboard")
        self.console.print(Panel(opts, border_style="dim", title="操作", title_align="left"))

    # ── configure ──────────────────────────────────────────
    def _configure_api(self) -> None:
        self.console.clear()
        self.console.print(Panel.fit(
            "[bold cyan]OpenAI 兼容 API 配置[/bold cyan]",
            border_style="cyan",
        ))

        # ── API Key ──────────────────────────────────────────
        env_val = os.getenv("XCODE_API_KEY") or os.getenv("OPENAI_API_KEY") or self.cfg.api_key or ""
        masked = ""
        if env_val:
            masked = env_val[:6] + "****" + env_val[-4:] if len(env_val) > 10 else "(已设置)"

        self.console.print(f"\n[bold]API Key[/bold] 当前: {masked}" if masked else "\n[bold]API Key[/bold] 当前: [red]未设置[/red]")
        self.console.print("[dim]直接回车保持当前值，输入 new 输入新 Key，输入 clear 清除[/dim]")

        key_input = Prompt.ask("API Key", default="").strip()
        if key_input.lower() == "clear":
            self.cfg.api_key = ""
            os.environ.pop("XCODE_API_KEY", None)
        elif key_input.lower() == "new" or (key_input and key_input != ""):
            new_key = Prompt.ask("请输入新的 API Key")
            if new_key.strip():
                cleaned_key = new_key.strip()
                if not _is_ascii_text(cleaned_key):
                    self.console.print("[yellow]检测到 API Key 包含非 ASCII 字符，可能导致连接失败，请检查是否有中文标点或隐藏字符。[/yellow]")
                self.cfg.api_key = cleaned_key
                os.environ["XCODE_API_KEY"] = cleaned_key

        # ── Base URL ─────────────────────────────────────────
        current_url = self.cfg.base_url or DEFAULT_BASE_URL
        self.console.print(f"\n[bold]Base URL[/bold] 当前: [dim]{current_url}[/dim]")
        self.console.print("[dim]请填写 OpenAI 兼容接口根路径，示例: https://api.openai.com/v1[/dim]")
        url_input = Prompt.ask("Base URL", default="").strip()
        if url_input:
            self.cfg.base_url = url_input
        elif not self.cfg.base_url:
            self.cfg.base_url = DEFAULT_BASE_URL

        # ── Model ────────────────────────────────────────────
        self.console.print(f"\n[bold]Model[/bold] 当前: [yellow]{self.cfg.model or DEFAULT_MODEL}[/yellow]")
        self.console.print("[dim]填写平台提供的模型名，例如 gpt-4o-mini / deepseek-chat / qwen-plus[/dim]")
        model_input = Prompt.ask("Model 名称（直接回车保持当前值）", default="").strip()
        if model_input:
            self.cfg.model = model_input
        elif not self.cfg.model:
            self.cfg.model = DEFAULT_MODEL

        self.cfg.provider = "openai-compatible"

        self.console.print("\n[green]✓ OpenAI 兼容 API 配置完成[/green]")
        self.console.print("[dim]输入 s 保存到文件，t 测试连接[/dim]\n")
        Prompt.ask("按回车返回主菜单", default="")

    # ── test ────────────────────────────────────────────────
    def _do_test(self) -> None:
        latest_result: tuple[bool, str] | None = None

        while True:
            self.console.clear()
            self._show_test_page(latest_result)

            action = Prompt.ask(
                "\n测试页操作（r=重新测试, b=返回主菜单, q=退出Dashboard）",
                choices=["r", "b", "q"],
                default="r",
                show_choices=False,
            )

            if action == "b":
                return
            if action == "q":
                raise typer.Exit()

            latest_result = self._run_connection_test()

    def _show_test_page(self, latest_result: tuple[bool, str] | None) -> None:
        self.console.print(Panel.fit("[bold cyan]连接测试[/bold cyan]", border_style="cyan"))

        base = self.cfg.base_url or "(OpenAI 默认)"
        model = self.cfg.model or "gpt-4o-mini"

        info = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        info.add_column(style="bold white")
        info.add_column(style="yellow")
        info.add_row("Base URL", base)
        info.add_row("Model", model)
        self.console.print(Panel(info, title="当前测试配置", border_style="blue", title_align="left"))

        if latest_result is None:
            self.console.print("\n[dim]尚未测试。请选择 r 开始测试。[/dim]")
            return

        ok, msg = latest_result
        if ok:
            self.console.print(f"\n[bold green]✓ {msg}[/bold green]")
        else:
            self.console.print(f"\n[bold red]✗ {msg}[/bold red]")

    def _run_connection_test(self) -> tuple[bool, str]:
        base = self.cfg.base_url or ""
        key = self.cfg.api_key or os.getenv("XCODE_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        model = self.cfg.model or "gpt-4o-mini"

        if not key:
            return False, "请先设置 API Key"

        if not _is_ascii_text(key):
            return False, "API Key 包含非 ASCII 字符，可能包含中文标点或隐藏字符，请重新输入。"

        if base and not _is_ascii_text(base):
            return False, "Base URL 包含非 ASCII 字符，请检查是否误输入了中文字符。"

        return _test_connection(base, key, model)

    # ── save ────────────────────────────────────────────────
    def _do_save(self) -> None:
        self.config_store.save(self.cfg)
        self.console.print(f"\n[bold green]✓ 配置已保存到 {self.config_store.path}[/bold green]")
        Prompt.ask("按回车返回", default="")
