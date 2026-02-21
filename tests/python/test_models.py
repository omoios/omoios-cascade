import pytest
from pydantic import ValidationError

from harness.models.agent import AgentConfig, AgentRole, AgentState
from harness.models.coherence import CompletionChecklist, ContextUpdate, IdempotencyGuard
from harness.models.error_budget import ErrorBudget, ErrorZone
from harness.models.handoff import FileDiff, Handoff, HandoffMetrics, HandoffStatus
from harness.models.merge import MergeResult, MergeStatus, ReconciliationReport
from harness.models.scratchpad import ScratchpadSchema
from harness.models.state import (
    ErrorBudgetSnapshot,
    StateSnapshot,
    TaskBoardSnapshot,
    WorkerSnapshot,
)
from harness.models.task import Task, TaskPriority, TaskStatus
from harness.models.watchdog import ActivityEntry, FailureMode, WatchdogEvent
from harness.models.workspace import Workspace, WorkspaceState


class TestTaskStatus:
    def test_enum_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.CLAIMED.value == "claimed"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.BLOCKED.value == "blocked"
        assert TaskStatus.ABANDONED.value == "abandoned"

    def test_has_seven_members(self):
        assert len(TaskStatus) == 7


class TestTaskPriority:
    def test_enum_values(self):
        assert TaskPriority.CRITICAL.value == "critical"
        assert TaskPriority.HIGH.value == "high"
        assert TaskPriority.NORMAL.value == "normal"
        assert TaskPriority.LOW.value == "low"


class TestTask:
    def test_defaults(self):
        task = Task(id="t1", title="Fix bug", description="Fix the auth bug")
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.NORMAL
        assert task.assigned_to is None
        assert task.blocked_by == []
        assert task.parent_id is None
        assert task.repo is None
        assert task.claimed_at is None
        assert task.completed_at is None
        assert task.metadata == {}

    def test_blocked_by_accepts_list(self):
        task = Task(
            id="t2",
            title="Deploy",
            description="Deploy to prod",
            blocked_by=["t1", "t0"],
        )
        assert task.blocked_by == ["t1", "t0"]

    def test_serialization_roundtrip(self):
        task = Task(
            id="t3",
            title="Test",
            description="Write tests",
            priority=TaskPriority.HIGH,
            blocked_by=["t1"],
        )
        data = task.model_dump()
        restored = Task.model_validate(data)
        assert restored.id == task.id
        assert restored.title == task.title
        assert restored.priority == task.priority
        assert restored.blocked_by == task.blocked_by

    def test_json_roundtrip(self):
        task = Task(
            id="t4",
            title="Refactor",
            description="Refactor models",
            status=TaskStatus.IN_PROGRESS,
        )
        json_str = task.model_dump_json()
        restored = Task.model_validate_json(json_str)
        assert restored.id == task.id
        assert restored.status == TaskStatus.IN_PROGRESS


class TestHandoffStatus:
    def test_enum_values(self):
        assert HandoffStatus.SUCCESS.value == "success"
        assert HandoffStatus.PARTIAL_FAILURE.value == "partial_failure"
        assert HandoffStatus.FAILED.value == "failed"
        assert HandoffStatus.BLOCKED.value == "blocked"


class TestFileDiff:
    def test_minimal(self):
        diff = FileDiff(path="src/main.py", diff_text="+hello")
        assert diff.path == "src/main.py"
        assert diff.before_hash is None
        assert diff.after_hash is None

    def test_with_hashes(self):
        diff = FileDiff(
            path="src/main.py",
            before_hash="abc123",
            after_hash="def456",
            diff_text="-old\n+new",
        )
        assert diff.before_hash == "abc123"
        assert diff.after_hash == "def456"


class TestHandoffMetrics:
    def test_defaults(self):
        metrics = HandoffMetrics(
            wall_time_seconds=1.5,
            tokens_used=100,
            attempts=1,
            files_modified=2,
        )
        assert metrics.tool_calls == 0

    def test_all_fields(self):
        metrics = HandoffMetrics(
            wall_time_seconds=5.0,
            tokens_used=5000,
            attempts=3,
            files_modified=10,
            tool_calls=42,
        )
        assert metrics.tool_calls == 42


