
import pytest

from harness.events import (
    EventBus,
    WorkerCompleted,
    WorkerSpawned,
)


class TestEventBusIntegration:
    @pytest.mark.asyncio
    async def test_event_bus_single_listener(self):
        bus = EventBus()
        received = []

        bus.subscribe("worker_spawned", lambda e: received.append(e))
        await bus.emit(WorkerSpawned(agent_id="w1", task_id="t1"))

        assert len(received) == 1
        assert received[0].agent_id == "w1"

    @pytest.mark.asyncio
    async def test_event_bus_multiple_listeners(self):
        bus = EventBus()
        r1, r2, r3 = [], [], []

        bus.subscribe("worker_spawned", lambda e: r1.append(e))
        bus.subscribe("worker_spawned", lambda e: r2.append(e))
        bus.subscribe("worker_spawned", lambda e: r3.append(e))
        await bus.emit(WorkerSpawned(agent_id="w1"))

        assert len(r1) == 1
        assert len(r2) == 1
        assert len(r3) == 1

    @pytest.mark.asyncio
    async def test_event_bus_type_filtering(self):
        bus = EventBus()
        spawned_events = []

        bus.subscribe("worker_spawned", lambda e: spawned_events.append(e))
        await bus.emit(WorkerCompleted(agent_id="w1"))

        assert len(spawned_events) == 0

    @pytest.mark.asyncio
    async def test_event_bus_ordering(self):
        bus = EventBus()
        received = []

        bus.subscribe("worker_spawned", lambda e: received.append(e.agent_id))

        for i in range(5):
            await bus.emit(WorkerSpawned(agent_id=f"w{i}"))

        assert received == ["w0", "w1", "w2", "w3", "w4"]

    @pytest.mark.asyncio
    async def test_event_bus_listener_exception(self):
        bus = EventBus()
        good_events = []

        def bad_listener(e):
            raise ValueError("boom")

        bus.subscribe("worker_spawned", bad_listener)
        bus.subscribe("worker_spawned", lambda e: good_events.append(e))

        with pytest.raises(ValueError):
            await bus.emit(WorkerSpawned(agent_id="w1"))

    @pytest.mark.asyncio
    async def test_event_bus_history(self):
        bus = EventBus()

        for i in range(10):
            await bus.emit(WorkerSpawned(agent_id=f"w{i}"))

        assert len(bus.history) == 10
        assert all(isinstance(e, WorkerSpawned) for e in bus.history)
