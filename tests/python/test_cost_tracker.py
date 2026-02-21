import asyncio

import pytest

from harness.events import EventBus
from harness.observability.cost_tracker import CostTracker


def test_cost_tracker_aggregates_agent_task_and_total_costs():
    tracker = CostTracker(cost_per_input_token=0.001, cost_per_output_token=0.002)

    tracker.record("agent-1", "task-1", input_tokens=100, output_tokens=50)
    tracker.record("agent-1", "task-1", input_tokens=10, output_tokens=5)
    tracker.record("agent-2", "task-2", input_tokens=200, output_tokens=10)

    agent_cost = tracker.get_agent_cost("agent-1")
    assert agent_cost.input_tokens == 110
    assert agent_cost.output_tokens == 55
    assert agent_cost.estimated_cost_usd == pytest.approx((110 * 0.001) + (55 * 0.002))

    task_cost = tracker.get_task_cost("task-1")
    assert task_cost.input_tokens == 110
    assert task_cost.output_tokens == 55

    total = tracker.get_total_cost()
    assert total.input_tokens == 310
    assert total.output_tokens == 65


@pytest.mark.asyncio
async def test_cost_tracker_emits_cost_update_event():
    bus = EventBus()
    seen = []

    def on_cost(event):
        seen.append(event)

    bus.subscribe("cost_update", on_cost)
    tracker = CostTracker(event_bus=bus, cost_per_input_token=0.001, cost_per_output_token=0.002)
    tracker.record("agent-1", "task-1", input_tokens=10, output_tokens=5)

    await asyncio.sleep(0)
    assert len(seen) == 1
    assert seen[0].event_type == "cost_update"
    assert seen[0].input_tokens == 10
    assert seen[0].output_tokens == 5
