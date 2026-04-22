"""Main Textual TUI App for the orchestration harness."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static
from textual import work

from harness.events import (
    CircuitBreakerOpen,
    CostUpdate,
    DegradationWarning,
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
from harness.tui.widgets import (
    CostWidget,
    EventLogWidget,
    TaskBoardWidget,
    WatchdogPanel,
    WorkerTableWidget,
)


class HarnessTUI(App):
    """Textual TUI for the multi-agent orchestration harness."""

    CSS_PATH = "harness.tcss"

    BINDINGS = [
        Binding(key="q", action="quit", description="Quit"),
        Binding(key="d", action="toggle_dark", description="Toggle Dark"),
        Binding(key="t", action="toggle_task_board", description="Toggle Tasks"),
        Binding(key="l", action="toggle_log", description="Toggle Log"),
        Binding(key="w", action="focus_workers", description="Focus Workers"),
        Binding(key="c", action="clear_alerts", description="Clear Alerts"),
        Binding(key="r", action="refresh_state", description="Refresh"),
    ]

    def __init__(self) -> None:
        """Initialize the TUI app."""
        super().__init__()
        self._event_bus: EventBus | None = None
        self._runner: Any = None
        self._worker_tokens: dict[str, int] = {}
        self._harness_instructions: str = ""
        self._harness_runner: Any = None

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header(show_clock=True)

        with Horizontal(id="main-grid"):
            # Sidebar
            with Vertical(id="sidebar"):
                yield TaskBoardWidget(id="task-board")
                yield CostWidget(id="cost-widget")
                yield WatchdogPanel(id="watchdog-panel")

            # Main content
            with Vertical(id="main-content"):
                with Static(id="worker-container"):
                    yield WorkerTableWidget(id="worker-table")
                with Static(id="event-log-container"):
                    yield EventLogWidget(id="event-log")

        yield Footer()

    def connect_event_bus(self, event_bus: EventBus) -> None:
        """Connect to the EventBus and subscribe to all event types."""
        self._event_bus = event_bus

        # Subscribe to all event types with type-specific handlers
        event_subscriptions = [
            (WorkerSpawned().event_type, self._on_worker_spawned),
            (WorkerCompleted().event_type, self._on_worker_completed),
            (HandoffReceived().event_type, self._on_handoff_received),
            (MergeCompleted().event_type, self._on_merge_completed),
            (WatchdogAlert().event_type, self._on_watchdog_alert),
            (ReconciliationStarted().event_type, self._on_reconciliation_started),
            (ReconciliationCompleted().event_type, self._on_reconciliation_completed),
            (ErrorBudgetChanged().event_type, self._on_error_budget_changed),
            (PlannerDecision().event_type, self._on_planner_decision),
            (CostUpdate().event_type, self._on_cost_update),
            (CircuitBreakerOpen().event_type, self._on_circuit_breaker_open),
            (DegradationWarning().event_type, self._on_degradation_warning),
        ]

        for event_type, handler in event_subscriptions:
            event_bus.subscribe(event_type, handler)

    def connect_runner(self, runner: Any) -> None:
        """Connect to the HarnessRunner for state access."""
        self._runner = runner
        self._refresh_state_from_runner()

    def _refresh_state_from_runner(self) -> None:
        """Refresh widget state from the runner."""
        if self._runner is None:
            return

        # Update task board from runner state
        self.call_later(self._update_task_board_from_runner)
        self.call_later(self._update_worker_table_from_runner)

    def _update_task_board_from_runner(self) -> None:
        """Update task board widget from runner state."""
        if self._runner is None:
            return

        task_board = getattr(self._runner, "task_board", None)
        if task_board is None:
            return

        task_board_widget = self.query_one("#task-board", TaskBoardWidget)
        task_board_widget.update_counts(
            pending=getattr(task_board, "pending", 0),
            in_progress=getattr(task_board, "in_progress", 0),
            completed=getattr(task_board, "completed", 0),
            failed=getattr(task_board, "failed", 0),
            blocked=getattr(task_board, "blocked", 0),
        )

    def _update_worker_table_from_runner(self) -> None:
        """Update worker table from runner state."""
        if self._runner is None:
            return

        workers = getattr(self._runner, "workers", {})
        worker_table = self.query_one("#worker-table", WorkerTableWidget)

        for worker_id, worker_data in workers.items():
            if isinstance(worker_data, dict):
                task_id = worker_data.get("task_id", "")
                status = worker_data.get("status", "")
            else:
                task_id = getattr(worker_data, "task_id", "")
                status = getattr(worker_data, "status", "")

            if worker_id not in worker_table._worker_rows:
                worker_table.add_worker(worker_id, task_id, status)
            else:
                worker_table.update_worker(worker_id, status)

    def _log_event(self, event: HarnessEvent) -> None:
        """Log an event to the event log widget."""
        event_log = self.query_one("#event-log", EventLogWidget)
        event_log.log_event(event)

    def _on_worker_spawned(self, event: WorkerSpawned) -> None:
        """Handle WorkerSpawned event."""

        def update() -> None:
            self._log_event(event)
            worker_table = self.query_one("#worker-table", WorkerTableWidget)
            worker_table.add_worker(event.agent_id, event.task_id, "running")
            self._update_task_board_from_runner()

        self.call_later(update)

    def _on_worker_completed(self, event: WorkerCompleted) -> None:
        """Handle WorkerCompleted event."""

        def update() -> None:
            self._log_event(event)
            worker_table = self.query_one("#worker-table", WorkerTableWidget)
            tokens = self._worker_tokens.get(event.agent_id, 0)
            worker_table.update_worker(event.agent_id, "completed", tokens)
            self._update_task_board_from_runner()

        self.call_later(update)

    def _on_handoff_received(self, event: HandoffReceived) -> None:
        """Handle HandoffReceived event."""

        def update() -> None:
            self._log_event(event)
            self._update_task_board_from_runner()

        self.call_later(update)

    def _on_merge_completed(self, event: MergeCompleted) -> None:
        """Handle MergeCompleted event."""

        def update() -> None:
            self._log_event(event)
            self._update_task_board_from_runner()

        self.call_later(update)

    def _on_watchdog_alert(self, event: WatchdogAlert) -> None:
        """Handle WatchdogAlert event."""

        def update() -> None:
            self._log_event(event)
            watchdog_panel = self.query_one("#watchdog-panel", WatchdogPanel)
            watchdog_panel.add_alert(event.failure_mode, event.agent_id)

        self.call_later(update)

    def _on_reconciliation_started(self, event: ReconciliationStarted) -> None:
        """Handle ReconciliationStarted event."""

        def update() -> None:
            self._log_event(event)

        self.call_later(update)

    def _on_reconciliation_completed(self, event: ReconciliationCompleted) -> None:
        """Handle ReconciliationCompleted event."""

        def update() -> None:
            self._log_event(event)
            self._update_task_board_from_runner()

        self.call_later(update)

    def _on_error_budget_changed(self, event: ErrorBudgetChanged) -> None:
        """Handle ErrorBudgetChanged event."""

        def update() -> None:
            self._log_event(event)

        self.call_later(update)

    def _on_planner_decision(self, event: PlannerDecision) -> None:
        """Handle PlannerDecision event."""

        def update() -> None:
            self._log_event(event)

        self.call_later(update)

    def _on_cost_update(self, event: CostUpdate) -> None:
        """Handle CostUpdate event."""

        def update() -> None:
            self._log_event(event)
            cost_widget = self.query_one("#cost-widget", CostWidget)
            cost_widget.update_cost(
                {
                    "input_tokens": event.input_tokens,
                    "output_tokens": event.output_tokens,
                    "cache_read_tokens": event.cache_read_tokens,
                    "cache_write_tokens": event.cache_write_tokens,
                    "estimated_cost_usd": event.estimated_cost_usd,
                }
            )
            self._worker_tokens[event.agent_id] = event.input_tokens + event.output_tokens

        self.call_later(update)

    def _on_circuit_breaker_open(self, event: CircuitBreakerOpen) -> None:
        """Handle CircuitBreakerOpen event."""

        def update() -> None:
            self._log_event(event)

        self.call_later(update)

    def _on_degradation_warning(self, event: DegradationWarning) -> None:
        """Handle DegradationWarning event."""

        def update() -> None:
            self._log_event(event)
            watchdog_panel = self.query_one("#watchdog-panel", WatchdogPanel)
            watchdog_panel.add_alert(
                f"Degradation: CPU {event.cpu_percent:.1f}%, Mem {event.memory_percent:.1f}%",
                "",
            )

        self.call_later(update)

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.dark = not self.dark

    def action_toggle_task_board(self) -> None:
        """Toggle visibility of the task board."""
        task_board = self.query_one("#task-board", TaskBoardWidget)
        task_board.toggle_class("hidden")

    def action_toggle_log(self) -> None:
        """Toggle visibility of the event log."""
        event_log_container = self.query_one("#event-log-container", Static)
        event_log_container.toggle_class("hidden")

    def action_focus_workers(self) -> None:
        """Focus the worker table."""
        self.query_one("#worker-table", WorkerTableWidget).focus()

    def action_clear_alerts(self) -> None:
        """Clear all watchdog alerts."""
        self.query_one("#watchdog-panel", WatchdogPanel).clear_alerts()

    def action_refresh_state(self) -> None:
        """Force refresh state from runner."""
        self._refresh_state_from_runner()

    def on_mount(self) -> None:
        """Initialize on mount and optionally launch harness."""
        self.title = "Harness TUI"
        self.sub_title = "Multi-Agent Orchestration"
        if self._harness_runner and self._harness_instructions:
            self._log_startup_config()
            self.run_harness_task()

    def _log_startup_config(self) -> None:
        """Log config details to the event log on startup."""
        runner = self._harness_runner
        if runner is None:
            return
        config = runner.config
        key = config.llm.api_key
        masked_key = key[:8] + '...' + key[-4:] if len(key) > 12 else '***'
        base_url = config.llm.base_url or 'https://api.anthropic.com (default)'
        cache_mode = 'explicit markers' if config.llm.enable_explicit_cache_control else 'provider auto-cache'
        event_log = self.query_one('#event-log', EventLogWidget)
        event_log.write('[bold]Harness Config[/bold]')
        event_log.write(f'  Model:     [cyan]{config.models.default}[/cyan]')
        event_log.write(f'  Base URL:  [cyan]{base_url}[/cyan]')
        event_log.write(f'  API Key:   [dim]{masked_key}[/dim]')
        event_log.write(f'  Caching:   {cache_mode}')
        event_log.write(f'  Repos:     {config.repos or "(none)"}')
        event_log.write(f'  Task:      [yellow]{self._harness_instructions}[/yellow]')
        event_log.write('')

    @work(thread=False)
    async def run_harness_task(self) -> None:
        """Run the harness as an async Textual worker."""
        try:
            result = await self._harness_runner.run(self._harness_instructions)
            event_log = self.query_one("#event-log", EventLogWidget)
            event_log.write(f"\n[bold green]Harness complete![/bold green]\nResult: {result}")
        except Exception as exc:
            event_log = self.query_one("#event-log", EventLogWidget)
            event_log.write(f"\n[bold red]Harness error: {exc}[/bold red]")
