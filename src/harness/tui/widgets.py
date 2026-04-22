"""Custom Textual widgets for the Harness TUI."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from textual.reactive import reactive
from textual.widgets import DataTable, RichLog, Static


class TaskBoardWidget(Static):
    """Widget displaying task counts by status."""

    pending: reactive[int] = reactive(0)
    in_progress: reactive[int] = reactive(0)
    completed: reactive[int] = reactive(0)
    failed: reactive[int] = reactive(0)
    blocked: reactive[int] = reactive(0)

    def compose(self) -> Any:
        """Compose the widget layout."""
        yield Static(id="task-board-content")

    def watch_pending(self, value: int) -> None:
        """React to pending count changes."""
        self._update_display()

    def watch_in_progress(self, value: int) -> None:
        """React to in_progress count changes."""
        self._update_display()

    def watch_completed(self, value: int) -> None:
        """React to completed count changes."""
        self._update_display()

    def watch_failed(self, value: int) -> None:
        """React to failed count changes."""
        self._update_display()

    def watch_blocked(self, value: int) -> None:
        """React to blocked count changes."""
        self._update_display()

    def on_mount(self) -> None:
        """Initialize the display on mount."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the visual display of task counts."""
        content = self.query_one("#task-board-content", Static)
        lines = [
            "Task Board",
            "",
            f"  [green]●[/green] Completed: {self.completed}",
            f"  [yellow]●[/yellow] In Progress: {self.in_progress}",
            f"  [blue]●[/blue] Pending: {self.pending}",
            f"  [red]●[/red] Failed: {self.failed}",
            f"  [dim]●[/dim] Blocked: {self.blocked}",
        ]
        content.update("\n".join(lines))

    def update_counts(
        self,
        pending: int,
        in_progress: int,
        completed: int,
        failed: int,
        blocked: int,
    ) -> None:
        """Update all task counts at once."""
        self.pending = pending
        self.in_progress = in_progress
        self.completed = completed
        self.failed = failed
        self.blocked = blocked


class WorkerTableWidget(DataTable):
    """DataTable widget for displaying worker information."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the worker table."""
        super().__init__(**kwargs)
        self._worker_rows: dict[str, int] = {}

    def on_mount(self) -> None:
        """Set up columns on mount."""
        self.add_columns("Worker ID", "Task", "Status", "Tokens")
        self.zebra_stripes = True
        self.cursor_type = "row"

    def add_worker(self, worker_id: str, task_id: str, status: str) -> None:
        """Add a new worker to the table."""
        if worker_id in self._worker_rows:
            return
        row_key = self.add_row(worker_id, task_id, status, "0", key=worker_id)
        self._worker_rows[worker_id] = row_key

    def update_worker(self, worker_id: str, status: str | None = None, tokens: int | None = None) -> None:
        """Update worker status and/or token count."""
        if worker_id not in self._worker_rows:
            return
        row_key = self._worker_rows[worker_id]
        row = self.get_row(row_key)
        if row is None:
            return
        current_worker, current_task, current_status, current_tokens = row
        new_status = status if status is not None else current_status
        new_tokens = str(tokens) if tokens is not None else current_tokens
        self.update_cell(row_key, "Status", new_status)
        self.update_cell(row_key, "Tokens", new_tokens)

    def remove_worker(self, worker_id: str) -> None:
        """Remove a worker from the table."""
        if worker_id not in self._worker_rows:
            return
        row_key = self._worker_rows[worker_id]
        self.remove_row(row_key)
        del self._worker_rows[worker_id]

    def clear_workers(self) -> None:
        """Clear all workers from the table."""
        self.clear()
        self._worker_rows.clear()


class CostWidget(Static):
    """Widget displaying cost and token information."""

    total_cost_usd: reactive[float] = reactive(0.0)
    input_tokens: reactive[int] = reactive(0)
    output_tokens: reactive[int] = reactive(0)
    cache_read_tokens: reactive[int] = reactive(0)
    cache_write_tokens: reactive[int] = reactive(0)

    def compose(self) -> Any:
        """Compose the widget layout."""
        yield Static(id="cost-content")

    def watch_total_cost_usd(self, value: float) -> None:
        """React to cost changes."""
        self._update_display()

    def watch_input_tokens(self, value: int) -> None:
        """React to input token changes."""
        self._update_display()

    def watch_output_tokens(self, value: int) -> None:
        """React to output token changes."""
        self._update_display()

    def watch_cache_read_tokens(self, value: int) -> None:
        """React to cache read token changes."""
        self._update_display()

    def watch_cache_write_tokens(self, value: int) -> None:
        """React to cache write token changes."""
        self._update_display()

    def on_mount(self) -> None:
        """Initialize the display on mount."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the visual display of cost information."""
        content = self.query_one("#cost-content", Static)
        total_tokens = self.input_tokens + self.output_tokens
        lines = [
            "Cost & Tokens",
            "",
            f"  Total Cost: [green]${self.total_cost_usd:.4f}[/green]",
            f"  Total Tokens: {total_tokens:,}",
            f"    Input: {self.input_tokens:,}",
            f"    Output: {self.output_tokens:,}",
            f"    Cache Read: {self.cache_read_tokens:,}",
            f"    Cache Write: {self.cache_write_tokens:,}",
        ]
        content.update("\n".join(lines))

    def update_cost(self, cost_update: dict[str, Any]) -> None:
        """Update cost metrics from a CostUpdate event."""
        self.input_tokens += cost_update.get("input_tokens", 0)
        self.output_tokens += cost_update.get("output_tokens", 0)
        self.cache_read_tokens += cost_update.get("cache_read_tokens", 0)
        self.cache_write_tokens += cost_update.get("cache_write_tokens", 0)
        self.total_cost_usd += cost_update.get("estimated_cost_usd", 0.0)