class TestHandoff:
    def _make_metrics(self) -> HandoffMetrics:
        return HandoffMetrics(
            wall_time_seconds=1.0,
            tokens_used=100,
            attempts=1,
            files_modified=1,
        )

    def test_requires_nonempty_narrative(self):
        with pytest.raises(ValidationError, match="narrative"):
            Handoff(
                agent_id="w1",
                task_id="t1",
                status=HandoffStatus.SUCCESS,
                narrative="",
                metrics=self._make_metrics(),
            )

    def test_rejects_whitespace_only_narrative(self):
        with pytest.raises(ValidationError, match="narrative"):
            Handoff(
                agent_id="w1",
                task_id="t1",
                status=HandoffStatus.SUCCESS,
                narrative="   \n\t  ",
                metrics=self._make_metrics(),
            )

    def test_valid_handoff(self):
        handoff = Handoff(
            agent_id="w1",
            task_id="t1",
            status=HandoffStatus.SUCCESS,
            narrative="Fixed the auth bug by updating the token validation logic.",
            metrics=self._make_metrics(),
        )
        assert handoff.agent_id == "w1"
        assert handoff.diffs == []
        assert handoff.artifacts == []
        assert handoff.error_message is None

    def test_handoff_with_diffs(self):
        diff = FileDiff(path="src/auth.py", diff_text="+new line")
        handoff = Handoff(
            agent_id="w1",
            task_id="t1",
            status=HandoffStatus.PARTIAL_FAILURE,
            narrative="Partially fixed — auth works but tests need updating.",
            diffs=[diff],
            metrics=self._make_metrics(),
            error_message="2 tests still failing",
        )
        assert len(handoff.diffs) == 1
        assert handoff.error_message == "2 tests still failing"


class TestAgentRole:
    def test_enum_values(self):
        assert AgentRole.ROOT_PLANNER.value == "root_planner"
        assert AgentRole.SUB_PLANNER.value == "sub_planner"
        assert AgentRole.WORKER.value == "worker"
        assert AgentRole.WATCHDOG.value == "watchdog"


class TestAgentState:
    def test_enum_values(self):
        assert AgentState.IDLE.value == "idle"
        assert AgentState.RUNNING.value == "running"
        assert AgentState.WAITING.value == "waiting"
        assert AgentState.COMPLETED.value == "completed"
        assert AgentState.FAILED.value == "failed"
        assert AgentState.KILLED.value == "killed"


class TestAgentConfig:
    def test_defaults(self):
        config = AgentConfig(agent_id="a1", role=AgentRole.WORKER)
        assert config.depth == 0
        assert config.parent_id is None
        assert config.task_id is None
        assert config.repo is None
        assert config.system_prompt == ""
        assert config.tool_names == []
        assert config.token_budget == 100_000
        assert config.timeout_seconds == 300

    def test_full_config(self):
        config = AgentConfig(
            agent_id="a2",
            role=AgentRole.SUB_PLANNER,
            depth=2,
            parent_id="a1",
            task_id="t5",
            repo="/tmp/repo",
            system_prompt="You are a sub-planner.",
            tool_names=["bash", "read_file"],
            token_budget=50_000,
            timeout_seconds=120,
        )
        assert config.depth == 2
        assert config.parent_id == "a1"
        assert config.token_budget == 50_000


# --- Step 2: Workspace, Merge, ErrorBudget, Watchdog ---


class TestWorkspaceState:
    def test_enum_values(self):
        assert WorkspaceState.CREATING.value == "creating"
        assert WorkspaceState.READY.value == "ready"
        assert WorkspaceState.IN_USE.value == "in_use"
        assert WorkspaceState.MERGING.value == "merging"
        assert WorkspaceState.CLEANED.value == "cleaned"


class TestWorkspace:
    def test_defaults(self):
        ws = Workspace(
            worker_id="w1",
            repo_path="/repo",
            workspace_path="/tmp/ws1",
            base_commit="abc123",
        )
        assert ws.state == WorkspaceState.CREATING
        assert ws.created_at is not None


class TestMergeResult:
    def test_clean_merge(self):
        result = MergeResult(
            worker_id="w1",
            status=MergeStatus.CLEAN,
            files_merged=["src/main.py"],
        )
        assert result.fix_forward_task is None
        assert result.conflicts == []

    def test_conflict_with_fix_forward(self):
        fix_task = Task(
            id="fix-1",
            title="Fix merge conflict",
            description="Resolve conflict in main.py",
        )
        result = MergeResult(
            worker_id="w1",
            status=MergeStatus.CONFLICT,
            conflicts=["src/main.py"],
            fix_forward_task=fix_task,
        )
        assert result.fix_forward_task is not None
        assert result.fix_forward_task.id == "fix-1"

    def test_no_changes(self):
        result = MergeResult(worker_id="w1", status=MergeStatus.NO_CHANGES)
        assert result.files_merged == []


class TestReconciliationReport:
    def test_defaults(self):
        report = ReconciliationReport()
        assert report.final_verdict == "pending"
        assert report.green_commit is None
        assert report.rounds == []


