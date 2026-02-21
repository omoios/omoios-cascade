from pydantic import BaseModel, field_validator


class ScratchpadSchema(BaseModel):
    goal: str
    active_workers: list[str] = []
    pending_handoffs: list[str] = []
    error_budget_summary: str = ""
    blockers: list[str] = []
    next_action: str

    @field_validator("goal", "next_action")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("active_workers", "pending_handoffs", "blockers")
    @classmethod
    def not_none(cls, v) -> list:
        if v is None:
            return []
        return v
