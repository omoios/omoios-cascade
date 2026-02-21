import threading
from datetime import datetime
from typing import Callable

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


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable[[HarnessEvent], None]]] = {}
        self._history: list[HarnessEvent] = []
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable[[HarnessEvent], None]) -> None:
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)

    def emit(self, event: HarnessEvent) -> None:
        with self._lock:
            self._history.append(event)
            callbacks = self._subscribers.get(event.event_type, [])
        for callback in callbacks:
            callback(event)

    @property
    def history(self) -> list[HarnessEvent]:
        with self._lock:
            return list(self._history)
