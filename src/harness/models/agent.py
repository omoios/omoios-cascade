from enum import Enum

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    ROOT_PLANNER = "root_planner"
    SUB_PLANNER = "sub_planner"
    WORKER = "worker"
    WATCHDOG = "watchdog"


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class AgentConfig(BaseModel):
    agent_id: str
    role: AgentRole
    depth: int = 0
    parent_id: str | None = None
    task_id: str | None = None
    repo: str | None = None
    system_prompt: str = ""
    tool_names: list[str] = Field(default_factory=list)
    token_budget: int = 100_000
    timeout_seconds: int = 300
