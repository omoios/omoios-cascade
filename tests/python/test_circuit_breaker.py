import pytest

from harness.events import EventBus
from harness.orchestration import circuit_breaker as circuit_breaker_module
from harness.orchestration.circuit_breaker import CircuitBreaker


def test_circuit_breaker_opens_when_error_rate_exceeds_threshold(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(circuit_breaker_module.time, "monotonic", lambda: now[0])

    breaker = CircuitBreaker(error_threshold=0.5, cooldown_seconds=10, window_seconds=60)
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == CircuitBreaker.OPEN
    assert breaker.can_proceed() is False


def test_circuit_breaker_half_open_and_close_on_success(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(circuit_breaker_module.time, "monotonic", lambda: now[0])

    breaker = CircuitBreaker(error_threshold=0.0, cooldown_seconds=10, window_seconds=60)
    breaker.record_failure()
    assert breaker.state == CircuitBreaker.OPEN

    now[0] = 111.0
    assert breaker.can_proceed() is True
    assert breaker.state == CircuitBreaker.HALF_OPEN

    breaker.record_success()
    assert breaker.state == CircuitBreaker.CLOSED


@pytest.mark.asyncio
async def test_circuit_breaker_emits_events(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(circuit_breaker_module.time, "monotonic", lambda: now[0])

    bus = EventBus()
    seen = []

    def on_event(event):
        seen.append(event.event_type)

    bus.subscribe("circuit_breaker_open", on_event)
    bus.subscribe("circuit_breaker_closed", on_event)

    breaker = CircuitBreaker(error_threshold=0.0, cooldown_seconds=10, window_seconds=60, event_bus=bus)
    breaker.record_failure()
    now[0] = 111.0
    _ = breaker.can_proceed()
    breaker.record_success()

    await __import__("asyncio").sleep(0)
    assert "circuit_breaker_open" in seen
    assert "circuit_breaker_closed" in seen
