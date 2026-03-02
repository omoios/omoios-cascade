#!/usr/bin/env python3
"""Tier 6: Full REST API Application (Task Management System).

Complexity: 8-12 workers, ~30 files, ~800 LOC.
Task: Build a complete REST API task management system with SQLite persistence,
multiple models (User, Project, Task, Comment, Label), full CRUD, search,
pagination, and comprehensive test coverage.

This tier tests the harness's ability to coordinate multiple workers building
a complex multi-model application with relationships and cross-cutting concerns.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-6"
WORKER_TIMEOUT = 300

SCAFFOLD_FILES = {
    "app/__init__.py": "",
    "app/models.py": '''\
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
class User:
    """A user in the system."""
    username: str
    email: str
    user_id: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Project:
    """A project containing tasks."""
    name: str
    description: str = ""
    owner_id: int = 0
    project_id: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Task:
    """A task within a project."""
    title: str
    description: str = ""
    project_id: int = 0
    assignee_id: int = 0
    priority: Priority = Priority.MEDIUM
    status: Status = Status.TODO
    task_id: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Comment:
    """A comment on a task."""
    task_id: int
    author_id: int
    content: str
    comment_id: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Label:
    """A label that can be attached to tasks."""
    name: str
    color: str = "#000000"
    label_id: int = 0
''',
    "tests/__init__.py": "",
    "tests/conftest.py": '''\
import pytest
from app.database import init_db


@pytest.fixture
def db_conn():
    """Provide an in-memory database connection."""
    conn = init_db(":memory:")
    yield conn
    conn.close()
''',
    "tests/test_basic.py": '''\
def test_placeholder():
    """Placeholder to ensure pytest discovers the tests directory."""
    assert True
''',
}

INSTRUCTIONS = """\
Build a complete REST API task management system. Use ONLY Python stdlib
(sqlite3, json, dataclasses, http.server, urllib.parse). No external dependencies.

MODULE 1 — Database Layer (`app/database.py`):

1. Create `init_db(db_path: str) -> sqlite3.Connection` function:
   - Create tables: users, projects, tasks, comments, labels, task_labels (junction)
   - users: user_id (PK), username (unique), email, created_at
   - projects: project_id (PK), name, description, owner_id (FK), created_at
   - tasks: task_id (PK), title, description, project_id (FK), assignee_id (FK),
            priority, status, created_at
   - comments: comment_id (PK), task_id (FK), author_id (FK), content, created_at
   - labels: label_id (PK), name (unique), color
   - task_labels: task_id (FK), label_id (FK), composite PK
   - Enable foreign keys via PRAGMA
   - Return the connection object

2. Create `get_connection(db_path: str = ":memory:") -> sqlite3.Connection`:
   - Returns a connection with row_factory = sqlite3.Row for dict-like access

MODULE 2 — Serializers (`app/serializers.py`):

3. Create serialization functions for all models:
   - `user_to_dict(user: User) -> dict` — convert User to dict
   - `user_from_dict(data: dict) -> User` — create User from dict
   - `project_to_dict(project: Project) -> dict`
   - `project_from_dict(data: dict) -> Project`
   - `task_to_dict(task: Task) -> dict`
   - `task_from_dict(data: dict) -> Task`
   - `comment_to_dict(comment: Comment) -> dict`
   - `comment_from_dict(data: dict) -> Comment`
   - `label_to_dict(label: Label) -> dict`
   - `label_from_dict(data: dict) -> Label`
   - Handle datetime serialization to ISO format
   - Handle Enum serialization to value

MODULE 3 — Validators (`app/validators.py`):

