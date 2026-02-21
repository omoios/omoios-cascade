import asyncio
from typing import Any

from harness.events import EventBus, ResourceBoundExceeded


class ResourceBoundsEnforcer:
    def __init__(
        self,
        max_wall_time_per_task: int = 600,
        max_tokens_per_agent: int = 100_000,
        max_file_modifications: int = 50,
        max_consecutive_errors: int = 10,
        event_bus: EventBus | None = None,
    ):
        self.max_wall_time_per_task = max_wall_time_per_task
        self.max_tokens_per_agent = max_tokens_per_agent
        self.max_file_modifications = max_file_modifications
        self.max_consecutive_errors = max_consecutive_errors
        self.event_bus = event_bus

    def check_bounds(self, agent_id: str, metrics: dict[str, Any]) -> list[str]:
        violations: list[str] = []

        if int(metrics.get("wall_time_seconds", 0)) > self.max_wall_time_per_task:
            violations.append("max_wall_time_per_task")
        if int(metrics.get("tokens_used", 0)) > self.max_tokens_per_agent:
            violations.append("max_tokens_per_agent")
        if int(metrics.get("file_modifications", 0)) > self.max_file_modifications:
            violations.append("max_file_modifications")
        if int(metrics.get("consecutive_errors", 0)) > self.max_consecutive_errors:
            violations.append("max_consecutive_errors")

        if violations:
            self._emit_bound_exceeded(agent_id, violations, metrics)

        return violations

    def _emit_bound_exceeded(self, agent_id: str, violations: list[str], metrics: dict[str, Any]) -> None:
        if not self.event_bus:
            return

        event = ResourceBoundExceeded(
            agent_id=agent_id,
            violations=violations,
            details={"metrics": metrics, "violations": violations},
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.event_bus.emit(event))
            return

        loop.create_task(self.event_bus.emit(event))
