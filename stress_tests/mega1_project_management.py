#!/usr/bin/env python3
"""Mega Tier 11: Full Project Management Platform.

Complexity: 80-120 workers, ~250 files, ~15K LOC.
Task: Build a complete project management platform with user system, projects,
tasks, kanban boards, gantt charts, time tracking, calendar, notifications,
reports, search, REST API, CLI, data export, permissions/RBAC, activity logs,
file attachments, comments, labels/tags, milestones, and sprint planning.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-mega-1"
WORKER_TIMEOUT = 900

SCAFFOLD_FILES = {
    "pm/__init__.py": '''\
"""Project Management Platform — A full-featured project management system."""

__version__ = "0.1.0"

from pm.models.user import User
from pm.models.project import Project
from pm.models.task import Task

__all__ = ["User", "Project", "Task"]
''',
    "pm/models/__init__.py": '''\
"""Core data models for the project management platform."""

from pm.models.user import User, UserRole, UserStatus
from pm.models.project import Project, ProjectStatus
from pm.models.task import Task, TaskStatus, TaskPriority
from pm.models.comment import Comment
from pm.models.label import Label
from pm.models.milestone import Milestone
from pm.models.sprint import Sprint

__all__ = [
    "User", "UserRole", "UserStatus",
    "Project", "ProjectStatus",
    "Task", "TaskStatus", "TaskPriority",
    "Comment", "Label", "Milestone", "Sprint",
]
''',
    "pm/models/user.py": '''\
"""User model with authentication and profile management."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto


class UserRole(Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"
    VIEWER = "viewer"


class UserStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"


@dataclass
class User:
    """A user in the project management system."""
    id: str
    email: str
    username: str
    full_name: str = ""
    role: UserRole = UserRole.MEMBER
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_login: datetime | None = None
    avatar_url: str = ""
    timezone: str = "UTC"
    locale: str = "en"
    metadata: dict = field(default_factory=dict)
''',
    "pm/models/project.py": '''\
"""Project model with team management."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ProjectStatus(Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"


@dataclass
class Project:
    """A project in the system."""
    id: str
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    owner_id: str = ""
    member_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    start_date: datetime | None = None
    end_date: datetime | None = None
    color: str = "#3B82F6"
    metadata: dict = field(default_factory=dict)
''',
    "pm/models/task.py": '''\
"""Task model with status and priority tracking."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Task:
    """A task in the project management system."""
    id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    project_id: str = ""
    assignee_id: str | None = None
    creator_id: str = ""
    parent_id: str | None = None
    milestone_id: str | None = None
    sprint_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    due_date: datetime | None = None
    completed_at: datetime | None = None
    estimated_hours: float = 0.0
    actual_hours: float = 0.0
    label_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
''',
    "pm/models/comment.py": '''\
"""Comment model for task discussions."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Comment:
    """A comment on a task or project."""
    id: str
    content: str
    author_id: str
    task_id: str | None = None
    project_id: str | None = None
    parent_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    edited: bool = False
    metadata: dict = field(default_factory=dict)
''',
    "pm/models/label.py": '''\
"""Label/tag model for categorization."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Label:
    """A label for tasks and projects."""
    id: str
    name: str
    color: str = "#6B7280"
    project_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)
''',
    "pm/models/milestone.py": '''\
"""Milestone model for project phases."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Milestone:
    """A milestone in a project."""
    id: str
    name: str
    description: str = ""
    project_id: str = ""
    due_date: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)
''',
    "pm/models/sprint.py": '''\
"""Sprint model for agile planning."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SprintStatus(Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Sprint:
    """A sprint for agile project management."""
    id: str
    name: str
    goal: str = ""
    project_id: str = ""
    status: SprintStatus = SprintStatus.PLANNING
    start_date: datetime | None = None
    end_date: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    velocity: float = 0.0
    metadata: dict = field(default_factory=dict)