4. Create validation functions:
   - `validate_user(data: dict) -> tuple[bool, list[str]]` — validate username (required,
     3-50 chars), email (required, valid format). Returns (is_valid, list_of_errors).
   - `validate_project(data: dict) -> tuple[bool, list[str]]` — validate name (required,
     1-100 chars), description (optional, max 500 chars)
   - `validate_task(data: dict) -> tuple[bool, list[str]]` — validate title (required,
     1-200 chars), priority is one of "low"/"medium"/"high", status is one of
     "todo"/"in_progress"/"done"
   - `validate_comment(data: dict) -> tuple[bool, list[str]]` — validate content
     (required, 1-1000 chars), task_id and author_id are positive integers
   - `validate_label(data: dict) -> tuple[bool, list[str]]` — validate name (required,
     1-50 chars), color (valid hex color like #RRGGBB)

MODULE 4 — Custom Exceptions (`app/errors.py`):

5. Create exception hierarchy:
   - `class ApiError(Exception)` — base exception with message and status_code attrs
   - `class NotFoundError(ApiError)` — 404, resource not found
   - `class ValidationError(ApiError)` — 400, validation failed
   - `class UnauthorizedError(ApiError)` — 401, authentication required
   - `class ConflictError(ApiError)` — 409, resource conflict (e.g., duplicate username)

MODULE 5 — Pagination (`app/pagination.py`):

6. Create pagination helper:
   - `paginate(items: list, page: int = 1, per_page: int = 20) -> dict`:
     - Returns dict with: items (sliced list), page, per_page, total, total_pages,
       has_next, has_prev
   - Handle edge cases: page < 1 defaults to 1, per_page < 1 defaults to 20,
     per_page > 100 caps at 100

MODULE 6 — Search (`app/search.py`):

7. Create full-text search:
   - `search_tasks(conn, query: str, project_id: int | None = None) -> list[dict]`:
     - Search in tasks.title and tasks.description (case-insensitive LIKE)
     - Optional filter by project_id
     - Return list of task dicts with project_name and assignee_username joined
   - `search_projects(conn, query: str) -> list[dict]`:
     - Search in projects.name and projects.description
     - Return list with owner_username joined

MODULE 8 — CRUD Stores (`app/store.py`):

8. Create `UserStore` class:
   - `__init__(self, conn: sqlite3.Connection)`
   - `create(self, user: User) -> User` — insert, set user.user_id from lastrowid
   - `get_by_id(self, user_id: int) -> User | None`
   - `get_by_username(self, username: str) -> User | None`
   - `list_all(self) -> list[User]`
   - `update(self, user: User) -> User` — update by user_id
   - `delete(self, user_id: int) -> bool`

9. Create `ProjectStore` class:
   - Same CRUD pattern for Project
   - `list_by_owner(self, owner_id: int) -> list[Project]`
   - Include `get_with_owner(self, project_id: int) -> dict | None` returning project
     dict with owner dict nested

10. Create `TaskStore` class:
    - Same CRUD pattern for Task
    - `list_by_project(self, project_id: int) -> list[Task]`
    - `list_by_assignee(self, assignee_id: int) -> list[Task]`
    - `list_by_status(self, status: str) -> list[Task]`
    - `get_with_details(self, task_id: int) -> dict | None` returning task dict with
      project and assignee nested

11. Create `CommentStore` class:
    - Same CRUD pattern for Comment
    - `list_by_task(self, task_id: int) -> list[Comment]`
    - `list_by_task_with_author(self, task_id: int) -> list[dict]` with author nested

12. Create `LabelStore` class:
    - Same CRUD pattern for Label
    - `get_by_name(self, name: str) -> Label | None`
    - `attach_to_task(self, task_id: int, label_id: int) -> bool`
    - `detach_from_task(self, task_id: int, label_id: int) -> bool`
    - `get_for_task(self, task_id: int) -> list[Label]`

MODULE 9 — Routes Package (`app/routes/`):

13. Create `app/routes/__init__.py` — empty init file

14. Create `app/routes/users.py` with handler functions:
    - `create_user(store, data) -> tuple[int, dict]` — POST /users, validate,
      create, return 201 + user dict
    - `get_user(store, user_id) -> tuple[int, dict]` — GET /users/{id}, 200 or 404
    - `list_users(store) -> tuple[int, dict]` — GET /users, 200 + list
    - `update_user(store, user_id, data) -> tuple[int, dict]` — PUT /users/{id}
    - `delete_user(store, user_id) -> tuple[int, dict]` — DELETE /users/{id}
    - All handlers catch ApiError and return (status_code, {"error": message})

15. Create `app/routes/projects.py` with similar handlers for projects

16. Create `app/routes/tasks.py` with handlers for tasks plus:
    - `update_task_status(store, task_id, data)` — PATCH /tasks/{id}/status
    - `assign_task(store, task_id, data)` — PATCH /tasks/{id}/assign

17. Create `app/routes/comments.py` with handlers for comments

18. Create `app/routes/labels.py` with handlers for labels plus:
    - `attach_label(store, task_id, data)` — POST /tasks/{id}/labels
    - `detach_label(store, task_id, label_id)` — DELETE /tasks/{id}/labels/{label_id}

MODULE 10 — Middleware (`app/middleware.py`):

19. Create middleware functions:
    - `auth_middleware(request) -> dict | None` — check for Authorization header,
      extract user_id, return user dict or None
    - `logging_middleware(request, response, duration_ms)` — log request method,
      path, status code, duration
    - `error_handler(func)` — decorator that catches exceptions and returns
      appropriate error responses

MODULE 11 — Application (`app/app.py`):

20. Create `create_app(db_path: str = ":memory:")` function:
    - Initialize database, create all stores
    - Create a router/dispatcher that routes requests to handlers
    - Return an object with `dispatch(method, path, body, headers)` method

MODULE 12 — Tests (`tests/`):

21. Create `tests/test_validators.py` (5 tests):
    - test_validate_user_valid, test_validate_user_invalid_email,
    - test_validate_task_invalid_priority, test_validate_comment_empty_content,
    - test_validate_label_invalid_color

22. Create `tests/test_serializers.py` (5 tests):
    - test_user_to_dict, test_user_from_dict,
    - test_task_with_enums, test_comment_roundtrip, test_label_defaults

23. Create `tests/test_stores.py` (8 tests):
    - test_user_store_crud, test_project_store_list_by_owner,
    - test_task_store_list_by_project, test_comment_store_list_by_task,
    - test_label_store_attach_detach, test_task_store_get_with_details,
    - test_user_store_get_by_username, test_label_store_get_for_task

24. Create `tests/test_search.py` (4 tests):
    - test_search_tasks_by_title, test_search_tasks_by_description,
    - test_search_projects, test_search_tasks_with_project_filter

25. Create `tests/test_pagination.py` (3 tests):
    - test_pagination_first_page, test_pagination_edge_cases,
    - test_pagination_has_next_prev

26. Create `tests/test_routes.py` (6 tests):
    - test_create_user_route, test_get_user_not_found,
    - test_create_project_validation_error, test_task_status_update,
    - test_comment_on_task, test_attach_label_to_task

Run `python -m pytest tests/ -v` to verify ALL 31 tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No Flask, FastAPI, SQLAlchemy, etc.
- All database operations use sqlite3 with parameterization (no SQL injection)
- All timestamps use ISO format strings
- All enums serialize to their .value
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=6,
        name="REST API App (Multi-Model System)",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=300,
        expected_test_count=31,
        max_planner_turns=100,
        max_planner_wall_time=1200,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
