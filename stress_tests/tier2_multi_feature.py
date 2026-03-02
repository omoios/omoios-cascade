#!/usr/bin/env python3
"""Tier 2: Multi-feature addition with cross-file coordination.

Complexity: 2-3 workers, 4-5 files changed, ~80 lines added.
Task: Add filtering by status, sorting by priority, and bulk status update.
Each feature touches store.py AND needs its own test function.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-2"

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

    def __lt__(self, other):
        order = {Priority.LOW: 0, Priority.MEDIUM: 1, Priority.HIGH: 2}
        return order[self] < order[other]


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

    def delete(self, task_id: int) -> bool:
        for i, t in enumerate(self._tasks):
            if t.task_id == task_id:
                self._tasks.pop(i)
                return True
        return False

    def list_all(self) -> list[Task]:
        return list(self._tasks)

    def search(self, keyword: str) -> list[Task]:
        kw = keyword.lower()
        return [t for t in self._tasks if kw in t.title.lower()]
""",
    "tests/__init__.py": "",
    "tests/test_store.py": """\
from app.models import Task, Priority, Status
from app.store import TaskStore


def test_add_and_get():
    store = TaskStore()
    t = store.add(Task(title="Test"))
    assert t.task_id == 1
    assert store.get(1).title == "Test"


def test_delete():
    store = TaskStore()
    store.add(Task(title="Remove me"))
    assert store.delete(1) is True
    assert store.get(1) is None
    assert store.delete(999) is False


def test_list_all():
    store = TaskStore()
    store.add(Task(title="A"))
    store.add(Task(title="B"))
    assert len(store.list_all()) == 2


def test_search():
    store = TaskStore()
    store.add(Task(title="Buy milk"))
    store.add(Task(title="Read book"))
    store.add(Task(title="Buy eggs"))
    assert len(store.search("buy")) == 2
    assert len(store.search("xyz")) == 0
""",
}

INSTRUCTIONS = """\
Add three new features to the task tracker app. Each feature needs implementation AND tests.

FEATURE 1 — Filter by Status:
In app/store.py, add `filter_by_status(self, status: Status) -> list[Task]`
that returns all tasks matching the given status.

FEATURE 2 — Sort by Priority:
In app/store.py, add `sort_by_priority(self, descending: bool = True) -> list[Task]`
that returns all tasks sorted by priority. HIGH first when descending=True.
Use the Priority.__lt__ method already defined in models.py.

FEATURE 3 — Bulk Status Update:
In app/store.py, add `bulk_update_status(self, task_ids: list[int], new_status: Status) -> int`
that updates all tasks with matching IDs to new_status. Returns count of tasks updated.

TESTS — Add to tests/test_store.py:
- `test_filter_by_status`: Create 3 tasks with mixed statuses, filter for TODO, verify count.
- `test_sort_by_priority_desc`: Create tasks with LOW/HIGH/MEDIUM priority, sort descending,
  verify HIGH is first and LOW is last.
- `test_sort_by_priority_asc`: Same but ascending, verify LOW first.
- `test_bulk_update_status`: Create 3 tasks, bulk update 2 of them to DONE,
  verify those 2 are DONE and the third is unchanged.

Run `python -m pytest tests/ -v` to verify all tests pass.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=2,
        name="Multi-Feature Addition",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=150,
        expected_test_count=8,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