''',
    "tests/__init__.py": "",
    "tests/conftest.py": """\
import pytest
from pm.models.user import User, UserRole, UserStatus
from pm.models.project import Project, ProjectStatus
from pm.models.task import Task, TaskStatus, TaskPriority


@pytest.fixture
def sample_user():
    return User(
        id="user-1",
        email="test@example.com",
        username="testuser",
        full_name="Test User",
        role=UserRole.MEMBER,
        status=UserStatus.ACTIVE
    )


@pytest.fixture
def sample_project():
    return Project(
        id="proj-1",
        name="Test Project",
        description="A test project",
        status=ProjectStatus.ACTIVE,
        owner_id="user-1"
    )


@pytest.fixture
def sample_task():
    return Task(
        id="task-1",
        title="Test Task",
        description="A test task",
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        project_id="proj-1",
        creator_id="user-1"
    )
""",
    "tests/test_models.py": """\
from pm.models.user import User, UserRole, UserStatus
from pm.models.project import Project, ProjectStatus
from pm.models.task import Task, TaskStatus, TaskPriority


def test_user_creation():
    user = User(id="u1", email="a@b.com", username="ab")
    assert user.role == UserRole.MEMBER
    assert user.status == UserStatus.ACTIVE


def test_project_defaults():
    proj = Project(id="p1", name="Test")
    assert proj.status == ProjectStatus.ACTIVE
    assert proj.member_ids == []


def test_task_status_transitions():
    task = Task(id="t1", title="Test")
    assert task.status == TaskStatus.TODO
    task.status = TaskStatus.IN_PROGRESS
    assert task.status == TaskStatus.IN_PROGRESS


def test_task_priority_order():
    assert TaskPriority.LOW.value < TaskPriority.MEDIUM.value
    assert TaskPriority.HIGH.value < TaskPriority.CRITICAL.value
""",
}

INSTRUCTIONS = """\
Build a FULL-FEATURED Project Management Platform called "pm". Use ONLY Python stdlib.
No external dependencies. This is a comprehensive project management system comparable
to Jira, Trello, or Asana with full user management, project organization, task tracking,
kanban boards, gantt charts, time tracking, calendar, notifications, reports, search,
REST API, CLI, data export, RBAC permissions, activity logs, file attachments, comments,
labels, milestones, and sprint planning.

=== SUBSYSTEM: Core Infrastructure ===

MODULE 1 — Storage Layer (`pm/storage/`):

1. Create `pm/storage/__init__.py` — export storage classes

2. Create `pm/storage/base.py`:
   - `StorageBackend` abstract base class with methods:
     - `get(self, key: str) -> dict | None`
     - `set(self, key: str, value: dict) -> None`
     - `delete(self, key: str) -> bool`
     - `keys(self, prefix: str = "") -> list[str]`
     - `scan(self, prefix: str = "") -> Iterator[tuple[str, dict]]`
   - `StorageError` exception class

3. Create `pm/storage/memory.py`:
   - `InMemoryStorage(StorageBackend)`:
     - `__init__(self)` — initialize empty dict storage
     - Thread-safe operations using threading.Lock
     - All base methods implemented with in-memory dict
     - `clear(self) -> None` — clear all data

4. Create `pm/storage/json_file.py`:
   - `JSONFileStorage(StorageBackend)`:
     - `__init__(self, data_dir: str)` — storage directory path
     - Store each record as separate JSON file: `{data_dir}/{key}.json`
     - Auto-create directories, handle file not found
     - Atomic writes using temp file + rename
     - `compact(self) -> None` — remove empty/orphaned files

5. Create `pm/storage/query.py`:
   - `Query` class for filtering records:
     - `__init__(self, storage: StorageBackend)`
     - `filter(self, **conditions) -> Query` — chainable filters
     - `equals(field, value)`, `contains(field, value)`, `in_list(field, values)`
     - `gt(field, value)`, `lt(field, value)`, `gte(field, value)`, `lte(field, value)`
     - `order_by(field: str, desc: bool = False) -> Query`
     - `limit(n: int) -> Query`
     - `offset(n: int) -> Query`
     - `execute(self) -> list[dict]` — run query and return results
   - `compile_conditions(conditions: dict) -> Callable` — helper

MODULE 2 — ID Generation (`pm/ids.py`):

6. Create `pm/ids.py`:
   - `generate_id(prefix: str = "") -> str` — UUID v4 with optional prefix
   - `generate_short_id(length: int = 8) -> str` — URL-safe random string
   - `snowflake_id() -> int` — Twitter-style snowflake ID (41-bit timestamp + 10-bit node + 12-bit sequence)
   - `IDGenerator` class for sequential IDs with prefix

MODULE 3 — Event System (`pm/events.py`):

7. Create `pm/events.py`:
   - `Event` dataclass: type, payload, timestamp, source
   - `EventBus` class:
     - `__init__(self)`
     - `subscribe(self, event_type: str, handler: Callable) -> None`
     - `unsubscribe(self, event_type: str, handler: Callable) -> None`
     - `publish(self, event: Event) -> None` — async notification
     - `publish_sync(self, event: Event) -> None` — immediate notification
   - Common event types: USER_CREATED, PROJECT_CREATED, TASK_CREATED, TASK_UPDATED, COMMENT_ADDED

=== SUBSYSTEM: User Management ===

MODULE 4 — User Repository (`pm/repos/user_repo.py`):

8. Create `pm/repos/__init__.py` — export repositories

9. Create `pm/repos/user_repo.py`:
   - `UserRepository` class:
     - `__init__(self, storage: StorageBackend)`
     - `create(self, user: User) -> User`
     - `get_by_id(self, user_id: str) -> User | None`
     - `get_by_email(self, email: str) -> User | None`
     - `get_by_username(self, username: str) -> User | None`
     - `update(self, user: User) -> User`
     - `delete(self, user_id: str) -> bool`
     - `list_all(self, limit: int = 100, offset: int = 0) -> list[User]`
     - `search(self, query: str) -> list[User]` — search by name/email
     - `count(self) -> int`

MODULE 5 — Authentication (`pm/auth/`):

10. Create `pm/auth/__init__.py` — export auth classes

11. Create `pm/auth/password.py`:
    - `hash_password(password: str) -> str` — PBKDF2-HMAC-SHA256 with salt
    - `verify_password(password: str, hashed: str) -> bool`
    - `generate_salt() -> str` — 32 bytes random, base64 encoded
    - `PasswordHasher` class with configurable iterations

12. Create `pm/auth/session.py`:
    - `Session` dataclass: id, user_id, created_at, expires_at, data
    - `SessionManager` class:
      - `__init__(self, storage: StorageBackend, ttl: int = 3600)`
      - `create(self, user_id: str) -> Session`
      - `get(self, session_id: str) -> Session | None`
      - `delete(self, session_id: str) -> bool`
      - `delete_user_sessions(self, user_id: str) -> int`
      - `cleanup_expired(self) -> int` — remove expired sessions

13. Create `pm/auth/token.py`:
    - `Token` dataclass: token, user_id, type, expires_at
    - `TokenManager` class:
      - `__init__(self, storage: StorageBackend)`
      - `create_access_token(self, user_id: str) -> str` — JWT-like token
      - `create_refresh_token(self, user_id: str) -> str`
      - `verify_token(self, token: str) -> Token | None`
      - `revoke_token(self, token: str) -> bool`
    - Token format: base64(header.payload.signature), HMAC-SHA256

MODULE 6 — User Service (`pm/services/user_service.py`):

14. Create `pm/services/__init__.py` — export services

15. Create `pm/services/user_service.py`:
    - `UserService` class:
      - `__init__(self, user_repo: UserRepository, password_hasher, session_manager)`
      - `register(self, email: str, username: str, password: str, full_name: str = "") -> tuple[User, Session]`
      - `login(self, email: str, password: str) -> tuple[User, Session] | None`
      - `logout(self, session_id: str) -> bool`
      - `change_password(self, user_id: str, old_password: str, new_password: str) -> bool`
      - `reset_password_request(self, email: str) -> str | None` — return reset token
      - `reset_password(self, token: str, new_password: str) -> bool`
      - `update_profile(self, user_id: str, **fields) -> User | None`
      - `deactivate_account(self, user_id: str) -> bool`
      - `list_users(self, role: UserRole | None = None, status: UserStatus | None = None) -> list[User]`
      - `update_user_role(self, admin_id: str, user_id: str, new_role: UserRole) -> bool`

=== SUBSYSTEM: Project Management ===

MODULE 7 — Project Repository (`pm/repos/project_repo.py`):

16. Create `pm/repos/project_repo.py`:
    - `ProjectRepository` class:
      - `__init__(self, storage: StorageBackend)`
      - `create(self, project: Project) -> Project`
      - `get_by_id(self, project_id: str) -> Project | None`
      - `update(self, project: Project) -> Project`
      - `delete(self, project_id: str) -> bool`
      - `list_by_owner(self, owner_id: str) -> list[Project]`
      - `list_by_member(self, user_id: str) -> list[Project]`
      - `add_member(self, project_id: str, user_id: str) -> bool`
      - `remove_member(self, project_id: str, user_id: str) -> bool`
      - `is_member(self, project_id: str, user_id: str) -> bool`
      - `search(self, query: str) -> list[Project]`
      - `archive(self, project_id: str) -> bool`
      - `unarchive(self, project_id: str) -> bool`

MODULE 8 — Task Repository (`pm/repos/task_repo.py`):

17. Create `pm/repos/task_repo.py`:
    - `TaskRepository` class:
      - `__init__(self, storage: StorageBackend)`
      - `create(self, task: Task) -> Task`
      - `get_by_id(self, task_id: str) -> Task | None`
      - `update(self, task: Task) -> Task`
      - `delete(self, task_id: str) -> bool`
      - `list_by_project(self, project_id: str, status: TaskStatus | None = None) -> list[Task]`
      - `list_by_assignee(self, user_id: str, status: TaskStatus | None = None) -> list[Task]`
      - `list_by_sprint(self, sprint_id: str) -> list[Task]`
      - `list_by_milestone(self, milestone_id: str) -> list[Task]`
      - `list_subtasks(self, parent_id: str) -> list[Task]`
      - `search(self, query: str, project_id: str | None = None) -> list[Task]`
      - `count_by_status(self, project_id: str) -> dict[TaskStatus, int]`
      - `update_status(self, task_id: str, new_status: TaskStatus, user_id: str) -> bool`
      - `assign(self, task_id: str, user_id: str | None, assigned_by: str) -> bool`
      - `set_priority(self, task_id: str, priority: TaskPriority) -> bool`
      - `set_due_date(self, task_id: str, due_date: datetime | None) -> bool`
      - `set_estimate(self, task_id: str, hours: float) -> bool`
      - `log_time(self, task_id: str, hours: float, user_id: str, description: str = "") -> bool`

MODULE 9 — Task Service (`pm/services/task_service.py`):

18. Create `pm/services/task_service.py`:
    - `TaskService` class:
      - `__init__(self, task_repo: TaskRepository, project_repo: ProjectRepository, event_bus: EventBus)`
      - `create_task(self, title: str, project_id: str, creator_id: str, **kwargs) -> Task`
      - `update_task(self, task_id: str, user_id: str, **kwargs) -> Task | None`
      - `delete_task(self, task_id: str, user_id: str) -> bool`
      - `move_task(self, task_id: str, new_status: TaskStatus, user_id: str) -> Task | None`
      - `assign_task(self, task_id: str, assignee_id: str | None, user_id: str) -> Task | None`
      - `add_subtask(self, parent_id: str, title: str, creator_id: str) -> Task`
      - `get_task_tree(self, task_id: str) -> dict` — task with nested subtasks
      - `bulk_update_status(self, task_ids: list[str], new_status: TaskStatus, user_id: str) -> int`
      - `get_tasks_by_user(self, user_id: str) -> list[Task]`
      - `get_overdue_tasks(self, project_id: str | None = None) -> list[Task]`
      - `complete_task(self, task_id: str, user_id: str) -> Task | None`
      - `reopen_task(self, task_id: str, user_id: str) -> Task | None`

MODULE 10 — Kanban Board (`pm/kanban/`):

19. Create `pm/kanban/__init__.py` — export kanban classes

20. Create `pm/kanban/board.py`:
    - `BoardColumn` dataclass: id, name, status, order, wip_limit
    - `KanbanBoard` class:
      - `__init__(self, project_id: str, columns: list[BoardColumn] | None = None)`
      - `get_columns(self) -> list[BoardColumn]`
      - `add_column(self, name: str, status: TaskStatus, wip_limit: int | None = None) -> BoardColumn`
      - `move_column(self, column_id: str, new_order: int) -> bool`
      - `delete_column(self, column_id: str) -> bool`
      - `get_column_tasks(self, column_id: str, task_repo: TaskRepository) -> list[Task]`
      - `can_add_to_column(self, column_id: str, current_count: int) -> bool` — check WIP limit
      - `serialize(self) -> dict`, `deserialize(data: dict) -> KanbanBoard` static method

21. Create `pm/kanban/swimlane.py`:
    - `Swimlane` dataclass: id, name, criteria (e.g., priority level, assignee)
    - `SwimlaneManager` class for organizing board by criteria

MODULE 11 — Gantt Chart (`pm/gantt/`):

22. Create `pm/gantt/__init__.py` — export gantt classes

23. Create `pm/gantt/chart.py`:
    - `GanttTask` dataclass: task_id, name, start_date, end_date, progress_percent, dependencies
    - `GanttChart` class:
      - `__init__(self, project_id: str, start_date: datetime, end_date: datetime)`
      - `add_task(self, task: GanttTask) -> None`
      - `remove_task(self, task_id: str) -> bool`
      - `update_task_dates(self, task_id: str, start: datetime, end: datetime) -> bool`
      - `set_task_progress(self, task_id: str, percent: int) -> bool`
      - `add_dependency(self, task_id: str, depends_on: str) -> bool`
      - `remove_dependency(self, task_id: str, depends_on: str) -> bool`
      - `get_critical_path(self) -> list[str]` — task IDs on critical path
      - `export_json(self) -> dict`
      - `calculate_dates_from_tasks(self, tasks: list[Task]) -> None`

24. Create `pm/gantt/renderer.py`:
    - `GanttRenderer` class:
      - `render_ascii(self, chart: GanttChart, width: int = 80) -> str` — ASCII art gantt chart
      - `render_text(self, chart: GanttChart) -> str` — text-based timeline
      - `render_csv(self, chart: GanttChart) -> str` — CSV export

=== SUBSYSTEM: Time Tracking ===

MODULE 12 — Time Tracking (`pm/time_tracking/`):

25. Create `pm/time_tracking/__init__.py` — export time tracking

26. Create `pm/time_tracking/models.py`:
    - `TimeEntry` dataclass: id, task_id, user_id, start_time, end_time, duration_minutes, description, billable
    - `Timer` dataclass: id, task_id, user_id, started_at, is_running

27. Create `pm/time_tracking/service.py`:
    - `TimeTrackingService` class:
      - `__init__(self, storage: StorageBackend)`
      - `start_timer(self, task_id: str, user_id: str) -> Timer`
      - `stop_timer(self, timer_id: str) -> TimeEntry`
      - `get_running_timer(self, user_id: str) -> Timer | None`
      - `log_time(self, task_id: str, user_id: str, minutes: int, description: str = "", billable: bool = True) -> TimeEntry`
      - `get_entries_by_task(self, task_id: str) -> list[TimeEntry]`
      - `get_entries_by_user(self, user_id: str, start: datetime | None = None, end: datetime | None = None) -> list[TimeEntry]`
      - `get_total_time(self, task_id: str) -> int` — minutes
      - `get_project_time_report(self, project_id: str, start: datetime, end: datetime) -> dict`
      - `get_user_time_report(self, user_id: str, start: datetime, end: datetime) -> dict`

MODULE 13 — Calendar (`pm/calendar/`):

28. Create `pm/calendar/__init__.py` — export calendar classes

29. Create `pm/calendar/models.py`:
    - `CalendarEvent` dataclass: id, title, description, start_time, end_time, creator_id, attendees, event_type, related_task_id, related_project_id
    - `EventType` enum: MEETING, DEADLINE, MILESTONE, REMINDER

30. Create `pm/calendar/service.py`:
    - `CalendarService` class:
      - `__init__(self, storage: StorageBackend)`
      - `create_event(self, title: str, start: datetime, end: datetime, creator_id: str, **kwargs) -> CalendarEvent`
      - `get_event(self, event_id: str) -> CalendarEvent | None`
      - `update_event(self, event_id: str, **kwargs) -> CalendarEvent | None`
      - `delete_event(self, event_id: str) -> bool`
      - `list_events(self, user_id: str, start: datetime, end: datetime) -> list[CalendarEvent]`
      - `get_events_by_project(self, project_id: str, start: datetime, end: datetime) -> list[CalendarEvent]`
      - `create_task_deadline_event(self, task: Task) -> CalendarEvent`
      - `create_milestone_event(self, milestone: Milestone) -> CalendarEvent`
      - `export_ical(self, events: list[CalendarEvent]) -> str` — iCal format export

=== SUBSYSTEM: Comments & Collaboration ===

MODULE 14 — Comment Repository (`pm/repos/comment_repo.py`):

31. Create `pm/repos/comment_repo.py`:
    - `CommentRepository` class:
      - `__init__(self, storage: StorageBackend)`
      - `create(self, comment: Comment) -> Comment`
      - `get_by_id(self, comment_id: str) -> Comment | None`
      - `update(self, comment: Comment) -> Comment`
      - `delete(self, comment_id: str) -> bool`
      - `list_by_task(self, task_id: str, limit: int = 50) -> list[Comment]`
      - `list_by_project(self, project_id: str, limit: int = 50) -> list[Comment]`
      - `list_replies(self, parent_id: str) -> list[Comment]`
      - `count_by_task(self, task_id: str) -> int`

MODULE 15 — Comment Service (`pm/services/comment_service.py`):

32. Create `pm/services/comment_service.py`:
    - `CommentService` class:
      - `__init__(self, comment_repo: CommentRepository, event_bus: EventBus)`
      - `add_comment(self, content: str, author_id: str, task_id: str | None = None, project_id: str | None = None) -> Comment`
      - `add_reply(self, content: str, author_id: str, parent_id: str) -> Comment`
      - `edit_comment(self, comment_id: str, new_content: str, user_id: str) -> Comment | None`
      - `delete_comment(self, comment_id: str, user_id: str) -> bool`
      - `get_task_comments(self, task_id: str) -> list[Comment]`
      - `get_thread(self, comment_id: str) -> list[Comment]` — comment with all replies

=== SUBSYSTEM: Labels, Milestones, Sprints ===

MODULE 16 — Label Repository (`pm/repos/label_repo.py`):

33. Create `pm/repos/label_repo.py`:
    - `LabelRepository` class:
      - `__init__(self, storage: StorageBackend)`
      - `create(self, label: Label) -> Label`
      - `get_by_id(self, label_id: str) -> Label | None`
      - `update(self, label: Label) -> Label`
      - `delete(self, label_id: str) -> bool`
      - `list_by_project(self, project_id: str | None) -> list[Label]`
      - `get_by_name(self, name: str, project_id: str | None) -> Label | None`

MODULE 17 — Milestone Repository (`pm/repos/milestone_repo.py`):

34. Create `pm/repos/milestone_repo.py`:
    - `MilestoneRepository` class:
      - `__init__(self, storage: StorageBackend)`
      - `create(self, milestone: Milestone) -> Milestone`
      - `get_by_id(self, milestone_id: str) -> Milestone | None`
      - `update(self, milestone: Milestone) -> Milestone`
      - `delete(self, milestone_id: str) -> bool`
      - `list_by_project(self, project_id: str) -> list[Milestone]`
      - `list_open(self, project_id: str) -> list[Milestone]`
      - `list_completed(self, project_id: str) -> list[Milestone]`
      - `complete(self, milestone_id: str) -> bool`
      - `get_progress(self, milestone_id: str, task_repo: TaskRepository) -> tuple[int, int]` — completed/total tasks

MODULE 18 — Sprint Repository (`pm/repos/sprint_repo.py`):

35. Create `pm/repos/sprint_repo.py`:
    - `SprintRepository` class:
      - `__init__(self, storage: StorageBackend)`
      - `create(self, sprint: Sprint) -> Sprint`
      - `get_by_id(self, sprint_id: str) -> Sprint | None`
      - `update(self, sprint: Sprint) -> Sprint`
      - `delete(self, sprint_id: str) -> bool`
      - `list_by_project(self, project_id: str) -> list[Sprint]`
      - `get_active(self, project_id: str) -> Sprint | None`
      - `start_sprint(self, sprint_id: str) -> bool`
      - `complete_sprint(self, sprint_id: str) -> bool`
      - `cancel_sprint(self, sprint_id: str) -> bool`
      - `add_task(self, sprint_id: str, task_id: str) -> bool`
      - `remove_task(self, sprint_id: str, task_id: str) -> bool`
      - `get_sprint_tasks(self, sprint_id: str, task_repo: TaskRepository) -> list[Task]`
      - `calculate_velocity(self, sprint_id: str, task_repo: TaskRepository) -> float`

MODULE 19 — Sprint Planning (`pm/sprint_planning/`):

36. Create `pm/sprint_planning/__init__.py`

37. Create `pm/sprint_planning/planner.py`:
    - `SprintPlanner` class:
      - `__init__(self, sprint_repo: SprintRepository, task_repo: TaskRepository)`
      - `plan_sprint(self, project_id: str, name: str, goal: str, duration_weeks: int, backlog_task_ids: list[str]) -> Sprint`
      - `estimate_capacity(self, team_member_ids: list[str], velocity_per_person: float = 10.0) -> float`
      - `suggest_tasks_for_sprint(self, project_id: str, target_points: float) -> list[str]`
      - `auto_assign_tasks(self, sprint_id: str, strategy: str = "round_robin") -> dict[str, str]` — task_id -> user_id

=== SUBSYSTEM: Notifications ===

MODULE 20 — Notifications (`pm/notifications/`):

38. Create `pm/notifications/__init__.py` — export notification classes

39. Create `pm/notifications/models.py`:
    - `Notification` dataclass: id, user_id, type, title, message, data, read, created_at
    - `NotificationType` enum: TASK_ASSIGNED, TASK_COMPLETED, COMMENT_ADDED, MENTIONED, SPRINT_STARTED, DEADLINE_APPROACHING

40. Create `pm/notifications/service.py`:
    - `NotificationService` class:
      - `__init__(self, storage: StorageBackend)`
      - `create_notification(self, user_id: str, type: NotificationType, title: str, message: str, data: dict | None = None) -> Notification`
      - `get_notification(self, notification_id: str) -> Notification | None`
      - `mark_as_read(self, notification_id: str) -> bool`
      - `mark_all_as_read(self, user_id: str) -> int`
      - `list_unread(self, user_id: str, limit: int = 50) -> list[Notification]`
      - `list_all(self, user_id: str, limit: int = 50) -> list[Notification]`
      - `delete_old_notifications(self, days: int = 30) -> int`
    - Subscribe to EventBus for automatic notification creation

=== SUBSYSTEM: Search ===

MODULE 21 — Search Engine (`pm/search/`):

41. Create `pm/search/__init__.py` — export search classes

42. Create `pm/search/index.py`:
    - `SearchIndex` class:
      - `__init__(self, storage: StorageBackend)`
      - `index_document(self, doc_id: str, content: str, doc_type: str, metadata: dict) -> None`
      - `remove_document(self, doc_id: str) -> bool`
      - `search(self, query: str, doc_types: list[str] | None = None, limit: int = 20) -> list[SearchResult]`
      - `reindex_all(self) -> None` — rebuild from storage
    - Tokenize using simple word splitting, lowercase, remove common stop words
    - Inverted index: word -> list of doc_ids with positions

43. Create `pm/search/models.py`:
    - `SearchResult` dataclass: doc_id, doc_type, title, snippet, score, highlights

44. Create `pm/search/service.py`:
    - `SearchService` class:
      - `__init__(self, index: SearchIndex)`
      - `search_tasks(self, query: str, project_id: str | None = None) -> list[SearchResult]`
      - `search_projects(self, query: str) -> list[SearchResult]`
      - `search_users(self, query: str) -> list[SearchResult]`
      - `search_comments(self, query: str, task_id: str | None = None) -> list[SearchResult]`
      - `global_search(self, query: str) -> dict[str, list[SearchResult]]` — results by type
      - `autocomplete(self, query: str, limit: int = 10) -> list[str]`

=== SUBSYSTEM: Reports & Analytics ===

MODULE 22 — Reports (`pm/reports/`):

45. Create `pm/reports/__init__.py` — export report classes

46. Create `pm/reports/generators.py`:
    - `ReportGenerator` base class with `generate(self, params: dict) -> ReportData`
    - `BurndownReportGenerator` — sprint burndown chart data
    - `VelocityReportGenerator` — team velocity over sprints
    - `TaskCompletionReportGenerator` — tasks completed by time period
    - `TimeTrackingReportGenerator` — time logged by user/project
    - `ProjectHealthReportGenerator` — overall project metrics

47. Create `pm/reports/models.py`:
    - `ReportData` dataclass: title, generated_at, parameters, data_points, summary
    - `ReportType` enum: BURNDOWN, VELOCITY, COMPLETION, TIME, HEALTH

48. Create `pm/reports/service.py`:
    - `ReportService` class:
      - `__init__(self, generators: dict[ReportType, ReportGenerator])`
      - `generate_report(self, report_type: ReportType, params: dict) -> ReportData`
      - `export_csv(self, report_data: ReportData) -> str`
      - `export_json(self, report_data: ReportData) -> str`
      - `get_available_reports(self) -> list[ReportType]`

=== SUBSYSTEM: RBAC & Permissions ===

MODULE 23 — Permissions (`pm/permissions/`):

49. Create `pm/permissions/__init__.py` — export permission classes

50. Create `pm/permissions/models.py`:
    - `Permission` enum: PROJECT_CREATE, PROJECT_READ, PROJECT_UPDATE, PROJECT_DELETE, TASK_CREATE, TASK_READ, TASK_UPDATE, TASK_DELETE, TASK_ASSIGN, COMMENT_CREATE, COMMENT_DELETE, MEMBER_INVITE, MEMBER_REMOVE, ADMIN_ACCESS
    - `RolePermissions` dataclass: role, permissions list

51. Create `pm/permissions/engine.py`:
    - `PermissionEngine` class:
      - `__init__(self)`
      - `has_permission(self, user: User, project: Project, permission: Permission) -> bool`
      - `check_permission(self, user: User, project: Project, permission: Permission) -> None` — raise if denied
      - `get_user_permissions(self, user: User, project: Project) -> list[Permission]`
      - `can_access_task(self, user: User, task: Task, project: Project) -> bool`
      - `can_modify_task(self, user: User, task: Task, project: Project) -> bool`
    - Role hierarchy: ADMIN > MANAGER > MEMBER > VIEWER
    - Project owner always has all permissions

MODULE 24 — Activity Log (`pm/activity/`):

52. Create `pm/activity/__init__.py` — export activity classes

53. Create `pm/activity/models.py`:
    - `Activity` dataclass: id, actor_id, action, entity_type, entity_id, old_values, new_values, timestamp, project_id
    - `ActionType` enum: CREATED, UPDATED, DELETED, ASSIGNED, STATUS_CHANGED, COMMENTED

54. Create `pm/activity/logger.py`:
    - `ActivityLogger` class:
      - `__init__(self, storage: StorageBackend)`
      - `log(self, activity: Activity) -> None`
      - `get_activity_for_project(self, project_id: str, limit: int = 50) -> list[Activity]`
      - `get_activity_for_user(self, user_id: str, limit: int = 50) -> list[Activity]`
      - `get_activity_for_entity(self, entity_type: str, entity_id: str) -> list[Activity]`
      - `get_recent_activity(self, limit: int = 50) -> list[Activity]`
    - Subscribe to EventBus for automatic activity logging

=== SUBSYSTEM: Export ===

MODULE 25 — Data Export (`pm/export/`):

55. Create `pm/export/__init__.py` — export export classes

56. Create `pm/export/exporters.py`:
    - `Exporter` base class
    - `CSVExporter` — export tasks, projects, time entries as CSV
    - `JSONExporter` — full JSON export with relationships
    - `MarkdownExporter` — export tasks as markdown documents

57. Create `pm/export/service.py`:
    - `ExportService` class:
      - `__init__(self, exporters: dict[str, Exporter])`
      - `export_project(self, project_id: str, format: str) -> str` — return file content
      - `export_tasks(self, task_ids: list[str], format: str) -> str`
      - `export_time_report(self, project_id: str, start: datetime, end: datetime, format: str) -> str`
      - `generate_backup(self) -> str` — full system backup as JSON

=== SUBSYSTEM: REST API ===

MODULE 26 — API Layer (`pm/api/`):

58. Create `pm/api/__init__.py` — export API classes

59. Create `pm/api/models.py`:
    - Request/response dataclasses for API
    - `ApiResponse` dataclass: success, data, error, meta
    - `Pagination` dataclass: page, per_page, total, total_pages
    - `ListResponse` dataclass: items, pagination

60. Create `pm/api/middleware.py`:
    - `AuthMiddleware` — extract and verify session/token from request
    - `RateLimitMiddleware` — simple rate limiting by IP/user
    - `CorsMiddleware` — CORS headers
    - `LoggingMiddleware` — request/response logging

61. Create `pm/api/routes/auth.py`:
    - `AuthRoutes` class:
      - `register(request) -> ApiResponse`
      - `login(request) -> ApiResponse`
      - `logout(request) -> ApiResponse`
      - `refresh_token(request) -> ApiResponse`
      - `reset_password(request) -> ApiResponse`

62. Create `pm/api/routes/users.py`:
    - `UserRoutes` class:
      - `get_profile(request) -> ApiResponse`
      - `update_profile(request) -> ApiResponse`
      - `change_password(request) -> ApiResponse`
      - `list_users(request) -> ListResponse`
      - `get_user(request, user_id) -> ApiResponse`

63. Create `pm/api/routes/projects.py`:
    - `ProjectRoutes` class:
      - `create_project(request) -> ApiResponse`
      - `list_projects(request) -> ListResponse`
      - `get_project(request, project_id) -> ApiResponse`
      - `update_project(request, project_id) -> ApiResponse`
      - `delete_project(request, project_id) -> ApiResponse`
      - `add_member(request, project_id) -> ApiResponse`
      - `remove_member(request, project_id, user_id) -> ApiResponse`
      - `archive_project(request, project_id) -> ApiResponse`

64. Create `pm/api/routes/tasks.py`:
    - `TaskRoutes` class:
      - `create_task(request) -> ApiResponse`
      - `list_tasks(request) -> ListResponse` — with filters
      - `get_task(request, task_id) -> ApiResponse`
      - `update_task(request, task_id) -> ApiResponse`
      - `delete_task(request, task_id) -> ApiResponse`
      - `move_task(request, task_id) -> ApiResponse` — change status
      - `assign_task(request, task_id) -> ApiResponse`

65. Create `pm/api/routes/comments.py`:
    - `CommentRoutes` class:
      - `add_comment(request) -> ApiResponse`
      - `list_comments(request, task_id) -> ListResponse`
      - `update_comment(request, comment_id) -> ApiResponse`
      - `delete_comment(request, comment_id) -> ApiResponse`

66. Create `pm/api/routes/sprints.py`:
    - `SprintRoutes` class:
      - `create_sprint(request) -> ApiResponse`
      - `list_sprints(request, project_id) -> ListResponse`
      - `get_sprint(request, sprint_id) -> ApiResponse`
      - `update_sprint(request, sprint_id) -> ApiResponse`
      - `start_sprint(request, sprint_id) -> ApiResponse`
      - `complete_sprint(request, sprint_id) -> ApiResponse`
      - `add_task_to_sprint(request, sprint_id) -> ApiResponse`

67. Create `pm/api/routes/search.py`:
    - `SearchRoutes` class:
      - `search(request) -> ApiResponse` — global search
      - `autocomplete(request) -> ApiResponse`

68. Create `pm/api/server.py`:
    - `APIServer` class:
      - `__init__(self, services: dict, host: str = "localhost", port: int = 8000)`
      - `register_routes(self) -> None` — register all route handlers
      - `handle_request(self, request: dict) -> dict` — main entry point
      - `serve_forever(self) -> None` — start HTTP server using http.server
      - `shutdown(self) -> None`
    - Request format: {"method": "POST", "path": "/api/tasks", "headers": {}, "body": {}}
    - Response format: {"status": 200, "headers": {}, "body": json_string}

=== SUBSYSTEM: CLI ===

MODULE 27 — CLI (`pm/cli/`):

69. Create `pm/cli/__init__.py` — export CLI classes

70. Create `pm/cli/base.py`:
    - `Command` dataclass: name, description, usage, handler
    - `CommandContext` dataclass: services, current_user, config

71. Create `pm/cli/commands/auth.py`:
    - `login(ctx, email, password) -> str` — authenticate and store session
    - `logout(ctx) -> str`
    - `register(ctx, email, username, password, full_name) -> str`
    - `whoami(ctx) -> str`

72. Create `pm/cli/commands/projects.py`:
    - `project_list(ctx) -> str` — table of projects
    - `project_create(ctx, name, description) -> str`
    - `project_show(ctx, project_id) -> str` — detailed view
    - `project_archive(ctx, project_id) -> str`
    - `project_members(ctx, project_id) -> str`
    - `project_add_member(ctx, project_id, email) -> str`

73. Create `pm/cli/commands/tasks.py`:
    - `task_list(ctx, project_id, status) -> str` — table/list of tasks
    - `task_show(ctx, task_id) -> str` — detailed task view
    - `task_create(ctx, project_id, title, description, priority) -> str`
    - `task_update(ctx, task_id, **kwargs) -> str`
    - `task_delete(ctx, task_id) -> str`
    - `task_move(ctx, task_id, status) -> str` — move to new status
    - `task_assign(ctx, task_id, user_id) -> str`
    - `my_tasks(ctx, status) -> str` — tasks assigned to current user

74. Create `pm/cli/commands/sprints.py`:
    - `sprint_list(ctx, project_id) -> str`
    - `sprint_create(ctx, project_id, name, goal, duration) -> str`
    - `sprint_start(ctx, sprint_id) -> str`
    - `sprint_complete(ctx, sprint_id) -> str`
    - `sprint_tasks(ctx, sprint_id) -> str`

75. Create `pm/cli/commands/time.py`:
    - `timer_start(ctx, task_id) -> str`
    - `timer_stop(ctx) -> str`
    - `time_log(ctx, task_id, minutes, description) -> str`
    - `time_report(ctx, project_id, days) -> str`

76. Create `pm/cli/main.py`:
    - `CLI` class:
      - `__init__(self, context: CommandContext)`
      - `run(self) -> None` — main REPL loop
      - `parse_command(self, line: str) -> tuple[str, list, dict]` — parse "cmd arg1 arg2 --flag=value"
      - `execute(self, command: str, args: list, kwargs: dict) -> str`
      - `print_help(self) -> str`
      - `complete(self, text: str, state: int) -> str | None` — tab completion
    - Main commands: login, logout, projects, tasks, sprints, time, search, help, quit
    - Prompt: "pm> " or "pm [project]> " when project selected

=== SUBSYSTEM: File Attachments (Stub) ===

MODULE 28 — Attachments (`pm/attachments/`):

77. Create `pm/attachments/__init__.py`

78. Create `pm/attachments/models.py`:
    - `Attachment` dataclass: id, filename, original_name, size, mime_type, uploaded_by, uploaded_at, task_id, storage_path

79. Create `pm/attachments/service.py`:
    - `AttachmentService` class (stub implementation):
      - `__init__(self, storage_dir: str)`
      - `upload(self, data: bytes, filename: str, user_id: str, task_id: str) -> Attachment` — save to disk, return metadata
      - `download(self, attachment_id: str) -> tuple[bytes, str] | None` — return data and filename
      - `delete(self, attachment_id: str) -> bool`
      - `list_by_task(self, task_id: str) -> list[Attachment]`
      - `get_info(self, attachment_id: str) -> Attachment | None`

=== SUBSYSTEM: Tests ===

MODULE 29 — Test Suite (`tests/`):

80. Create `tests/storage/` with `__init__.py`:
    - `test_base.py` (3 tests): test_abstract_methods, test_storage_error
    - `test_memory.py` (4 tests): test_get_set, test_delete, test_keys, test_thread_safety
    - `test_json_file.py` (4 tests): test_persistence, test_atomic_write, test_scan, test_compact
    - `test_query.py` (5 tests): test_filter_equals, test_filter_range, test_order_by, test_limit_offset, test_chain_filters

81. Create `tests/auth/` with `__init__.py`:
    - `test_password.py` (3 tests): test_hash_verify, test_different_passwords_different_hashes, test_salt_generation
    - `test_session.py` (4 tests): test_create_session, test_get_session, test_expired_session, test_cleanup_expired
    - `test_token.py` (3 tests): test_create_token, test_verify_token, test_revoke_token

82. Create `tests/repos/` with `__init__.py`:
    - `test_user_repo.py` (5 tests): test_create_user, test_get_by_email, test_search_users, test_update_user, test_list_all
    - `test_project_repo.py` (5 tests): test_create_project, test_add_member, test_list_by_member, test_archive, test_search
    - `test_task_repo.py` (6 tests): test_create_task, test_list_by_project, test_update_status, test_assign, test_search, test_count_by_status
    - `test_comment_repo.py` (4 tests): test_create_comment, test_list_by_task, test_replies, test_count_by_task
    - `test_label_repo.py` (3 tests): test_create_label, test_list_by_project, test_get_by_name
    - `test_milestone_repo.py` (4 tests): test_create_milestone, test_list_open, test_complete, test_get_progress
    - `test_sprint_repo.py` (5 tests): test_create_sprint, test_start_sprint, test_add_task, test_get_velocity, test_active_sprint

83. Create `tests/services/` with `__init__.py`:
    - `test_user_service.py` (4 tests): test_register, test_login, test_update_profile, test_change_password
    - `test_task_service.py` (5 tests): test_create_task, test_move_task, test_assign_task, test_bulk_update, test_complete_task
    - `test_comment_service.py` (3 tests): test_add_comment, test_add_reply, test_edit_comment

84. Create `tests/kanban/` with `__init__.py`:
    - `test_board.py` (4 tests): test_add_column, test_move_column, test_wip_limit, test_serialize

85. Create `tests/gantt/` with `__init__.py`:
    - `test_chart.py` (3 tests): test_add_task, test_dependencies, test_critical_path
    - `test_renderer.py` (2 tests): test_render_ascii, test_render_csv

86. Create `tests/time_tracking/` with `__init__.py`:
    - `test_service.py` (4 tests): test_start_stop_timer, test_log_time, test_get_entries, test_time_report

87. Create `tests/calendar/` with `__init__.py`:
    - `test_service.py` (3 tests): test_create_event, test_list_events, test_export_ical

88. Create `tests/notifications/` with `__init__.py`:
    - `test_service.py` (3 tests): test_create_notification, test_mark_read, test_list_unread

89. Create `tests/search/` with `__init__.py`:
    - `test_index.py` (3 tests): test_index_document, test_search, test_remove_document
    - `test_service.py` (3 tests): test_search_tasks, test_global_search, test_autocomplete

90. Create `tests/reports/` with `__init__.py`:
    - `test_generators.py` (3 tests): test_burndown, test_velocity, test_completion

91. Create `tests/permissions/` with `__init__.py`:
    - `test_engine.py` (4 tests): test_has_permission, test_role_hierarchy, test_owner_permissions, test_check_permission_raises

92. Create `tests/activity/` with `__init__.py`:
    - `test_logger.py` (3 tests): test_log_activity, test_get_project_activity, test_get_entity_activity

93. Create `tests/api/` with `__init__.py`:
    - `test_routes_auth.py` (3 tests): test_register, test_login, test_logout
    - `test_routes_projects.py` (4 tests): test_create_project, test_list_projects, test_get_project, test_archive
    - `test_routes_tasks.py` (4 tests): test_create_task, test_list_tasks, test_update_task, test_move_task

94. Create `tests/cli/` with `__init__.py`:
    - `test_commands.py` (3 tests): test_login_command, test_project_list, test_task_create

Run `python -m pytest tests/ -v` to verify ALL 120+ tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No Flask, Django, FastAPI, SQLAlchemy, or external packages.
- HTTP server uses http.server from stdlib.
- Database is file-based JSON or in-memory storage.
- Authentication uses PBKDF2 from hashlib, not bcrypt.
- Search is inverted index implementation, not Elasticsearch.
- All datetimes use datetime module with timezone.utc.
- All file operations use pathlib.Path.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=11,
        name="MEGA-1: Project Management Platform",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=WORKER_TIMEOUT,
        expected_test_count=120,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
