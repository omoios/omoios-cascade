from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FailureMode(str, Enum):
    ZOMBIE = "zombie"
    TUNNEL_VISION = "tunnel_vision"
    TOKEN_BURN = "token_burn"
    SCOPE_CREEP = "scope_creep"


class WatchdogEvent(BaseModel):
    agent_id: str
    failure_mode: FailureMode
    evidence: str
    action_taken: str
    timestamp: datetime = Field(default_factory=datetime.now)


class ActivityEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    agent_id: str
    details: dict = Field(default_factory=dict)
    tokens_used: int = 0
    files_touched: list[str] = Field(default_factory=list)
