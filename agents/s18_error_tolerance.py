#!/usr/bin/env python3
"""
s18_error_tolerance.py - Error Tolerance Policy

Concepts implemented:
- ErrorPolicy with configurable error budget (N% failure allowed).
- Failed/partial work is converted into follow-up tasks on the board.
- Error categorization: transient / permanent / unknown.
- Exception-safe orchestration: failures are captured and routed to tasks.

This session intentionally prioritizes throughput and fix-forward behavior.
"""

from __future__ import annotations

import json
import random
import subprocess
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(override=True)

WORKDIR = Path.cwd().resolve()
TASKS_DIR = WORKDIR / ".tasks"
EVENTS_DIR = WORKDIR / ".events"
POLL_INTERVAL_SECONDS = 1.0
DEFAULT_ERROR_BUDGET = 0.10
WINDOW_SIZE = 50
DEFAULT_MAX_CONCURRENCY = 6


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class HandoffStatus(str, Enum):
    SUCCESS = "Success"
    PARTIAL_FAILURE = "PartialFailure"
    FAILED = "Failed"
    BLOCKED = "Blocked"


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class ErrorZone(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Task:
    id: int
    subject: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    owner: str = ""
    retry_count: int = 0
    source_task_id: Optional[int] = None
    task_type: str = "feature"
    notes: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["status"] = self.status.value
        out["priority"] = self.priority.value
        return out

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "Task":
        return Task(
            id=int(payload["id"]),
            subject=str(payload.get("subject", "")),
            description=str(payload.get("description", "")),
            status=TaskStatus(str(payload.get("status", TaskStatus.PENDING.value))),
            priority=TaskPriority(
                str(payload.get("priority", TaskPriority.NORMAL.value))
            ),
            owner=str(payload.get("owner", "")),
            retry_count=int(payload.get("retry_count", 0)),
            source_task_id=(
                int(payload["source_task_id"])
                if payload.get("source_task_id") is not None
                else None
            ),
            task_type=str(payload.get("task_type", "feature")),
            notes=list(payload.get("notes", [])),
            created_at=float(payload.get("created_at", time.time())),
            updated_at=float(payload.get("updated_at", time.time())),
        )


@dataclass
class Handoff:
    handoff_id: str
    task_id: int
    worker_id: str
    status: HandoffStatus
    narrative: str
    artifacts: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    attempts: int = 0
    tokens_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["status"] = self.status.value
        return out


@dataclass
class ErrorEvent:
    timestamp: float
    task_id: int
    handoff_id: Optional[str]
    status: HandoffStatus
    category: ErrorCategory
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["status"] = self.status.value
        out["category"] = self.category.value
        return out


@dataclass
class ThroughputMetrics:
    started_at: float = field(default_factory=time.time)
    completed_tasks: int = 0
    total_handoffs: int = 0
    success_handoffs: int = 0
    partial_handoffs: int = 0
    failed_handoffs: int = 0

    def tasks_per_hour(self) -> float:
        elapsed = max(time.time() - self.started_at, 1.0)
        return self.completed_tasks / (elapsed / 3600.0)


class TaskBoard:
    """File-backed board under .tasks/task_<id>.json."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.next_id = self._max_id() + 1

    def _max_id(self) -> int:
        ids: List[int] = []
        for fp in self.root.glob("task_*.json"):
            try:
                ids.append(int(fp.stem.split("_")[1]))
            except Exception:
                continue
        return max(ids) if ids else 0

    def _path(self, task_id: int) -> Path:
        return self.root / f"task_{task_id}.json"

    def _save(self, task: Task) -> None:
        self._path(task.id).write_text(json.dumps(task.to_dict(), indent=2))

    def _load(self, task_id: int) -> Task:
        p = self._path(task_id)
        if not p.exists():
            raise ValueError(f"Task {task_id} not found")
        return Task.from_dict(json.loads(p.read_text()))

    def create(
        self,
        subject: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        task_type: str = "feature",
        source_task_id: Optional[int] = None,
        retry_count: int = 0,
    ) -> Task:
        with self.lock:
            task = Task(
                id=self.next_id,
                subject=subject,
                description=description,
                priority=priority,
                task_type=task_type,
                source_task_id=source_task_id,
                retry_count=retry_count,
            )
            self.next_id += 1
            self._save(task)
            return task

    def get(self, task_id: int) -> Task:
        return self._load(task_id)

    def update(self, task: Task) -> Task:
        task.updated_at = time.time()
        self._save(task)
        return task

    def set_status(self, task_id: int, status: TaskStatus) -> Task:
        with self.lock:
            task = self._load(task_id)
            task.status = status
            return self.update(task)

    def set_owner(self, task_id: int, owner: str) -> Task:
        with self.lock:
            task = self._load(task_id)
            task.owner = owner
            return self.update(task)

    def add_note(self, task_id: int, note: str) -> Task:
        with self.lock:
            task = self._load(task_id)
            task.notes.append(note)
            return self.update(task)

    def list_all(self) -> List[Task]:
        out: List[Task] = []
        for fp in sorted(self.root.glob("task_*.json")):
            try:
                out.append(Task.from_dict(json.loads(fp.read_text())))
            except Exception:
                continue
        return out

    def _priority_rank(self, p: TaskPriority) -> int:
        return {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.LOW: 3,
        }.get(p, 99)

    def claim_next(self, owner: str) -> Optional[Task]:
        with self.lock:
            pending = [
                t
                for t in self.list_all()
                if t.status == TaskStatus.PENDING and not t.owner
            ]
            if not pending:
                return None
            pending.sort(key=lambda t: (self._priority_rank(t.priority), t.created_at))
            task = pending[0]
            task.status = TaskStatus.IN_PROGRESS
            task.owner = owner
            self.update(task)
            return task

    def render(self) -> str:
        tasks = self.list_all()
        if not tasks:
            return "No tasks"
        marks = {
            TaskStatus.PENDING: "[ ]",
            TaskStatus.IN_PROGRESS: "[>]",
            TaskStatus.COMPLETED: "[x]",
            TaskStatus.FAILED: "[!]",
        }
        lines: List[str] = []
        for t in tasks:
            owner = f" @{t.owner}" if t.owner else ""
            lines.append(
                f"{marks.get(t.status, '[?]')} #{t.id} ({t.priority.value}): {t.subject}{owner}"
            )
        return "\n".join(lines)


class ErrorPolicy:
    """Sliding-window policy with explicit error budget."""

    def __init__(
        self, error_budget: float = DEFAULT_ERROR_BUDGET, window_size: int = WINDOW_SIZE
    ):
        self.error_budget = max(0.0, min(error_budget, 1.0))
        self.window_size = max(5, window_size)
        self.events: Deque[ErrorEvent] = deque(maxlen=self.window_size)

    def record(self, event: ErrorEvent) -> None:
        self.events.append(event)

    def total_handoffs(self) -> int:
        return len(self.events)

    def error_count(self) -> int:
        return len([e for e in self.events if e.status != HandoffStatus.SUCCESS])

    def error_rate(self) -> float:
        total = self.total_handoffs()
        if total == 0:
            return 0.0
        return self.error_count() / float(total)

    def zone(self) -> ErrorZone:
        rate = self.error_rate()
        if rate < self.error_budget:
            return ErrorZone.HEALTHY
        if rate <= 0.25:
            return ErrorZone.WARNING
        return ErrorZone.CRITICAL

    def recommended_concurrency(self, base: int) -> int:
        z = self.zone()
        if z == ErrorZone.HEALTHY:
            return max(base, 1)
        if z == ErrorZone.WARNING:
            return max(1, base // 2)
        return 0

    def category_counts(self) -> Dict[str, int]:
        out = {
            ErrorCategory.TRANSIENT.value: 0,
            ErrorCategory.PERMANENT.value: 0,
            ErrorCategory.UNKNOWN.value: 0,
        }
        for e in self.events:
            if e.status == HandoffStatus.SUCCESS:
                continue
            out[e.category.value] = out.get(e.category.value, 0) + 1
        return out

    def snapshot(self) -> Dict[str, Any]:
        return {
            "error_budget": self.error_budget,
            "window_size": self.window_size,
            "total_handoffs": self.total_handoffs(),
            "error_count": self.error_count(),
            "error_rate": round(self.error_rate(), 4),
            "zone": self.zone().value,
            "categories": self.category_counts(),
            "latest": [e.to_dict() for e in list(self.events)[-10:]],
        }


class EventLog:
    """Append-only jsonl event stream under .events."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "s18_error_tolerance.jsonl"
        self.lock = threading.Lock()

    def write(self, event_type: str, payload: Dict[str, Any]) -> None:
        row = {"timestamp": time.time(), "type": event_type, "payload": payload}
        with self.lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(row) + "\n")

    def read_last(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().splitlines()
        out: List[Dict[str, Any]] = []
        for line in lines[-max(1, limit) :]:
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


class ErrorTolerantEngine:
    """
    Simple orchestrator:
    - Schedules tasks from board with policy-based concurrency.
    - Runs worker jobs inside protected exception boundaries.
    - Turns errors into tasks via requeue/follow-up/fixer generation.
    """

    def __init__(
        self,
        task_board: TaskBoard,
        policy: ErrorPolicy,
        event_log: EventLog,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ):
        self.board = task_board
        self.policy = policy
        self.log = event_log
        self.max_concurrency = max(1, max_concurrency)

        self.metrics = ThroughputMetrics()
        self.active: Dict[str, threading.Thread] = {}
        self.thread_lock = threading.Lock()

        self.handoffs: List[Handoff] = []
        self.errors: List[ErrorEvent] = []

    # -----------------------------
    # Error handling + categorizer
    # -----------------------------
    def categorize_error(self, text: str) -> ErrorCategory:
        low = text.lower()
        transient = [
            "timeout",
            "timed out",
            "temporarily",
            "rate limit",
            "network",
            "connection",
            "429",
            "503",
        ]
        permanent = [
            "syntax",
            "permission denied",
            "module not found",
            "invalid",
            "typeerror",
            "valueerror",
            "assertion",
        ]
        if any(k in low for k in transient):
            return ErrorCategory.TRANSIENT
        if any(k in low for k in permanent):
            return ErrorCategory.PERMANENT
        return ErrorCategory.UNKNOWN

    def _record_policy_event(
        self,
        task_id: int,
        handoff_id: Optional[str],
        status: HandoffStatus,
        detail: str,
    ) -> ErrorCategory:
        category = self.categorize_error(detail)
        event = ErrorEvent(
            timestamp=time.time(),
            task_id=task_id,
            handoff_id=handoff_id,
            status=status,
            category=category,
            detail=detail[:1400],
        )
        self.policy.record(event)
        if status != HandoffStatus.SUCCESS:
            self.errors.append(event)
        self.log.write("policy_event", event.to_dict())
        return category

    # -----------------------------
    # Task conversions (errors => tasks)
    # -----------------------------
    def _create_retry_task(
        self, source_task: Task, category: ErrorCategory, handoff: Handoff
    ) -> Task:
        retry = source_task.retry_count + 1
        priority = (
            TaskPriority.HIGH
            if category != ErrorCategory.PERMANENT
            else TaskPriority.NORMAL
        )
        task = self.board.create(
            subject=f"Retry #{source_task.id}: {source_task.subject}",
            description=(
                f"Original task {source_task.id} failed.\n"
                f"Category: {category.value}\n"
                f"Handoff status: {handoff.status.value}\n"
                f"Narrative:\n{handoff.narrative}\n"
                "Apply a different strategy and report deltas."
            ),
            priority=priority,
            task_type="retry",
            source_task_id=source_task.id,
            retry_count=retry,
        )
        self.board.add_note(task.id, "auto-generated retry from failed handoff")
        self.log.write("task_created", {"kind": "retry", "task": task.to_dict()})
        return task

    def _create_partial_followup(self, source_task: Task, handoff: Handoff) -> Task:
        task = self.board.create(
            subject=f"Follow-up for task {source_task.id}: unresolved scope",
            description=(
                f"Task {source_task.id} returned PartialFailure.\n"
                "Complete unresolved remainder only.\n"
                f"Narrative:\n{handoff.narrative}"
            ),
            priority=TaskPriority.NORMAL,
            task_type="followup",
            source_task_id=source_task.id,
            retry_count=source_task.retry_count,
        )
        self.board.add_note(task.id, "auto-generated follow-up from partial handoff")
        self.log.write("task_created", {"kind": "followup", "task": task.to_dict()})
        return task

    def _create_build_fixer(self, source_task: Task, detail: str) -> Task:
        task = self.board.create(
            subject=f"Fix build break from task {source_task.id}",
            description=(
                f"Build/compile check failed after task {source_task.id}.\n"
                f"Details:\n{detail[:4000]}\n"
                "Apply fix-forward and preserve existing progress."
            ),
            priority=TaskPriority.CRITICAL,
            task_type="build_fixer",
            source_task_id=source_task.id,
            retry_count=source_task.retry_count,
        )
        self.board.add_note(task.id, "auto-generated critical fixer")
        self.log.write("task_created", {"kind": "build_fixer", "task": task.to_dict()})
        return task

    # -----------------------------
    # Worker run model
    # -----------------------------
    def _simulate_worker_job(self, task: Task, worker_id: str) -> Handoff:
        """
        Session-friendly deterministic simulation:
        - 70% success
        - 20% partial failure
        - 10% failed/blocked
        plus a tiny compile check simulation for Python tasks.
        """
        started = time.time()
        attempts = random.randint(1, 4)
        tokens = random.randint(200, 1800)

        roll = random.random()
        if (
            "missing path" in task.description.lower()
            or "intentional failing" in task.subject.lower()
        ):
            roll = 0.98

        status = HandoffStatus.SUCCESS
        narrative = "Completed assigned scope."
        artifacts: List[str] = []

        if roll < 0.70:
            status = HandoffStatus.SUCCESS
            narrative = "Task completed successfully with expected output."
            artifacts = [f"artifact://task-{task.id}/result.txt"]
        elif roll < 0.90:
            status = HandoffStatus.PARTIAL_FAILURE
            narrative = "Completed core path, edge cases still unresolved."
            artifacts = [f"artifact://task-{task.id}/partial.txt"]
        else:
            status = (
                HandoffStatus.FAILED if random.random() > 0.4 else HandoffStatus.BLOCKED
            )
            if (
                "network" in task.description.lower()
                or "api" in task.description.lower()
            ):
                narrative = "Request timed out during external call; retry recommended."
            else:
                narrative = "Encountered invalid state and could not complete scope."

        if status == HandoffStatus.SUCCESS and ".py" in task.description:
            check_proc = subprocess.run(
                ["python3", "-c", "print('compile-check-ok')"],
                capture_output=True,
                text=True,
            )
            if check_proc.returncode != 0:
                status = HandoffStatus.PARTIAL_FAILURE
                narrative = (
                    f"Core task done, compile check noisy: {check_proc.stderr.strip()}"
                )

        return Handoff(
            handoff_id=f"h-{uuid.uuid4().hex[:10]}",
            task_id=task.id,
            worker_id=worker_id,
            status=status,
            narrative=narrative,
            artifacts=artifacts,
            duration_seconds=max(time.time() - started, 0.01),
            attempts=attempts,
            tokens_used=tokens,
        )

    def _handle_handoff(self, task: Task, handoff: Handoff) -> None:
        self.handoffs.append(handoff)
        self.metrics.total_handoffs += 1

        category = self._record_policy_event(
            task.id, handoff.handoff_id, handoff.status, handoff.narrative
        )

        if handoff.status == HandoffStatus.SUCCESS:
            self.metrics.success_handoffs += 1
            self.board.set_status(task.id, TaskStatus.COMPLETED)
            self.metrics.completed_tasks += 1
            self.log.write(
                "handoff", {"outcome": "success", "handoff": handoff.to_dict()}
            )
            return

        if handoff.status == HandoffStatus.PARTIAL_FAILURE:
            self.metrics.partial_handoffs += 1
            self.board.set_status(task.id, TaskStatus.COMPLETED)
            self.metrics.completed_tasks += 1
            self._create_partial_followup(task, handoff)
            self.log.write(
                "handoff",
                {
                    "outcome": "partial_failure",
                    "handoff": handoff.to_dict(),
                    "category": category.value,
                },
            )
            return

        self.metrics.failed_handoffs += 1
        self.board.set_status(task.id, TaskStatus.FAILED)
        retry = self._create_retry_task(task, category, handoff)
        if category == ErrorCategory.PERMANENT:
            self._create_build_fixer(task, handoff.narrative)
        self.log.write(
            "handoff",
            {
                "outcome": "failed",
                "handoff": handoff.to_dict(),
                "category": category.value,
                "retry_task": retry.to_dict(),
            },
        )

    def _worker_wrapper(self, worker_id: str, task: Task) -> None:
        try:
            handoff = self._simulate_worker_job(task, worker_id)
            self._handle_handoff(task, handoff)
        except Exception:
            detail = traceback.format_exc(limit=8)
            cat = self._record_policy_event(task.id, None, HandoffStatus.FAILED, detail)
            self.board.set_status(task.id, TaskStatus.FAILED)
            self._create_retry_task(
                task,
                cat,
                Handoff(
                    handoff_id=f"h-{uuid.uuid4().hex[:10]}",
                    task_id=task.id,
                    worker_id=worker_id,
                    status=HandoffStatus.FAILED,
                    narrative=detail,
                ),
            )
            self.log.write(
                "worker_exception",
                {"worker_id": worker_id, "task_id": task.id, "detail": detail[:3000]},
            )
        finally:
            with self.thread_lock:
                self.active.pop(worker_id, None)

    # -----------------------------
    # Scheduler loop
    # -----------------------------
    def scheduler_tick(self) -> None:
        zone = self.policy.zone()
        allowed = self.policy.recommended_concurrency(self.max_concurrency)

        if zone == ErrorZone.CRITICAL:
            self.log.write(
                "scheduler",
                {
                    "zone": zone.value,
                    "message": "critical zone active; no new workers this tick",
                    "active_workers": len(self.active),
                    "error_rate": self.policy.error_rate(),
                },
            )
            return

        while True:
            with self.thread_lock:
                if len(self.active) >= allowed:
                    break

            task = self.board.claim_next(owner="")
            if not task:
                break

            worker_id = f"worker-{uuid.uuid4().hex[:6]}"
            self.board.set_owner(task.id, worker_id)

            thread = threading.Thread(
                target=self._worker_wrapper, args=(worker_id, task), daemon=True
            )
            with self.thread_lock:
                self.active[worker_id] = thread
            thread.start()

            self.log.write(
                "scheduler",
                {
                    "zone": zone.value,
                    "worker_id": worker_id,
                    "task_id": task.id,
                    "allowed_concurrency": allowed,
                    "active_workers": len(self.active),
                    "error_rate": self.policy.error_rate(),
                },
            )

    def run_for(self, seconds: int) -> None:
        deadline = time.time() + max(seconds, 0)
        while time.time() < deadline:
            self.scheduler_tick()
            time.sleep(POLL_INTERVAL_SECONDS)

    # -----------------------------
    # Reporting
    # -----------------------------
    def policy_status(self) -> str:
        payload = {
            "error_policy": self.policy.snapshot(),
            "active_workers": len(self.active),
            "recommended_concurrency": self.policy.recommended_concurrency(
                self.max_concurrency
            ),
            "throughput": {
                "completed_tasks": self.metrics.completed_tasks,
                "total_handoffs": self.metrics.total_handoffs,
                "success_handoffs": self.metrics.success_handoffs,
                "partial_handoffs": self.metrics.partial_handoffs,
                "failed_handoffs": self.metrics.failed_handoffs,
                "tasks_per_hour": round(self.metrics.tasks_per_hour(), 2),
            },
        }
        return json.dumps(payload, indent=2)

    def recent_errors(self, limit: int = 20) -> str:
        rows = [e.to_dict() for e in self.errors[-max(limit, 1) :]]
        return json.dumps(rows, indent=2)

    def recent_handoffs(self, limit: int = 20) -> str:
        rows = [h.to_dict() for h in self.handoffs[-max(limit, 1) :]]
        return json.dumps(rows, indent=2)


BOARD = TaskBoard(TASKS_DIR)
POLICY = ErrorPolicy(error_budget=DEFAULT_ERROR_BUDGET, window_size=WINDOW_SIZE)
EVENTS = EventLog(EVENTS_DIR)
ENGINE = ErrorTolerantEngine(
    BOARD, POLICY, EVENTS, max_concurrency=DEFAULT_MAX_CONCURRENCY
)


def seed_demo_tasks() -> None:
    if BOARD.list_all():
        return
    BOARD.create(
        subject="Create demo helper",
        description="Create tmp/demo_helper.py with function demo_value() -> 42.",
        priority=TaskPriority.NORMAL,
        task_type="demo",
    )
    BOARD.create(
        subject="Call external API",
        description="Fetch API data and normalize response; network may timeout.",
        priority=TaskPriority.HIGH,
        task_type="demo",
    )
    BOARD.create(
        subject="Intentional failing task",
        description="Read missing path and produce retry flow.",
        priority=TaskPriority.HIGH,
        task_type="demo_failure",
    )


def print_help() -> None:
    print(
        "Commands: /tasks /policy /errors [n] /handoffs [n] /events [n] "
        "/run <sec> /seed /add <subject> /q"
    )


def cmd_add(subject: str) -> None:
    subject = subject.strip()
    if not subject:
        print("Error: missing subject")
        return
    task = BOARD.create(
        subject=subject,
        description="Ad-hoc task created from CLI",
        priority=TaskPriority.NORMAL,
        task_type="manual",
    )
    print(f"Created task #{task.id}")


if __name__ == "__main__":
    seed_demo_tasks()
    print("s18 error tolerance")
    print_help()

    while True:
        try:
            raw = input("\033[36ms18 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        q = raw.strip()
        if q.lower() in ("q", "exit", "/q", ""):
            break

        if q == "/help":
            print_help()
            continue
        if q == "/tasks":
            print(BOARD.render())
            continue
        if q == "/policy":
            print(ENGINE.policy_status())
            continue
        if q.startswith("/errors"):
            parts = q.split(" ", 1)
            lim = 20
            if len(parts) == 2 and parts[1].strip().isdigit():
                lim = int(parts[1].strip())
            print(ENGINE.recent_errors(limit=lim))
            continue
        if q.startswith("/handoffs"):
            parts = q.split(" ", 1)
            lim = 20
            if len(parts) == 2 and parts[1].strip().isdigit():
                lim = int(parts[1].strip())
            print(ENGINE.recent_handoffs(limit=lim))
            continue
        if q.startswith("/events"):
            parts = q.split(" ", 1)
            lim = 20
            if len(parts) == 2 and parts[1].strip().isdigit():
                lim = int(parts[1].strip())
            print(json.dumps(EVENTS.read_last(limit=lim), indent=2))
            continue
        if q == "/seed":
            seed_demo_tasks()
            print("Seed tasks ensured")
            continue
        if q.startswith("/add "):
            cmd_add(q.split(" ", 1)[1])
            continue
        if q.startswith("/run "):
            parts = q.split(" ", 1)
            if len(parts) != 2 or not parts[1].strip().isdigit():
                print("Usage: /run <seconds>")
                continue
            sec = int(parts[1].strip())
            ENGINE.run_for(sec)
            print("Run complete")
            continue

        print("Unknown command. Use /help")
