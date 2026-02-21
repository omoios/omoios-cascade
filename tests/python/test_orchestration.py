from datetime import datetime, timedelta

import pytest

from harness.agents.watchdog import Watchdog
from harness.config import WatchdogConfig
from harness.events import EventBus
from harness.models.error_budget import ErrorBudget
from harness.models.state import TaskBoardSnapshot
from harness.models.task import Task, TaskStatus
from harness.models.watchdog import ActivityEntry, FailureMode
from harness.orchestration.scheduler import Scheduler


class TestScheduler:
    def test_dispatches_pending_tasks(self):
        scheduler = Scheduler()
        task1 = Task(id="t1", title="Task 1", description="desc")
        task2 = Task(id="t2", title="Task 2", description="desc")

        scheduler.add_task(task1)
        scheduler.add_task(task2)

        ready_tasks = scheduler.get_ready_tasks()

        assert {task.id for task in ready_tasks} == {"t1", "t2"}

    def test_respects_blocked_by(self):
        scheduler = Scheduler()
        task_a = Task(id="a", title="Task A", description="desc")
        task_b = Task(id="b", title="Task B", description="desc", blocked_by=["a"])

        scheduler.add_task(task_a)
        scheduler.add_task(task_b)

        ready_tasks = scheduler.get_ready_tasks()

        assert [task.id for task in ready_tasks] == ["a"]

    def test_unblocks_when_blocker_completes(self):
        scheduler = Scheduler()
        task_a = Task(id="a", title="Task A", description="desc")
        task_b = Task(id="b", title="Task B", description="desc", blocked_by=["a"])

        scheduler.add_task(task_a)
        scheduler.add_task(task_b)
        scheduler.complete_task("a")

        ready_tasks = scheduler.get_ready_tasks()

        assert [task.id for task in ready_tasks] == ["b"]

    def test_claim_task_sets_in_progress(self):
        scheduler = Scheduler()
        task = Task(id="t1", title="Task", description="desc")
        scheduler.add_task(task)

        claimed = scheduler.claim_task("t1", "worker-1")

        assert claimed.status == TaskStatus.IN_PROGRESS
        assert claimed.assigned_to == "worker-1"
        assert claimed.claimed_at is not None

    def test_complete_task_sets_completed(self):
        scheduler = Scheduler()
        task = Task(id="t1", title="Task", description="desc")
        scheduler.add_task(task)

        completed = scheduler.complete_task("t1")

        assert completed.status == TaskStatus.COMPLETED
        assert completed.completed_at is not None

    def test_requeue_on_failure_resets_to_pending(self):
        scheduler = Scheduler()
        task = Task(id="t1", title="Task", description="desc")
        scheduler.add_task(task)
        scheduler.claim_task("t1", "worker-1")

        requeued = scheduler.requeue_on_failure("t1")

        assert requeued.status == TaskStatus.PENDING
        assert requeued.assigned_to is None

    def test_get_task_board_returns_accurate_counts(self):
        scheduler = Scheduler()
        scheduler.add_task(Task(id="p1", title="Pending", description="desc", status=TaskStatus.PENDING))
        scheduler.add_task(Task(id="ip1", title="In Progress", description="desc", status=TaskStatus.IN_PROGRESS))
        scheduler.add_task(Task(id="c1", title="Completed", description="desc", status=TaskStatus.COMPLETED))
        scheduler.add_task(Task(id="f1", title="Failed", description="desc", status=TaskStatus.FAILED))
        scheduler.add_task(Task(id="b1", title="Blocked", description="desc", status=TaskStatus.BLOCKED))

        board = scheduler.get_task_board()

        assert isinstance(board, TaskBoardSnapshot)
        assert board.pending == 1
        assert board.in_progress == 1
        assert board.completed == 1
        assert board.failed == 1
        assert board.blocked == 1

    def test_error_budget_integration(self):
        budget = ErrorBudget()
        scheduler = Scheduler(error_budget=budget)
        scheduler.add_task(Task(id="t1", title="Task 1", description="desc"))
        scheduler.add_task(Task(id="t2", title="Task 2", description="desc"))

        scheduler.complete_task("t1")
        scheduler.fail_task("t2")

        assert scheduler.error_budget.total_tasks == 2
        assert scheduler.error_budget.failed_tasks == 1
        assert scheduler.error_budget.failure_rate == pytest.approx(0.5)


