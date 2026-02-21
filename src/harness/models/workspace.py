from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class WorkspaceState(str, Enum):
    CREATING = "creating"
    READY = "ready"
    IN_USE = "in_use"
    MERGING = "merging"
    CLEANED = "cleaned"


class Workspace(BaseModel):
    worker_id: str
    repo_path: str
    workspace_path: str
    base_commit: str
    state: WorkspaceState = WorkspaceState.CREATING
    created_at: datetime = Field(default_factory=datetime.now)
