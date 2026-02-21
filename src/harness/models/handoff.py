from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class HandoffStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    BLOCKED = "blocked"


class FileDiff(BaseModel):
    path: str
    before_hash: str | None = None
    after_hash: str | None = None
    diff_text: str


class HandoffMetrics(BaseModel):
    wall_time_seconds: float
    tokens_used: int
    attempts: int
    files_modified: int
    tool_calls: int = 0


class Handoff(BaseModel):
    agent_id: str
    task_id: str
    status: HandoffStatus
    diffs: list[FileDiff] = Field(default_factory=list)
    narrative: str = Field(description="What was done, concerns, suggestions — THE critical field")
    artifacts: list[str] = Field(default_factory=list)
    metrics: HandoffMetrics
    error_message: str | None = None
    submitted_at: datetime = Field(default_factory=datetime.now)

    @field_validator("narrative")
    @classmethod
    def narrative_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Handoff narrative must not be empty")
        return v
