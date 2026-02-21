from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Task(BaseModel):
    id: str = Field(description="Unique task identifier")
    parent_id: str | None = Field(default=None)
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    assigned_to: str | None = Field(default=None)
    repo: str | None = Field(default=None, description="Target repository path")
    blocked_by: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)