class TestErrorBudget:
    def test_healthy_zone_all_successes(self):
        budget = ErrorBudget()
        for _ in range(10):
            budget.record(success=True)
        assert budget.zone == ErrorZone.HEALTHY
        assert budget.failure_rate == 0.0

    def test_critical_zone_many_failures(self):
        budget = ErrorBudget(budget_percentage=0.15)
        for _ in range(5):
            budget.record(success=False)
        assert budget.zone == ErrorZone.CRITICAL
        assert budget.failure_rate == 1.0

    def test_warning_zone(self):
        budget = ErrorBudget(budget_percentage=0.20, window_size=10)
        for _ in range(8):
            budget.record(success=True)
        for _ in range(2):
            budget.record(success=False)
        assert budget.failure_rate == pytest.approx(0.2)
        assert budget.zone == ErrorZone.WARNING

    def test_warning_zone_boundary(self):
        budget = ErrorBudget(budget_percentage=0.30, window_size=10)
        for _ in range(8):
            budget.record(success=True)
        for _ in range(2):
            budget.record(success=False)
        assert budget.failure_rate == pytest.approx(0.2)
        assert budget.zone == ErrorZone.WARNING

    def test_sliding_window_evicts_old(self):
        budget = ErrorBudget(window_size=5)
        for _ in range(5):
            budget.record(success=False)
        assert budget.zone == ErrorZone.CRITICAL
        for _ in range(5):
            budget.record(success=True)
        assert budget.failure_rate == 0.0
        assert budget.zone == ErrorZone.HEALTHY

    def test_window_size_enforcement(self):
        budget = ErrorBudget(window_size=3)
        for _ in range(10):
            budget.record(success=True)
        assert len(budget.window) == 3
        assert budget.total_tasks == 10


class TestFailureMode:
    def test_enum_values(self):
        assert FailureMode.ZOMBIE.value == "zombie"
        assert FailureMode.TUNNEL_VISION.value == "tunnel_vision"
        assert FailureMode.TOKEN_BURN.value == "token_burn"
        assert FailureMode.SCOPE_CREEP.value == "scope_creep"


class TestWatchdogEvent:
    def test_creation(self):
        event = WatchdogEvent(
            agent_id="w1",
            failure_mode=FailureMode.ZOMBIE,
            evidence="No heartbeat for 60s",
            action_taken="killed",
        )
        assert event.timestamp is not None


class TestActivityEntry:
    def test_defaults(self):
        entry = ActivityEntry(event_type="tool_call", agent_id="w1")
        assert entry.tokens_used == 0
        assert entry.files_touched == []
        assert entry.details == {}


# --- Step 3: Coherence Models ---


class TestWorkerSnapshot:
    def test_minimal(self):
        snapshot = WorkerSnapshot(worker_id="w1", task_id="t1", status="running")
        assert snapshot.worker_id == "w1"
        assert snapshot.tokens_used == 0

    def test_with_tokens(self):
        snapshot = WorkerSnapshot(worker_id="w2", task_id="t2", status="completed", tokens_used=5000)
        assert snapshot.tokens_used == 5000


class TestErrorBudgetSnapshot:
    def test_all_fields(self):
        snapshot = ErrorBudgetSnapshot(zone="healthy", failure_rate=0.1, total=10, failed=1)
        assert snapshot.zone == "healthy"
        assert snapshot.failure_rate == 0.1


class TestTaskBoardSnapshot:
    def test_defaults(self):
        board = TaskBoardSnapshot()
        assert board.pending == 0
        assert board.in_progress == 0
        assert board.completed == 0
        assert board.failed == 0
        assert board.blocked == 0

    def test_with_counts(self):
        board = TaskBoardSnapshot(pending=5, in_progress=2, completed=10, failed=1, blocked=3)
        assert board.pending == 5
        assert board.in_progress == 2
        assert board.completed == 10
        assert board.failed == 1
        assert board.blocked == 3


class TestStateSnapshot:
    def test_serialization_roundtrip(self):
        board = TaskBoardSnapshot(pending=1, in_progress=1, completed=2)
        worker = WorkerSnapshot(worker_id="w1", task_id="t1", status="running")
        error_budget = ErrorBudgetSnapshot(zone="healthy", failure_rate=0.0, total=5, failed=0)
        snapshot = StateSnapshot(
            turn_number=10,
            total_tokens=50000,
            task_board=board,
            workers=[worker],
            error_budget=error_budget,
            scratchpad_summary="Working on auth",
        )
        data = snapshot.model_dump()
        restored = StateSnapshot.model_validate(data)
        assert restored.turn_number == 10
        assert len(restored.workers) == 1
        assert restored.error_budget is not None

    def test_minimal(self):
        board = TaskBoardSnapshot()
        snapshot = StateSnapshot(turn_number=1, total_tokens=1000, task_board=board)
        assert snapshot.workers == []
        assert snapshot.error_budget is None
        assert snapshot.scratchpad_summary == ""


