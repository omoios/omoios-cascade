from enum import Enum

from pydantic import BaseModel, Field


class ErrorZone(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


class ErrorBudget(BaseModel):
    total_tasks: int = 0
    failed_tasks: int = 0
    window: list[bool] = Field(default_factory=list)
    window_size: int = 20
    budget_percentage: float = 0.15
    zone: ErrorZone = ErrorZone.HEALTHY

    @property
    def failure_rate(self) -> float:
        if not self.window:
            return 0.0
        return self.window.count(False) / len(self.window)

    def record(self, success: bool) -> None:
        self.window.append(success)
        if len(self.window) > self.window_size:
            self.window.pop(0)
        self.total_tasks += 1
        if not success:
            self.failed_tasks += 1
        rate = self.failure_rate
        if rate > self.budget_percentage:
            self.zone = ErrorZone.CRITICAL
        elif rate > self.budget_percentage * 0.5:
            self.zone = ErrorZone.WARNING
        else:
            self.zone = ErrorZone.HEALTHY
