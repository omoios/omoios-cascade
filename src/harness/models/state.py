from pydantic import BaseModel


class WorkerSnapshot(BaseModel):
    worker_id: str
    task_id: str
    status: str
    tokens_used: int = 0


class ErrorBudgetSnapshot(BaseModel):
    zone: str
    failure_rate: float
    total: int
    failed: int


class TaskBoardSnapshot(BaseModel):
    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    blocked: int = 0


class StateSnapshot(BaseModel):
    turn_number: int
    total_tokens: int
    task_board: TaskBoardSnapshot
    workers: list[WorkerSnapshot] = []
    error_budget: ErrorBudgetSnapshot | None = None
    scratchpad_summary: str = ""