class TestScratchpadSchema:
    def test_required_fields(self):
        schema = ScratchpadSchema(goal="Fix auth bug", next_action="Implement token validation")
        assert schema.goal == "Fix auth bug"
        assert schema.next_action == "Implement token validation"

    def test_defaults(self):
        schema = ScratchpadSchema(goal="Test", next_action="Run tests")
        assert schema.active_workers == []
        assert schema.pending_handoffs == []
        assert schema.error_budget_summary == ""
        assert schema.blockers == []

    def test_rejects_empty_goal(self):
        with pytest.raises(ValidationError, match="Field cannot be empty"):
            ScratchpadSchema(goal="   ", next_action="do something")

    def test_rejects_empty_next_action(self):
        with pytest.raises(ValidationError, match="Field cannot be empty"):
            ScratchpadSchema(goal="some goal", next_action="  \n  ")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValidationError, match="Field cannot be empty"):
            ScratchpadSchema(goal="\t", next_action="action")

    def test_accepts_whitespace_trimmed(self):
        schema = ScratchpadSchema(goal="  goal  ", next_action="  action  ")
        assert schema.goal == "goal"
        assert schema.next_action == "action"


class TestCompletionChecklist:
    def test_all_true_returns_complete(self):
        checklist = CompletionChecklist(
            all_tasks_terminal=True,
            no_workers_running=True,
            error_budget_healthy=True,
            reconciliation_passed=True,
            pending_handoffs_empty=True,
        )
        passed, failures = checklist.is_complete()
        assert passed is True
        assert failures == []

    def test_all_false_returns_failures(self):
        checklist = CompletionChecklist(
            all_tasks_terminal=False,
            no_workers_running=False,
            error_budget_healthy=False,
            reconciliation_passed=False,
            pending_handoffs_empty=False,
        )
        passed, failures = checklist.is_complete()
        assert passed is False
        assert len(failures) == 5

    def test_partial_failure(self):
        checklist = CompletionChecklist(
            all_tasks_terminal=True,
            no_workers_running=False,
            error_budget_healthy=True,
            reconciliation_passed=False,
            pending_handoffs_empty=True,
        )
        passed, failures = checklist.is_complete()
        assert passed is False
        assert "no_workers_running" in failures
        assert "reconciliation_passed" in failures


class TestContextUpdate:
    def test_defaults(self):
        update = ContextUpdate(agent_id="w1", content="Task completed")
        assert update.priority == "info"
        assert update.timestamp is not None

    def test_with_priority(self):
        update = ContextUpdate(agent_id="w1", content="Warning message", priority="warning")
        assert update.priority == "warning"


class TestIdempotencyGuard:
    def test_can_spawn_worker_true_for_new(self):
        guard = IdempotencyGuard()
        assert guard.can_spawn_worker("t1") is True

    def test_can_spawn_worker_false_after_mark(self):
        guard = IdempotencyGuard()
        guard.mark_worker_spawned("t1")
        assert guard.can_spawn_worker("t1") is False

    def test_can_merge_handoff_true_for_new(self):
        guard = IdempotencyGuard()
        assert guard.can_merge_handoff("h1") is True

    def test_can_merge_handoff_false_after_mark(self):
        guard = IdempotencyGuard()
        guard.mark_handoff_merged("h1")
        assert guard.can_merge_handoff("h1") is False

    def test_can_create_task_true_for_new(self):
        guard = IdempotencyGuard()
        assert guard.can_create_task("Fix bug") is True

    def test_can_create_task_false_for_duplicate(self):
        guard = IdempotencyGuard()
        guard.mark_task_created("Fix bug")
        assert guard.can_create_task("Fix bug") is False
        assert guard.can_create_task("FIX BUG") is False
        assert guard.can_create_task("fix bug") is False

    def test_file_persistence_save_load(self, tmp_path):
        guard = IdempotencyGuard()
        guard.mark_worker_spawned("t1")
        guard.mark_handoff_merged("h1")
        guard.mark_task_created("Task title")

        path = tmp_path / "guard.json"
        guard.save_to_file(str(path))

        loaded = IdempotencyGuard.load_from_file(str(path))
        assert loaded.can_spawn_worker("t1") is False
        assert loaded.can_merge_handoff("h1") is False
        assert loaded.can_create_task("Task title") is False
