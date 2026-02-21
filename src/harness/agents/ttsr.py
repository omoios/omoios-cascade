from typing import Any

from harness.events import TTSRFired


class TTSRMixin:
    _TTSR_START_TEXT = "Before starting, think about your approach. What files do you need? What's your plan?"
    _TTSR_REVIEW_TEXT = "Review: Is your approach working? Adjust if needed."

    def _init_ttsr_state(self) -> None:
        self._ttsr_fired = False
        self._ttsr_review_fired = False
        self._ttsr_pending_system_messages: list[str] = []

    async def _ttsr_before_llm_call(self) -> None:
        if self._ttsr_fired:
            return
        self._ttsr_pending_system_messages.append(self._TTSR_START_TEXT)
        self._ttsr_fired = True
        if self.event_bus:
            await self.event_bus.emit(TTSRFired(agent_id=self.config.agent_id))

    async def _ttsr_on_tool_result(self, results: list[dict[str, Any]]) -> None:
        if not self._ttsr_fired or self._ttsr_review_fired:
            return
        if not results:
            return
        self._ttsr_pending_system_messages.append(self._TTSR_REVIEW_TEXT)
        self._ttsr_review_fired = True

    def _ttsr_consume_system_messages(self) -> str:
        if not self._ttsr_pending_system_messages:
            return ""
        content = "\n\n".join(self._ttsr_pending_system_messages)
        self._ttsr_pending_system_messages = []
        return content
