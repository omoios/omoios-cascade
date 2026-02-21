import asyncio
import time
from collections import deque

from harness.events import CircuitBreakerClosed, CircuitBreakerOpen, EventBus


class CircuitBreaker:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        error_threshold: float = 0.5,
        cooldown_seconds: int = 120,
        window_seconds: int = 60,
        event_bus: EventBus | None = None,
    ):
        self.error_threshold = error_threshold
        self.cooldown_seconds = cooldown_seconds
        self.window_seconds = window_seconds
        self.event_bus = event_bus
        self._state = self.CLOSED
        self._opened_at: float | None = None
        self._outcomes: deque[tuple[float, bool]] = deque()

    @property
    def state(self) -> str:
        return self._state

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._outcomes and self._outcomes[0][0] < cutoff:
            self._outcomes.popleft()

    def _error_rate(self, now: float) -> float:
        self._prune(now)
        if not self._outcomes:
            return 0.0
        failures = sum(1 for _, success in self._outcomes if not success)
        return failures / len(self._outcomes)

    def _transition_to_open(self, now: float) -> None:
        if self._state == self.OPEN:
            return
        self._state = self.OPEN
        self._opened_at = now
        self._emit_open()

    def _transition_to_closed(self) -> None:
        if self._state == self.CLOSED:
            return
        self._state = self.CLOSED
        self._opened_at = None
        self._emit_closed()

    def record_success(self) -> None:
        now = time.monotonic()
        self._outcomes.append((now, True))
        self._prune(now)
        if self._state == self.HALF_OPEN:
            self._transition_to_closed()

    def record_failure(self) -> None:
        now = time.monotonic()
        self._outcomes.append((now, False))
        rate = self._error_rate(now)

        if self._state == self.HALF_OPEN:
            self._transition_to_open(now)
            return

        if self._state == self.CLOSED and rate > self.error_threshold:
            self._transition_to_open(now)

    def can_proceed(self) -> bool:
        now = time.monotonic()
        if self._state == self.CLOSED:
            return True

        if self._state == self.OPEN:
            if self._opened_at is None:
                self._opened_at = now
                return False
            if (now - self._opened_at) >= self.cooldown_seconds:
                self._state = self.HALF_OPEN
                return True
            return False

        return True

    def _emit_open(self) -> None:
        if not self.event_bus:
            return
        event = CircuitBreakerOpen(details={"state": self._state})
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.event_bus.emit(event))
            return
        loop.create_task(self.event_bus.emit(event))

    def _emit_closed(self) -> None:
        if not self.event_bus:
            return
        event = CircuitBreakerClosed(details={"state": self._state})
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.event_bus.emit(event))
            return
        loop.create_task(self.event_bus.emit(event))
