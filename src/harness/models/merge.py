from enum import Enum

from pydantic import BaseModel, Field

from harness.models.task import Task


class MergeStatus(str, Enum):
    CLEAN = "clean"
    CONFLICT = "conflict"
    NO_CHANGES = "no_changes"


class MergeResult(BaseModel):
    worker_id: str
    status: MergeStatus
    files_merged: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    fix_forward_task: Task | None = None


class ReconciliationRound(BaseModel):
    round_number: int
    test_command: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    fixers_spawned: int = 0
    fixers_succeeded: int = 0
    duration_seconds: float = 0.0


class ReconciliationReport(BaseModel):
    rounds: list[ReconciliationRound] = Field(default_factory=list)
    final_verdict: str = "pending"
    green_commit: str | None = None
