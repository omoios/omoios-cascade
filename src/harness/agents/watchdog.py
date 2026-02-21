from collections import Counter
from datetime import datetime

from harness.config import WatchdogConfig
from harness.events import EventBus, WatchdogAlert
from harness.models.watchdog import ActivityEntry, FailureMode, WatchdogEvent


class Watchdog:
    def __init__(self, config: WatchdogConfig, event_bus: EventBus | None = None):
        self.config = config
        self.event_bus = event_bus
        self._activities: dict[str, list[ActivityEntry]] = {}

    def record_activity(self, entry: ActivityEntry) -> None:
        if entry.agent_id not in self._activities:
            self._activities[entry.agent_id] = []
        self._activities[entry.agent_id].append(entry)

    async def check_agents(self) -> list[WatchdogEvent]:
        events: list[WatchdogEvent] = []
        now = datetime.now()

        for agent_id, activities in self._activities.items():
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
        return WatchdogEvent(
            agent_id=agent_id,
            failure_mode=failure_mode,
            evidence=evidence,
            action_taken="kill_requested",
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
