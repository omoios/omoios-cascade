import asyncio
import inspect
from datetime import datetime
from typing import Any, Callable

from pydantic import BaseModel, Field


class HarnessEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    agent_id: str = ""
    details: dict = Field(default_factory=dict)


class WorkerSpawned(HarnessEvent):
    task_id: str = ""
    event_type: str = "worker_spawned"


class WorkerCompleted(HarnessEvent):
    task_id: str = ""
    event_type: str = "worker_completed"


class HandoffReceived(HarnessEvent):
    task_id: str = ""
    status: str = ""
    event_type: str = "handoff_received"


class MergeCompleted(HarnessEvent):
    status: str = ""
    event_type: str = "merge_completed"


class WatchdogAlert(HarnessEvent):
    failure_mode: str = ""
    event_type: str = "watchdog_alert"


class ReconciliationStarted(HarnessEvent):
    event_type: str = "reconciliation_started"


class ReconciliationCompleted(HarnessEvent):
    verdict: str = ""
    event_type: str = "reconciliation_completed"


class ErrorBudgetChanged(HarnessEvent):
    zone: str = ""
    event_type: str = "error_budget_changed"


class PlannerDecision(HarnessEvent):
    action: str = ""
    event_type: str = "planner_decision"


class SelfReflectionInjected(HarnessEvent):
    turn_count: int = 0
    event_type: str = "self_reflection_injected"


class PivotEncouraged(HarnessEvent):
    tool_name: str = ""
    failure_count: int = 0
    event_type: str = "pivot_encouraged"


class IdentityReinjected(HarnessEvent):
    event_type: str = "identity_reinjected"


class IntentValidationWarning(HarnessEvent):
    warnings: list[str] = Field(default_factory=list)
    event_type: str = "intent_validation_warning"


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable[[HarnessEvent], Any]]] = {}
        self._history: list[HarnessEvent] = []
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str, callback: Callable[[HarnessEvent], Any]) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    async def emit(self, event: HarnessEvent) -> None:
        async with self._lock:
            self._history.append(event)
            callbacks = self._subscribers.get(event.event_type, [])
        for callback in callbacks:
            if inspect.iscoroutinefunction(callback):
                await callback(event)
            else:
                callback(event)

    @property
    def history(self) -> list[HarnessEvent]:
        return list(self._history)
