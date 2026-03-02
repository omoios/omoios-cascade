from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from harness.storage import HarnessDB

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


class TTSRFired(HarnessEvent):
    event_type: str = "ttsr_fired"


class ExtensionsDiscovered(HarnessEvent):
    extensions: list[str] = Field(default_factory=list)
    event_type: str = "extensions_discovered"


class IntentValidationWarning(HarnessEvent):
    warnings: list[str] = Field(default_factory=list)
    event_type: str = "intent_validation_warning"


class SkillCreated(HarnessEvent):
    skill_name: str = ""
    path: str = ""
    event_type: str = "skill_created"


class SkillValidationError(HarnessEvent):
    skill_name: str = ""
    errors: list[str] = Field(default_factory=list)
    event_type: str = "skill_validation_error"


class SkillInjected(HarnessEvent):
    skill_name: str = ""
    task_id: str = ""
    event_type: str = "skill_injected"


class CostUpdate(HarnessEvent):
    task_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    estimated_cost_usd: float = 0.0
    event_type: str = "cost_update"


class ResourceBoundExceeded(HarnessEvent):
    violations: list[str] = Field(default_factory=list)
    event_type: str = "resource_bound_exceeded"


class PoolScaleUp(HarnessEvent):
    target_count: int = 0
    event_type: str = "pool_scale_up"


class PoolScaleDown(HarnessEvent):
    target_count: int = 0
    event_type: str = "pool_scale_down"


class CircuitBreakerOpen(HarnessEvent):
    event_type: str = "circuit_breaker_open"


class CircuitBreakerClosed(HarnessEvent):
    event_type: str = "circuit_breaker_closed"


class DegradationWarning(HarnessEvent):
    memory_percent: float = 0.0
    cpu_percent: float = 0.0
    event_type: str = "degradation_warning"


class DegradationCritical(HarnessEvent):
    memory_percent: float = 0.0
    cpu_percent: float = 0.0
    event_type: str = "degradation_critical"


class EventBus:
    def __init__(self, db: HarnessDB | None = None):
        self._subscribers: dict[str, list[Callable[[HarnessEvent], Any]]] = {}
        self._history: list[HarnessEvent] = []
        self._db = db
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str, callback: Callable[[HarnessEvent], Any]) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    async def emit(self, event: HarnessEvent) -> None:
        async with self._lock:
            self._history.append(event)
            if self._db is not None:
                self._db.insert_event(
                    timestamp=event.timestamp.timestamp(),
                    event_type=event.event_type,
                    agent_id=event.agent_id,
                    payload=event.details,
                )
            callbacks = self._subscribers.get(event.event_type, [])
        for callback in callbacks:
            if inspect.iscoroutinefunction(callback):
                await callback(event)
            else:
                callback(event)

    @property
    def history(self) -> list[HarnessEvent]:
        return list(self._history)