class TestWatchdog:
    def test_detects_zombie_stale_heartbeat(self):
        watchdog = Watchdog(config=WatchdogConfig(zombie_timeout_seconds=60))
        watchdog.record_activity(
            ActivityEntry(
                timestamp=datetime.now() - timedelta(seconds=120),
                event_type="heartbeat",
                agent_id="worker-1",
            )
        )

        events = watchdog.check_agents()

        assert len(events) == 1
        assert events[0].failure_mode == FailureMode.ZOMBIE
        assert "No activity for" in events[0].evidence
        assert events[0].action_taken == "kill_requested"

    def test_detects_tunnel_vision_repeated_edits(self):
        watchdog = Watchdog(config=WatchdogConfig(tunnel_vision_threshold=3))
        for _ in range(4):
            watchdog.record_activity(
                ActivityEntry(
                    event_type="edit",
                    agent_id="worker-1",
                    files_touched=["src/harness/core.py"],
                )
            )

        events = watchdog.check_agents()

        assert len(events) == 1
        assert events[0].failure_mode == FailureMode.TUNNEL_VISION
        assert events[0].evidence == "File src/harness/core.py touched 4 times"

    def test_detects_token_burn_without_tools(self):
        watchdog = Watchdog(config=WatchdogConfig(token_burn_threshold=1000))
        watchdog.record_activity(
            ActivityEntry(
                event_type="llm_call",
                agent_id="worker-1",
                tokens_used=700,
            )
        )
        watchdog.record_activity(
            ActivityEntry(
                event_type="reasoning",
                agent_id="worker-1",
                tokens_used=600,
            )
        )

        events = watchdog.check_agents()

        assert len(events) == 1
        assert events[0].failure_mode == FailureMode.TOKEN_BURN
        assert events[0].evidence == "Used 1300 tokens without tool calls"

    def test_does_not_flag_healthy_worker(self):
        watchdog = Watchdog(config=WatchdogConfig())
        watchdog.record_activity(
            ActivityEntry(
                timestamp=datetime.now(),
                event_type="tool_read",
                agent_id="worker-1",
                tokens_used=500,
                files_touched=["a.py"],
            )
        )
        watchdog.record_activity(
            ActivityEntry(
                timestamp=datetime.now(),
                event_type="edit",
                agent_id="worker-1",
                tokens_used=300,
                files_touched=["b.py"],
            )
        )

        events = watchdog.check_agents()

        assert events == []

    def test_respects_configurable_thresholds(self):
        relaxed_watchdog = Watchdog(
            config=WatchdogConfig(zombie_timeout_seconds=200, tunnel_vision_threshold=4)
        )
        relaxed_watchdog.record_activity(
            ActivityEntry(
                timestamp=datetime.now() - timedelta(seconds=120),
                event_type="heartbeat",
                agent_id="worker-1",
            )
        )
        for _ in range(4):
            relaxed_watchdog.record_activity(
                ActivityEntry(
                    timestamp=datetime.now() - timedelta(seconds=120),
                    event_type="edit",
                    agent_id="worker-1",
                    files_touched=["src/harness/core.py"],
                )
            )

        strict_watchdog = Watchdog(
            config=WatchdogConfig(zombie_timeout_seconds=60, tunnel_vision_threshold=3)
        )
        strict_watchdog.record_activity(
            ActivityEntry(
                timestamp=datetime.now() - timedelta(seconds=120),
                event_type="heartbeat",
                agent_id="worker-1",
            )
        )
        for _ in range(4):
            strict_watchdog.record_activity(
                ActivityEntry(
                    timestamp=datetime.now() - timedelta(seconds=120),
                    event_type="edit",
                    agent_id="worker-1",
                    files_touched=["src/harness/core.py"],
                )
            )

        relaxed_events = relaxed_watchdog.check_agents()
        strict_events = strict_watchdog.check_agents()

        assert relaxed_events == []
        assert {event.failure_mode for event in strict_events} == {
            FailureMode.ZOMBIE,
            FailureMode.TUNNEL_VISION,
        }

    def test_emits_watchdog_alert_events(self):
        event_bus = EventBus()
        watchdog = Watchdog(
            config=WatchdogConfig(zombie_timeout_seconds=60),
            event_bus=event_bus,
        )
        watchdog.record_activity(
            ActivityEntry(
                timestamp=datetime.now() - timedelta(seconds=120),
                event_type="heartbeat",
                agent_id="worker-1",
            )
        )

        watchdog.check_agents()

        alerts = [event for event in event_bus.history if event.event_type == "watchdog_alert"]
        assert len(alerts) == 1
        assert alerts[0].agent_id == "worker-1"
        assert alerts[0].failure_mode == FailureMode.ZOMBIE.value
        assert alerts[0].details["action_taken"] == "kill_requested"
