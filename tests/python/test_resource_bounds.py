import asyncio

import pytest

from harness.events import EventBus
from harness.observability.resource_bounds import ResourceBoundsEnforcer


def test_resource_bounds_returns_violations_without_bus():
    enforcer = ResourceBoundsEnforcer(
        max_wall_time_per_task=10,
        max_tokens_per_agent=100,
        max_file_modifications=2,
        max_consecutive_errors=1,
    )

    violations = enforcer.check_bounds(
        "worker-1",
        {
            "wall_time_seconds": 11,
            "tokens_used": 101,
            "file_modifications": 3,
            "consecutive_errors": 2,
        },
    )

    assert violations == [
        "max_wall_time_per_task",
        "max_tokens_per_agent",
        "max_file_modifications",
        "max_consecutive_errors",
    ]


@pytest.mark.asyncio
async def test_resource_bounds_emits_event_when_exceeded():
    bus = EventBus()
    seen = []

    def on_bound(event):
        seen.append(event)

    bus.subscribe("resource_bound_exceeded", on_bound)
    enforcer = ResourceBoundsEnforcer(max_tokens_per_agent=10, event_bus=bus)

    violations = enforcer.check_bounds("worker-2", {"tokens_used": 11})
    await asyncio.sleep(0)

    assert violations == ["max_tokens_per_agent"]
    assert len(seen) == 1
    assert seen[0].violations == ["max_tokens_per_agent"]
