import pytest

from harness.models.error_budget import ErrorBudget, ErrorZone
from harness.models.state import WorkerSnapshot
from harness.models.task import Task, TaskStatus
from harness.orchestration.idempotency import CompletionGate, IdempotencyGuard


class TestIdempotencyOperations:
    def test_reject_duplicate_worker_spawn(self):
        guard = IdempotencyGuard()
        task_id = "task-1"

        assert guard.can_spawn_worker(task_id) is True
        guard.mark_worker_spawned(task_id)
        assert guard.can_spawn_worker(task_id) is False

    def test_reject_duplicate_handoff_merge(self):
        guard = IdempotencyGuard()
        handoff_id = "handoff-1"

        assert guard.can_merge_handoff(handoff_id) is True
        guard.mark_handoff_merged(handoff_id)
        assert guard.can_merge_handoff(handoff_id) is False

    def test_reject_duplicate_task_creation(self):
        guard = IdempotencyGuard()
        title = "Create parser"

        assert guard.can_create_task(title) is True
        guard.mark_task_created(title)
        assert guard.can_create_task(title) is False


class TestCompletionGate:
    def test_blocks_with_running_workers(self):
        gate = CompletionGate()
        workers = [WorkerSnapshot(worker_id="w1", task_id="t1", status="running", tokens_used=0)]
        tasks = [Task(id="t1", title="Done", description="Done", status=TaskStatus.COMPLETED)]

        passed, failures = gate.declare_done(
            workers=workers,
            handoffs=[],
            tasks=tasks,
            error_budget=ErrorBudget(zone=ErrorZone.HEALTHY),
            reconciliation_passed=True,
        )

        assert passed is False
        assert "no_workers_running" in failures

    def test_blocks_with_pending_handoffs(self):
        gate = CompletionGate()
        tasks = [Task(id="t1", title="Done", description="Done", status=TaskStatus.COMPLETED)]

        passed, failures = gate.declare_done(
            workers=[],
            handoffs=["h1"],
            tasks=tasks,
            error_budget=ErrorBudget(zone=ErrorZone.HEALTHY),
            reconciliation_passed=True,
        )

        assert passed is False
        assert "pending_handoffs_empty" in failures

    def test_blocks_with_non_terminal_tasks(self):
        gate = CompletionGate()
        tasks = [Task(id="t1", title="Pending", description="Pending", status=TaskStatus.PENDING)]

        passed, failures = gate.declare_done(
            workers=[],
            handoffs=[],
            tasks=tasks,
            error_budget=ErrorBudget(zone=ErrorZone.HEALTHY),
            reconciliation_passed=True,
        )

        assert passed is False
        assert "all_tasks_terminal" in failures

    def test_blocks_with_critical_error_budget(self):
        gate = CompletionGate()
        tasks = [Task(id="t1", title="Done", description="Done", status=TaskStatus.COMPLETED)]

        passed, failures = gate.declare_done(
            workers=[],
            handoffs=[],
            tasks=tasks,
            error_budget=ErrorBudget(zone=ErrorZone.CRITICAL),
            reconciliation_passed=True,
        )

        assert passed is False
        assert "error_budget_healthy" in failures

    def test_passes_when_all_satisfied(self):
        gate = CompletionGate()
        tasks = [Task(id="t1", title="Done", description="Done", status=TaskStatus.COMPLETED)]

        passed, failures = gate.declare_done(
            workers=[],
            handoffs=[],
            tasks=tasks,
            error_budget=ErrorBudget(zone=ErrorZone.HEALTHY),
            reconciliation_passed=True,
        )

        assert passed is True
        assert failures == []

    @pytest.mark.usefixtures("tmp_path")
    def test_idempotency_file_persistence_roundtrip(self, tmp_path):
        guard = IdempotencyGuard()
        guard.mark_worker_spawned("t1")
        guard.mark_handoff_merged("h1")
        guard.mark_task_created("Create parser")

        file_path = tmp_path / "idempotency_guard.json"
        guard.save_to_file(str(file_path))

        loaded = IdempotencyGuard.load_from_file(str(file_path))

        assert loaded.can_spawn_worker("t1") is False
        assert loaded.can_merge_handoff("h1") is False
        assert loaded.can_create_task("Create parser") is False
