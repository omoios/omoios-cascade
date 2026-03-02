#!/usr/bin/env python3
"""Tier 4: Refactor existing code + add new features.

Complexity: 4-5 workers, 8-10 files changed, ~200 lines added.
Task: Replace in-memory TaskStore with SQLite persistence + add tags/categories.
This requires MODIFYING existing files AND creating new ones — tests must cover both.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-4"

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
    "app/store.py": '''\
from app.models import Task, Status


class TaskStore:
    """In-memory task store — to be replaced with SQLite."""

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

    def search(self, keyword: str) -> list[Task]:
        kw = keyword.lower()
        return [t for t in self._tasks if kw in t.title.lower()]
''',
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


def test_list_all():
    store = TaskStore()
    store.add(Task(title="A"))
    store.add(Task(title="B"))
    assert len(store.list_all()) == 2


def test_search():
    store = TaskStore()
    store.add(Task(title="Buy milk"))
    store.add(Task(title="Read book"))
    assert len(store.search("buy")) == 1
    assert len(store.search("xyz")) == 0


def test_update_status():
    store = TaskStore()
    store.add(Task(title="Do it"))
    updated = store.update_status(1, Status.DONE)
    assert updated.status == Status.DONE
""",
}

INSTRUCTIONS = """\
Perform a major refactor of the task tracker: replace the in-memory store with SQLite \
AND add a tagging/category system. Both changes touch overlapping files.

PART A — SQLite Persistence (refactor app/store.py):

1. Create `app/database.py` with:
   - `init_db(db_path: str) -> sqlite3.Connection` that creates the tasks table:
     (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
      priority TEXT DEFAULT 'medium', status TEXT DEFAULT 'todo',
      created_at TEXT NOT NULL)
   - Returns the connection object.

2. Rewrite `app/store.py` — Replace the in-memory `TaskStore` with `SqliteTaskStore`:
   - `__init__(self, db_path: str = ":memory:")` — calls init_db, stores connection
   - `add(self, task: Task) -> Task` — INSERT into tasks, set task.task_id from lastrowid
   - `get(self, task_id: int) -> Task | None` — SELECT by id
   - `delete(self, task_id: int) -> bool` — DELETE by id, return True if rowcount > 0
   - `list_all(self) -> list[Task]` — SELECT all, return as Task objects
   - `update_status(self, task_id: int, status: Status) -> Task | None` — UPDATE status
   - `search(self, keyword: str) -> list[Task]` — SELECT WHERE title LIKE %keyword%
   - `close(self)` — close the connection
   - Keep the class name importable as `TaskStore` for backward compatibility:
     add `TaskStore = SqliteTaskStore` at module level.

PART B — Tags System (new feature on top of SQLite):

3. Add a `tags` field to `app/models.py` Task dataclass: `tags: list[str] = field(default_factory=list)`

4. Create `app/tags.py` with:
   - Create a tags table: (id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES tasks(id), tag TEXT NOT NULL)
   - `add_tag(conn, task_id: int, tag: str) -> None`
   - `remove_tag(conn, task_id: int, tag: str) -> None`
   - `get_tags(conn, task_id: int) -> list[str]`
   - `find_by_tag(conn, tag: str) -> list[int]` — returns task_ids with that tag

5. Update `app/database.py` init_db to also create the tags table.

6. Update `app/store.py` SqliteTaskStore:
   - `add_tag(self, task_id: int, tag: str) -> None`
   - `remove_tag(self, task_id: int, tag: str) -> None`
   - `get_tags(self, task_id: int) -> list[str]`
   - `find_by_tag(self, tag: str) -> list[Task]` — returns full Task objects

TESTS — Update tests/test_store.py:

7. ALL existing tests must still pass (they use TaskStore which is now SqliteTaskStore).
8. Add new tests:
   - `test_sqlite_persistence`: Create store, add task, verify get() returns it
   - `test_add_tag`: Add task, add tag "urgent", verify get_tags returns ["urgent"]
   - `test_remove_tag`: Add tag, remove it, verify empty
   - `test_find_by_tag`: Add 3 tasks, tag 2 of them "work", find_by_tag("work") returns 2 tasks
   - `test_search_still_works`: Verify search("buy") still works with SQLite backend

Run `python -m pytest tests/ -v` to verify ALL tests pass (both old and new).

CONSTRAINTS:
- Only use Python stdlib (sqlite3 is stdlib).
- TaskStore must remain importable from app.store for backward compatibility.
- All SQLite stores use ":memory:" in tests (no file cleanup needed).
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=4,
        name="Refactor + Extend (SQLite + Tags)",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=180,
        expected_test_count=10,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
