from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass

from xcode_cli.core.tool_registry import ToolDef


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    blocked_by: list[str]
    blocks: list[str]


class TaskTracker:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create(self, subject: str, description: str) -> Task:
        task = Task(
            id=str(uuid.uuid4()),
            subject=subject,
            description=description,
            status="pending",
            blocked_by=[],
            blocks=[],
        )
        self._tasks[task.id] = task
        return task

    def update(self, task_id: str, status: str) -> Task:
        if task_id not in self._tasks:
            raise ValueError(f"Task not found: {task_id}")
        if status not in {"pending", "in_progress", "completed", "deleted"}:
            raise ValueError(f"Invalid status: {status}")
        self._tasks[task_id].status = status
        return self._tasks[task_id]

    def list_all(self) -> list[Task]:
        return list(self._tasks.values())

    def add_dependency(self, task_id: str, blocked_by_id: str) -> None:
        if task_id not in self._tasks:
            raise ValueError(f"Task not found: {task_id}")
        if blocked_by_id not in self._tasks:
            raise ValueError(f"Task not found: {blocked_by_id}")

        task = self._tasks[task_id]
        blocker = self._tasks[blocked_by_id]

        if blocked_by_id not in task.blocked_by:
            task.blocked_by.append(blocked_by_id)
        if task_id not in blocker.blocks:
            blocker.blocks.append(task_id)


def create_task_tools(task_tracker: TaskTracker) -> list[ToolDef]:
    def task_create(subject: str, description: str) -> str:
        task = task_tracker.create(subject=subject, description=description)
        return json.dumps(asdict(task), ensure_ascii=False)

    def task_update(task_id: str, status: str) -> str:
        task = task_tracker.update(task_id=task_id, status=status)
        return json.dumps(asdict(task), ensure_ascii=False)

    def task_list() -> str:
        tasks = [asdict(task) for task in task_tracker.list_all()]
        return json.dumps(tasks, ensure_ascii=False)

    return [
        ToolDef(
            name="task_create",
            description="Create a tracked task item.",
            parameters={
                "subject": {"type": "string", "description": "Short task title."},
                "description": {"type": "string", "description": "Detailed task description."},
            },
            required=["subject", "description"],
            execute=task_create,
            is_read_only=False,
        ),
        ToolDef(
            name="task_update",
            description="Update a tracked task status.",
            parameters={
                "task_id": {"type": "string", "description": "Task ID."},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "deleted"],
                    "description": "New task status.",
                },
            },
            required=["task_id", "status"],
            execute=task_update,
            is_read_only=False,
        ),
        ToolDef(
            name="task_list",
            description="List all tracked tasks.",
            parameters={},
            required=[],
            execute=task_list,
            is_read_only=True,
        ),
    ]
