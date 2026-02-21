from harness.models.coherence import CompletionChecklist, IdempotencyGuard
from harness.models.error_budget import ErrorZone
from harness.models.task import TaskStatus

__all__ = ["IdempotencyGuard", "CompletionGate"]


class CompletionGate:
    def declare_done(
        self,
        workers: list,
        handoffs: list,
        tasks: list,
        error_budget,
        reconciliation_passed: bool,
    ) -> tuple[bool, list[str]]:
        terminal_statuses = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ABANDONED}
        all_tasks_terminal = all(task.status in terminal_statuses for task in tasks)
        no_workers_running = not workers or all(worker.status != "running" for worker in workers)
        error_budget_healthy = error_budget.zone != ErrorZone.CRITICAL
        pending_handoffs_empty = len(handoffs) == 0

        checklist = CompletionChecklist(
            all_tasks_terminal=all_tasks_terminal,
            no_workers_running=no_workers_running,
            error_budget_healthy=error_budget_healthy,
            reconciliation_passed=reconciliation_passed,
            pending_handoffs_empty=pending_handoffs_empty,
        )
        return checklist.is_complete()
