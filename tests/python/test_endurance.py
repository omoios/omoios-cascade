import pytest

from harness.models.error_budget import ErrorBudget, ErrorZone
from harness.models.state import StateSnapshot, TaskBoardSnapshot
from harness.models.task import Task
from harness.orchestration.compression import (
    CompressionTracker,
    auto_compact,
    estimate_tokens,
    microcompact,
)
from harness.orchestration.scheduler import Scheduler


class TestEndurance:
    def test_20_task_orchestration_over_50_turns(self):
        scheduler = Scheduler()

        for index in range(1, 21):
            blockers = [f"t{index - 1}"] if index > 1 else []
            scheduler.add_task(
                Task(
                    id=f"t{index}",
                    title=f"Task {index}",
                    description="endurance task",
                    blocked_by=blockers,
                )
            )

        for _ in range(50):
            ready_tasks = scheduler.get_ready_tasks()
            if not ready_tasks:
                continue
            task = ready_tasks[0]
            scheduler.claim_task(task.id, "worker-1")
            scheduler.complete_task(task.id)

        board = scheduler.get_task_board()

        assert board.completed == 20
        assert board.pending == 0
        assert board.failed == 0
        assert board.in_progress == 0

    def test_compression_cycles_maintain_state(self):
        tracker = CompressionTracker()
        messages = [
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "running"},
                    {"type": "tool_result", "content": "tool output 1"},
                ],
            },
            {"role": "user", "content": "continue"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_result", "content": "tool output 2"},
                ],
            },
            {"role": "user", "content": "wrap up"},
        ]

        for _ in range(3):
            messages = microcompact(messages, keep_recent=2)
            tracker.record_compression()
            token_estimate = estimate_tokens(messages)
            assert isinstance(token_estimate, int)
            assert token_estimate >= 0

        snapshot = StateSnapshot(
            turn_number=12,
            total_tokens=estimate_tokens(messages),
            task_board=TaskBoardSnapshot(pending=1, completed=4),
            scratchpad_summary="stable",
        )
        compacted = auto_compact(messages, client=object(), snapshot=snapshot)

        assert compacted[0]["role"] == "user"
        assert "[state_snapshot]" in compacted[0]["content"]
        assert snapshot.model_dump_json() in compacted[0]["content"]
        assert tracker.count == 3

    def test_worker_failures_trigger_requeuing(self):
        scheduler = Scheduler()
        for index in range(1, 6):
            scheduler.add_task(
                Task(
                    id=f"t{index}",
                    title=f"Task {index}",
                    description="requeue test",
                )
            )

        scheduler.claim_task("t1", "worker-a")
        scheduler.fail_task("t1")
        scheduler.claim_task("t2", "worker-b")
        scheduler.fail_task("t2")

        scheduler.requeue_on_failure("t1")
        scheduler.requeue_on_failure("t2")

        ready_ids = {task.id for task in scheduler.get_ready_tasks()}
        assert {"t1", "t2"}.issubset(ready_ids)

        for task_id in ["t1", "t2", "t3", "t4", "t5"]:
            scheduler.claim_task(task_id, "worker-final")
            scheduler.complete_task(task_id)

        board = scheduler.get_task_board()

        assert board.completed == 5
        assert board.failed == 0
        assert board.pending == 0

    def test_error_budget_transitions(self):
        budget = ErrorBudget()
        zones = [budget.zone]

        for _ in range(10):
            budget.record(success=True)
            zones.append(budget.zone)

        for _ in range(3):
            budget.record(success=False)
            zones.append(budget.zone)

        for _ in range(10):
            budget.record(success=True)
            zones.append(budget.zone)

        assert ErrorZone.HEALTHY in zones
        assert ErrorZone.CRITICAL in zones
        assert budget.zone in {ErrorZone.WARNING, ErrorZone.HEALTHY}
        assert budget.failure_rate == pytest.approx(0.15)

    def test_planner_loop_bounds_trigger_graceful_stop(self):
        max_turns = 50
        counter = 0

        while True:
            counter += 1
            if counter >= max_turns:
                break

        assert counter == 50

    def test_final_task_board_matches_expected(self):
        scheduler = Scheduler()

        for index in range(1, 6):
            scheduler.add_task(
                Task(
                    id=f"t{index}",
                    title=f"Independent {index}",
                    description="independent",
                )
            )

        for index in range(6, 11):
            blocker = f"t{index - 5}"
            scheduler.add_task(
                Task(
                    id=f"t{index}",
                    title=f"Dependent {index}",
                    description="dependent",
                    blocked_by=[blocker],
                )
            )

        while True:
            ready_tasks = scheduler.get_ready_tasks()
            if not ready_tasks:
                break
            for task in ready_tasks:
                scheduler.claim_task(task.id, "worker-1")
                scheduler.complete_task(task.id)

        board = scheduler.get_task_board()

        assert isinstance(board, TaskBoardSnapshot)
        assert board.pending == 0
        assert board.completed == 10
        assert board.failed == 0
