from datetime import datetime

from harness.models.error_budget import ErrorBudget
from harness.models.state import TaskBoardSnapshot
from harness.models.task import Task, TaskStatus


class Scheduler:
    def __init__(self, error_budget: ErrorBudget | None = None):
        self._tasks: dict[str, Task] = {}
        self._error_budget = error_budget or ErrorBudget()

    def add_task(self, task: Task) -> None:
        self._tasks[task.id] = task

    def get_ready_tasks(self) -> list[Task]:
        terminal_statuses = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ABANDONED}
        ready_tasks: list[Task] = []

        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

            blockers_satisfied = True
            for blocker_id in task.blocked_by:
                blocker = self._tasks.get(blocker_id)
                if blocker is None or blocker.status not in terminal_statuses:
                    blockers_satisfied = False
                    break

            if blockers_satisfied:
                ready_tasks.append(task)

        return ready_tasks

    def claim_task(self, task_id: str, worker_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        task.status = TaskStatus.IN_PROGRESS
        task.assigned_to = worker_id
        task.claimed_at = datetime.now()
        return task

    def complete_task(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        self._error_budget.record(success=True)
        return task

    def fail_task(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        task.status = TaskStatus.FAILED
        self._error_budget.record(success=False)
        return task

    def requeue_on_failure(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        task.status = TaskStatus.PENDING
        task.assigned_to = None
        return task

    def get_task_board(self) -> TaskBoardSnapshot:
        pending = 0
        in_progress = 0
        completed = 0
        failed = 0
        blocked = 0

        for task in self._tasks.values():
            if task.status == TaskStatus.PENDING:
                pending += 1
            elif task.status == TaskStatus.IN_PROGRESS:
                in_progress += 1
            elif task.status == TaskStatus.COMPLETED:
                completed += 1
            elif task.status == TaskStatus.FAILED:
                failed += 1
            elif task.status == TaskStatus.BLOCKED:
                blocked += 1

        return TaskBoardSnapshot(
            pending=pending,
            in_progress=in_progress,
            completed=completed,
            failed=failed,
            blocked=blocked,
        )

    @property
    def error_budget(self) -> ErrorBudget:
        return self._error_budget
