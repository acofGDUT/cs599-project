from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from xcode_cli.paths import ensure_xcode_home


PLAN_SYSTEM_PROMPT = """You are in PLANNING MODE. You are designing a solution, NOT implementing it.

Rules:
- Explore the codebase thoroughly using read_file, grep, glob.
- Do NOT use write_file, edit_file, or run_shell.
- Design the architecture, identify affected files, plan the changes.
- Write the plan to the plan file using the write_plan tool (not write_file).
- When the plan is complete, call exit_plan_mode to present it to the user for approval.
"""


@dataclass
class PlanMode:
    is_active: bool = False
    pending_approval: bool = False
    plan_path: str = ""
    plan_summary: str = ""

    def enter(self) -> str:
        self.is_active = True
        self.pending_approval = False
        self.plan_path = ""
        self.plan_summary = ""
        return "已进入计划模式。"

    def exit(self, plan_summary: str) -> str:
        self.pending_approval = True
        self.plan_summary = plan_summary
        return "计划已生成，等待用户审批。"

    def approve(self) -> str:
        self.is_active = False
        self.pending_approval = False
        return "计划已批准，将按计划执行。"

    def reject(self) -> str:
        self.is_active = False
        self.pending_approval = False
        return "计划已拒绝，已退出计划模式。"

    def get_system_prompt(self) -> str:
        return PLAN_SYSTEM_PROMPT


def _plans_dir() -> Path:
    root = ensure_xcode_home()
    plans = root / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    return plans


def write_plan_file(content: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = _plans_dir() / f"{ts}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
