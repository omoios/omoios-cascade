#!/usr/bin/env python3
"""Tier 1: Single feature addition (baseline).

Complexity: 1-2 workers, 2 files changed, ~20 lines added.
Task: Add a 'search' method to the task tracker + test it.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo, reset_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-1"

SCAFFOLD_FILES = {
    "app/__init__.py": "",
    "app/models.py": """\
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Status(Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass
class Task:
    title: str
    priority: Priority = Priority.MEDIUM
    status: Status = Status.TODO
    created_at: datetime = field(default_factory=datetime.now)
    task_id: int = 0
""",
    "app/store.py": """\
from app.models import Task


class TaskStore:
    def __init__(self):
        self._tasks: list[Task] = []
        self._next_id: int = 1

    def add(self, task: Task) -> Task:
        task.task_id = self._next_id
        self._next_id += 1
        self._tasks.append(task)
        return task

    def get(self, task_id: int) -> Task | None:
        for t in self._tasks:
            if t.task_id == task_id:
                return t
        return None

    def list_all(self) -> list[Task]:
        return list(self._tasks)
""",
    "tests/__init__.py": "",
    "tests/test_models.py": """\
from app.models import Task, Priority, Status
from app.store import TaskStore


def test_task_defaults():
    t = Task(title="Test")
    assert t.priority == Priority.MEDIUM
    assert t.status == Status.TODO


def test_task_custom_priority():
    t = Task(title="Urgent", priority=Priority.HIGH)
    assert t.priority == Priority.HIGH


def test_store_add_and_get():
    store = TaskStore()
    t = store.add(Task(title="Do laundry"))
    assert t.task_id == 1
    assert store.get(1) is not None
    assert store.get(999) is None
""",
}

INSTRUCTIONS = """\
Add a 'search' feature to the task tracker app.

1. In app/store.py, add a `search(self, keyword: str) -> list[Task]` method
   that returns all tasks whose title contains the keyword (case-insensitive).
2. In tests/test_models.py, add a test `test_search_tasks` that:
   - Creates a TaskStore with 3 tasks: "Buy groceries", "Read book", "Buy gifts"
   - Searches for "buy" and asserts it returns exactly 2 tasks
   - Searches for "read" and asserts it returns exactly 1 task
   - Searches for "xyz" and asserts it returns 0 tasks
3. Run `python -m pytest tests/ -v` to verify all tests pass.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=1,
        name="Single Feature Addition",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=120,
        expected_test_count=4,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
