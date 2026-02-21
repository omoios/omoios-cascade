from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from harness.events import (
    ErrorBudgetChanged,
    EventBus,
    HandoffReceived,
    HarnessEvent,
    MergeCompleted,
    PlannerDecision,
    ReconciliationCompleted,
    ReconciliationStarted,
    WatchdogAlert,
    WorkerCompleted,
    WorkerSpawned,
)


class RichRenderer:
    def __init__(self, event_bus: EventBus | None = None, console: Console | None = None):
        self.console = console or Console()
        self.event_bus = event_bus
        self._event_log: list[str] = []
        if self.event_bus is not None:
            self.event_bus.subscribe(WorkerSpawned().event_type, self._on_event)
            self.event_bus.subscribe(WorkerCompleted().event_type, self._on_event)
            self.event_bus.subscribe(HandoffReceived().event_type, self._on_event)
            self.event_bus.subscribe(MergeCompleted().event_type, self._on_event)
            self.event_bus.subscribe(WatchdogAlert().event_type, self._on_event)
            self.event_bus.subscribe(ReconciliationStarted().event_type, self._on_event)
            self.event_bus.subscribe(ReconciliationCompleted().event_type, self._on_event)
            self.event_bus.subscribe(ErrorBudgetChanged().event_type, self._on_event)
            self.event_bus.subscribe(PlannerDecision().event_type, self._on_event)

    def _on_event(self, event: HarnessEvent) -> None:
        if event.event_type == WorkerSpawned().event_type:
            message = f"Worker spawned: {event.agent_id}"
            self._event_log.append(message)
            self.console.print(f"[bold green]{message}[/]")
            return

        if event.event_type == WorkerCompleted().event_type:
            message = f"Worker completed: {event.agent_id}"
            self._event_log.append(message)
            self.console.print(f"[bold blue]{message}[/]")
            return

        if event.event_type == WatchdogAlert().event_type:
            failure_mode = event.failure_mode if isinstance(event, WatchdogAlert) else "unknown"
            message = f"WATCHDOG: {failure_mode} on {event.agent_id}"
            self._event_log.append(message)
            self.console.print(f"[bold red]{message}[/]")
            return

        if event.event_type == ErrorBudgetChanged().event_type:
            zone = event.zone if isinstance(event, ErrorBudgetChanged) else "unknown"
            message = f"Error budget: {zone}"
            self._event_log.append(message)
            self.console.print(f"[yellow]{message}[/]")
            return

        message = f"{event.event_type}: {event.agent_id}"
        self._event_log.append(message)
        self.console.print(message)

    def render_task_board(self, task_board: dict) -> None:
        table = Table(title="Task Board")
        table.add_column("Status")
        table.add_column("Count", justify="right")

        for status in ["pending", "in_progress", "completed", "failed", "blocked"]:
            table.add_row(status, str(task_board.get(status, 0)))

        self.console.print(Panel(table, title="Harness Tasks"))

    def render_worker_table(self, workers: list[dict]) -> None:
        table = Table(title="Workers")
        table.add_column("Worker ID")
        table.add_column("Task")
        table.add_column("Status")
        table.add_column("Tokens", justify="right")

        for worker in workers:
            worker_id = worker.get("worker_id", worker.get("agent_id", ""))
            task = worker.get("task", worker.get("task_id", ""))
            status = worker.get("status", "")
            tokens = worker.get("tokens", worker.get("token_count", 0))
            table.add_row(str(worker_id), str(task), str(status), str(tokens))

        self.console.print(Panel(table, title="Harness Workers"))

    @property
    def event_log(self) -> list[str]:
        return self._event_log
