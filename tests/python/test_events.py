import asyncio

from harness.events import (
    EventBus,
    HarnessEvent,
    WorkerCompleted,
    WorkerSpawned,
)


async def test_emit_and_subscribe():
    bus = EventBus()
    callback_called = []

    def callback(event: HarnessEvent):
        callback_called.append(event)

    bus.subscribe("worker_spawned", callback)

    event = WorkerSpawned(task_id="task-123")
    await bus.emit(event)

    assert len(callback_called) == 1
    assert callback_called[0].task_id == "task-123"


async def test_history_records():
    bus = EventBus()

    await bus.emit(WorkerSpawned(task_id="task-1"))
    await bus.emit(WorkerCompleted(task_id="task-2"))
    await bus.emit(WorkerSpawned(task_id="task-3"))

    history = bus.history
    assert len(history) == 3
    assert history[0].task_id == "task-1"
    assert history[1].task_id == "task-2"
    assert history[2].task_id == "task-3"


async def test_async_concurrency():
    bus = EventBus()
    num_events = 100

    async def emit_events():
        for i in range(num_events):
            await bus.emit(WorkerSpawned(task_id=f"task-{i}"))

    await asyncio.gather(emit_events(), emit_events())

    assert len(bus.history) == num_events * 2


def test_event_serialization():
    original = WorkerSpawned(task_id="task-abc", agent_id="agent-1")
    original.details = {"priority": "high"}

    dumped = original.model_dump()
    restored = WorkerSpawned.model_validate(dumped)

    assert restored.task_id == original.task_id
    assert restored.agent_id == original.agent_id
    assert restored.event_type == original.event_type
    assert restored.details == original.details
    assert restored.timestamp == original.timestamp
