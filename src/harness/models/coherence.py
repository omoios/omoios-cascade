import json
from datetime import datetime

from pydantic import BaseModel, field_validator


class CompletionChecklist(BaseModel):
    all_tasks_terminal: bool = False
    no_workers_running: bool = False
    error_budget_healthy: bool = False
    reconciliation_passed: bool = False
    pending_handoffs_empty: bool = False

    def is_complete(self) -> tuple[bool, list[str]]:
        failures = []
        if not self.all_tasks_terminal:
            failures.append("all_tasks_terminal")
        if not self.no_workers_running:
            failures.append("no_workers_running")
        if not self.error_budget_healthy:
            failures.append("error_budget_healthy")
        if not self.reconciliation_passed:
            failures.append("reconciliation_passed")
        if not self.pending_handoffs_empty:
            failures.append("pending_handoffs_empty")
        return (len(failures) == 0, failures)


class ContextUpdate(BaseModel):
    agent_id: str
    content: str
    priority: str = "info"
    timestamp: datetime = field_validator("timestamp", mode="before")(lambda x: x or datetime.now())


class IdempotencyGuard:
    def __init__(self):
        self._spawned_workers: set[str] = set()
        self._merged_handoffs: set[str] = set()
        self._created_tasks: dict[str, str] = {}

    def can_spawn_worker(self, task_id: str) -> bool:
        return task_id not in self._spawned_workers

    def mark_worker_spawned(self, task_id: str) -> None:
        self._spawned_workers.add(task_id)

    def can_merge_handoff(self, handoff_id: str) -> bool:
        return handoff_id not in self._merged_handoffs

    def mark_handoff_merged(self, handoff_id: str) -> None:
        self._merged_handoffs.add(handoff_id)

    def can_create_task(self, title: str) -> bool:
        key = title.strip().lower()
        return key not in self._created_tasks

    def mark_task_created(self, title: str) -> None:
        key = title.strip().lower()
        self._created_tasks[key] = title

    @classmethod
    def load_from_file(cls, path: str) -> "IdempotencyGuard":
        with open(path, "r") as f:
            data = json.load(f)
        guard = cls()
        guard._spawned_workers = set(data.get("spawned_workers", []))
        guard._merged_handoffs = set(data.get("merged_handoffs", []))
        guard._created_tasks = data.get("created_tasks", {})
        return guard

    def save_to_file(self, path: str) -> None:
        data = {
            "spawned_workers": list(self._spawned_workers),
            "merged_handoffs": list(self._merged_handoffs),
            "created_tasks": self._created_tasks,
        }
        with open(path, "w") as f:
            json.dump(data, f)
