from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from harness.config import WatchdogConfig
from harness.events import EventBus, WatchdogAlert
from harness.models.watchdog import ActivityEntry, FailureMode, WatchdogEvent

if TYPE_CHECKING:
    from harness.storage import HarnessDB


class Watchdog:
    def __init__(self, config: WatchdogConfig, event_bus: EventBus | None = None, db: HarnessDB | None = None):
        self.config = config
        self.event_bus = event_bus
        self._db = db
        self._activities: dict[str, list[ActivityEntry]] = {}
        self._completed_agents: set[str] = set()
        self._kill_callbacks: dict[str, Callable] = {}

    def record_activity(self, entry: ActivityEntry) -> None:
        if entry.agent_id not in self._activities:
            self._activities[entry.agent_id] = []
        self._activities[entry.agent_id].append(entry)
        # Persist to SQLite if available
        if self._db is not None:
            self._db.insert_activity(
                agent_id=entry.agent_id,
                event_type=entry.event_type,
                timestamp=entry.timestamp.timestamp(),
                tokens_used=entry.tokens_used,
                files_touched=entry.files_touched,
            )

    def register_kill_callback(self, agent_id: str, callback: Callable) -> None:
        """Register a callback to kill an agent when watchdog detects failure."""
        self._kill_callbacks[agent_id] = callback

    def mark_completed(self, agent_id: str) -> None:
        """Mark an agent as completed so check_agents skips it."""
        self._completed_agents.add(agent_id)
        # Clean up activities to prevent stale zombie checks
        self._activities.pop(agent_id, None)
        self._kill_callbacks.pop(agent_id, None)

    async def check_agents(self) -> list[WatchdogEvent]:
        events: list[WatchdogEvent] = []
        now = datetime.now()

        for agent_id, activities in self._activities.items():
            if agent_id in self._completed_agents:
                continue
            if not activities:
                continue

            last_activity = max(activities, key=lambda activity: activity.timestamp)
            inactive_seconds = (now - last_activity.timestamp).total_seconds()
            if inactive_seconds > self.config.zombie_timeout_seconds:
                evidence = f"No activity for {int(inactive_seconds)} seconds"
                events.append(
                    self._build_event(
                        agent_id=agent_id,
                        failure_mode=FailureMode.ZOMBIE,
                        evidence=evidence,
                    )
                )

            file_counts = Counter(
                file_path for activity in activities for file_path in activity.files_touched if file_path
            )
            for file_path, count in sorted(file_counts.items()):
                if count > self.config.tunnel_vision_threshold:
                    evidence = f"File {file_path} touched {count} times"
                    events.append(
                        self._build_event(
                            agent_id=agent_id,
                            failure_mode=FailureMode.TUNNEL_VISION,
                            evidence=evidence,
                        )
                    )

            total_tokens = sum(activity.tokens_used for activity in activities)
            has_tool_activity = any("tool" in activity.event_type.lower() for activity in activities)
            if total_tokens > self.config.token_burn_threshold and not has_tool_activity:
                evidence = f"Used {total_tokens} tokens without tool calls"
                events.append(
                    self._build_event(
                        agent_id=agent_id,
                        failure_mode=FailureMode.TOKEN_BURN,
                        evidence=evidence,
                    )
                )

        for event in events:
            await self._emit_alert(event)

        return events

    def _build_event(
        self,
        agent_id: str,
        failure_mode: FailureMode,
        evidence: str,
    ) -> WatchdogEvent:
        # Check if we have a kill callback for this agent
        action_taken = "kill_requested"
        if agent_id in self._kill_callbacks:
            try:
                self._kill_callbacks[agent_id]()
                action_taken = "killed"
            except Exception:
                action_taken = "kill_failed"
        return WatchdogEvent(
            agent_id=agent_id,
            failure_mode=failure_mode,
            evidence=evidence,
            action_taken=action_taken,
        )

    async def _emit_alert(self, event: WatchdogEvent) -> None:
        if self.event_bus is None:
            return

        await self.event_bus.emit(
            WatchdogAlert(
                agent_id=event.agent_id,
                failure_mode=event.failure_mode.value,
                details={
                    "evidence": event.evidence,
                    "action_taken": event.action_taken,
                },
            )
        )