class EventLogWidget(RichLog):
    """Scrolling event log widget."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the event log."""
        super().__init__(**kwargs)
        self._event_colors: dict[str, str] = {
            "worker_spawned": "green",
            "worker_completed": "blue",
            "handoff_received": "cyan",
            "merge_completed": "magenta",
            "watchdog_alert": "red",
            "reconciliation_started": "yellow",
            "reconciliation_completed": "yellow",
            "error_budget_changed": "yellow",
            "planner_decision": "white",
            "cost_update": "dim",
            "circuit_breaker_open": "red",
            "degradation_warning": "yellow",
            "degradation_critical": "red",
        }

    def on_mount(self) -> None:
        """Configure the log on mount."""
        self.auto_scroll = True
        self.markup = True

    def log_event(self, event: Any) -> None:
        """Log an event with appropriate formatting and color."""
        timestamp = getattr(event, "timestamp", datetime.now())
        event_type = getattr(event, "event_type", "unknown")
        agent_id = getattr(event, "agent_id", "")
        task_id = getattr(event, "task_id", "")
        color = self._event_colors.get(event_type, "white")
        time_str = timestamp.strftime("%H:%M:%S") if hasattr(timestamp, "strftime") else str(timestamp)
        message = f"[{time_str}] [{color}]{event_type}[/{color}]"
        if agent_id:
            message += f" ({agent_id})"
        if task_id:
            message += f" [dim]task={task_id}[/dim]"
        # Add details for specific event types
        if event_type == "watchdog_alert":
            failure_mode = getattr(event, "failure_mode", "")
            message += f" [red bold]⚠ {failure_mode}[/red bold]"
        self.write(message)


class WatchdogPanel(Static):
    """Panel displaying watchdog alerts with auto-clear."""

    alerts: reactive[list[dict[str, Any]]] = reactive([])

    def compose(self) -> Any:
        """Compose the widget layout."""
        yield Static(id="watchdog-content")

    def watch_alerts(self, value: list[dict[str, Any]]) -> None:
        """React to alert changes."""
        self._update_display()

    def on_mount(self) -> None:
        """Initialize the display on mount."""
        self._update_display()
        self.set_interval(1.0, self._check_expired_alerts)

    def _update_display(self) -> None:
        """Update the visual display of watchdog alerts."""
        content = self.query_one("#watchdog-content", Static)
        if not self.alerts:
            content.update("[dim]No active alerts[/dim]")
            self.remove_class("has-alerts")
        else:
            lines = ["Watchdog Alerts", ""]
            for alert in self.alerts:
                failure_mode = alert.get("failure_mode", "unknown")
                agent_id = alert.get("agent_id", "")
                lines.append(f"  [red]⚠ {failure_mode}[/red]")
                if agent_id:
                    lines[-1] += f" ({agent_id})"
            content.update("\n".join(lines))
            self.add_class("has-alerts")

    def add_alert(self, failure_mode: str, agent_id: str = "") -> None:
        """Add a new watchdog alert."""
        alert = {
            "failure_mode": failure_mode,
            "agent_id": agent_id,
            "timestamp": datetime.now(),
        }
        self.alerts = self.alerts + [alert]
        self._schedule_clear()

    def _check_expired_alerts(self) -> None:
        """Check and remove expired alerts."""
        now = datetime.now()
        expired = [alert for alert in self.alerts if (now - alert["timestamp"]).total_seconds() > 30]
        if expired:
            self.alerts = [alert for alert in self.alerts if alert not in expired]

    def _schedule_clear(self) -> None:
        """Schedule automatic clearing of alerts after 30 seconds."""
        self.set_timer(30.0, self._clear_all_alerts)

    def _clear_all_alerts(self) -> None:
        """Clear all alerts."""
        self.alerts = []

    def clear_alerts(self) -> None:
        """Manually clear all alerts."""
        self.alerts = []
