#!/usr/bin/env python3
"""Tier 3: New module creation from scratch.

Complexity: 3-4 workers, 6-8 new files, ~150 lines added.
Task: Add a complete HTTP API layer with routing, handlers, serialization, and tests.
Workers must coordinate — the API layer depends on the existing store module.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-3"

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

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }
""",
    "app/store.py": """\
from app.models import Task, Status


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

    def update_status(self, task_id: int, status: Status) -> Task | None:
        task = self.get(task_id)
        if task:
            task.status = status
        return task
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


def test_update_status():
    store = TaskStore()
    store.add(Task(title="Do it"))
    updated = store.update_status(1, Status.DONE)
    assert updated.status == Status.DONE
""",
}

INSTRUCTIONS = """\
Build a complete HTTP-style API layer for the task tracker. This is a NEW module — \
you must create multiple new files. No external dependencies allowed (no Flask, no FastAPI). \
Use only Python stdlib.

WHAT TO BUILD:

1. `app/api/__init__.py` — empty init file for the api package.

2. `app/api/router.py` — A Router class that:
   - Stores route registrations as a list of (method, path_pattern, handler) tuples
   - Has a `route(method: str, path: str)` decorator for registering handlers
   - Has a `dispatch(method: str, path: str, body: dict | None = None) -> tuple[int, dict]` method
     that finds a matching route and calls the handler. Returns (status_code, response_body).
   - Supports path parameters like `/tasks/{task_id}` — extracts task_id as an int
   - Returns (404, {"error": "Not found"}) for unmatched routes

3. `app/api/handlers.py` — Handler functions that use a TaskStore instance:
   - `create_task(store, body)` — creates a task from body["title"] and optional body["priority"],
     returns (201, task.to_dict())
   - `get_task(store, task_id)` — returns (200, task.to_dict()) or (404, {"error": "Task not found"})
   - `list_tasks(store)` — returns (200, {"tasks": [t.to_dict() for t in store.list_all()]})
   - `delete_task(store, task_id)` — returns (200, {"deleted": True}) or (404, {"error": "Task not found"})
   - `update_task_status(store, task_id, body)` — updates status from body["status"],
     returns (200, task.to_dict()) or (404, {"error": "Task not found"})

4. `app/api/app.py` — A create_app(store: TaskStore) function that:
   - Creates a Router
   - Registers all handlers from handlers.py
   - Returns the router for dispatching

5. `tests/test_api.py` — Tests for the full API:
   - `test_create_task`: POST /tasks with {"title": "Test"} → 201 + task dict
   - `test_get_task`: Create a task, GET /tasks/1 → 200 + correct task
   - `test_get_task_not_found`: GET /tasks/999 → 404
   - `test_list_tasks`: Create 2 tasks, GET /tasks → 200 + list of 2
   - `test_delete_task`: Create + delete, GET returns 404
   - `test_update_status`: Create, PUT /tasks/1/status with {"status": "done"} → 200

Run `python -m pytest tests/ -v` to verify ALL tests pass.

CONSTRAINTS:
- No external dependencies. Only Python stdlib + the existing app modules.
- The Router.dispatch method is the entry point — no real HTTP server needed.
- All responses are (int, dict) tuples.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=3,
        name="New Module (API Layer)",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=180,
        expected_test_count=9,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
