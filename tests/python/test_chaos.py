from datetime import datetime, timedelta

from harness.agents.watchdog import Watchdog
from harness.config import WatchdogConfig
from harness.git.workspace import snapshot_workspace
from harness.models.error_budget import ErrorBudget, ErrorZone
from harness.models.handoff import Handoff, HandoffMetrics, HandoffStatus
from harness.models.task import Task, TaskStatus
from harness.models.watchdog import ActivityEntry, FailureMode
from harness.models.workspace import Workspace
from harness.orchestration.idempotency import IdempotencyGuard
from harness.orchestration.merge import optimistic_merge
from harness.orchestration.scheduler import Scheduler


class TestChaos:
    def test_worker_crash_produces_failed_status(self):
        error_budget = ErrorBudget()
        scheduler = Scheduler(error_budget=error_budget)
        task = Task(id="t-chaos-1", title="Chaos task", description="simulate worker crash")
        scheduler.add_task(task)

        claimed = scheduler.claim_task("t-chaos-1", "worker-1")
        claimed.status = TaskStatus.FAILED
        scheduler.error_budget.record(success=False)

        assert claimed.status == TaskStatus.FAILED
        assert scheduler.error_budget.failed_tasks == 1
        assert scheduler.error_budget.total_tasks == 1

    def test_corrupt_handoff_missing_narrative(self):
        handoff = Handoff.model_construct(
            agent_id="worker-1",
            task_id="task-1",
            status=HandoffStatus.SUCCESS,
            narrative="",
            metrics=HandoffMetrics(
                wall_time_seconds=1.0,
                tokens_used=100,
                attempts=1,
                files_modified=0,
            ),
            diffs=[],
            artifacts=[],
            error_message=None,
        )

        assert handoff.narrative == ""

    async def test_two_workers_same_file_merge_conflict(self, tmp_path):
        canonical_dir = tmp_path / "canonical"
        workspace_1_dir = tmp_path / "workspace-1"
        workspace_2_dir = tmp_path / "workspace-2"

        canonical_dir.mkdir()
        workspace_1_dir.mkdir()
        workspace_2_dir.mkdir()

        file_name = "shared.txt"
        base_content = "base\n"
        (canonical_dir / file_name).write_text(base_content, encoding="utf-8")
        (workspace_1_dir / file_name).write_text("worker one change\n", encoding="utf-8")
        (workspace_2_dir / file_name).write_text("worker two change\n", encoding="utf-8")

        base_snapshot = snapshot_workspace(str(canonical_dir))

        workspace_1 = Workspace(
            worker_id="worker-1",
            repo_path=str(canonical_dir),
            workspace_path=str(workspace_1_dir),
            base_commit="no-git",
        )
        workspace_2 = Workspace(
            worker_id="worker-2",
            repo_path=str(canonical_dir),
            workspace_path=str(workspace_2_dir),
            base_commit="no-git",
        )

        first_merge = await optimistic_merge(
            workspace=workspace_1,
            canonical_path=str(canonical_dir),
            idempotency_guard=None,
            base_snapshot=base_snapshot,
        )
        second_merge = await optimistic_merge(
            workspace=workspace_2,
            canonical_path=str(canonical_dir),
            idempotency_guard=None,
            base_snapshot=base_snapshot,
        )

        assert first_merge.status.value == "clean"
        assert first_merge.files_merged == [file_name]
        assert second_merge.status.value == "conflict"
        assert second_merge.conflicts == [file_name]
        assert second_merge.fix_forward_task is not None
        assert second_merge.fix_forward_task.metadata["conflicts"] == [file_name]

    async def test_watchdog_kills_zombie_worker(self):
        watchdog = Watchdog(config=WatchdogConfig(zombie_timeout_seconds=60))
        watchdog.record_activity(
            ActivityEntry(
                timestamp=datetime.now() - timedelta(seconds=120),
                event_type="heartbeat",
                agent_id="worker-zombie",
            )
        )

        events = await watchdog.check_agents()

        assert len(events) == 1
        assert events[0].failure_mode == FailureMode.ZOMBIE

    def test_out_of_order_handoff_processing(self):
        guard = IdempotencyGuard()

        assert guard.can_merge_handoff("h2") is True
        guard.mark_handoff_merged("h2")

        assert guard.can_merge_handoff("h1") is True
        guard.mark_handoff_merged("h1")

        assert guard.can_merge_handoff("h2") is False

    def test_error_budget_recovery_after_failures(self):
        error_budget = ErrorBudget()

        for _ in range(3):
            error_budget.record(success=False)

        assert error_budget.zone == ErrorZone.CRITICAL

        for _ in range(20):
            error_budget.record(success=True)

        assert error_budget.zone == ErrorZone.HEALTHY
