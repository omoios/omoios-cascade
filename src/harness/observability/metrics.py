import json
import time
from pathlib import Path
from typing import Any

from harness.events import (
    CostUpdate,
    EventBus,
    HarnessEvent,
    MergeCompleted,
    PlannerDecision,
    ResourceBoundExceeded,
    WorkerCompleted,
    WorkerSpawned,
)


class MetricsCollector:
    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus
        self._started_at = time.monotonic()
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.tasks_pending = 0
        self.workers_active = 0
        self.workers_idle = 0
        self.workers_terminated = 0
        self.tokens_total = 0
        self._errors_total = 0
        self._merges_total = 0
        self._merges_success = 0
        self._task_durations: list[float] = []
        self.cost_total = 0.0

        if self.event_bus:
            self.event_bus.subscribe(WorkerSpawned().event_type, self._on_event)
            self.event_bus.subscribe(WorkerCompleted().event_type, self._on_event)
            self.event_bus.subscribe(CostUpdate().event_type, self._on_event)
            self.event_bus.subscribe(ResourceBoundExceeded().event_type, self._on_event)
            self.event_bus.subscribe(MergeCompleted().event_type, self._on_event)
            self.event_bus.subscribe(PlannerDecision().event_type, self._on_event)

    def _on_event(self, event: HarnessEvent) -> None:
        if event.event_type == WorkerSpawned().event_type:
            self.workers_active += 1
            self.workers_idle = max(0, self.workers_idle - 1)
            return

        if event.event_type == WorkerCompleted().event_type:
            self.workers_active = max(0, self.workers_active - 1)
            self.workers_idle += 1
            status = str(event.details.get("status", "completed"))
            if status in {"failed", "error"}:
                self.tasks_failed += 1
            else:
                self.tasks_completed += 1
            duration = event.details.get("duration_seconds")
            if isinstance(duration, (int, float)):
                self._task_durations.append(float(duration))
            if status == "terminated":
                self.workers_terminated += 1
            return

        if event.event_type == CostUpdate().event_type and isinstance(event, CostUpdate):
            self.tokens_total += (
                event.input_tokens + event.output_tokens + event.cache_read_tokens + event.cache_write_tokens
            )
            self.cost_total += event.estimated_cost_usd
            return

        if event.event_type == ResourceBoundExceeded().event_type:
            self._errors_total += 1
            return

        if event.event_type == MergeCompleted().event_type:
            self._merges_total += 1
            merge_status = getattr(event, "status", "")
            if str(merge_status).lower() in {"success", "merged", "ok"}:
                self._merges_success += 1
            return

        if event.event_type == PlannerDecision().event_type:
            pending = event.details.get("tasks_pending")
            idle = event.details.get("workers_idle")
            if isinstance(pending, int):
                self.tasks_pending = pending
            if isinstance(idle, int):
                self.workers_idle = idle

    def snapshot(self) -> dict[str, Any]:
        elapsed_minutes = max((time.monotonic() - self._started_at) / 60.0, 1e-9)
        total_tasks = self.tasks_completed + self.tasks_failed
        error_rate = (self.tasks_failed / total_tasks) if total_tasks else 0.0
        merge_success_rate = (self._merges_success / self._merges_total) if self._merges_total else 0.0
        average_task_duration = sum(self._task_durations) / len(self._task_durations) if self._task_durations else 0.0

        return {
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "tasks_pending": self.tasks_pending,
            "workers_active": self.workers_active,
            "workers_idle": self.workers_idle,
            "workers_terminated": self.workers_terminated,
            "tokens_total": self.tokens_total,
            "tokens_per_minute": self.tokens_total / elapsed_minutes,
            "error_rate": error_rate,
            "merge_success_rate": merge_success_rate,
            "average_task_duration": average_task_duration,
            "cost_total": self.cost_total,
        }

    def to_jsonl(self, path: str) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = self.snapshot()
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True))
            handle.write("\n")
