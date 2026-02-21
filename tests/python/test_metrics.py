import json

import pytest

from harness.events import CostUpdate, EventBus, MergeCompleted, WorkerCompleted, WorkerSpawned
from harness.observability.metrics import MetricsCollector


@pytest.mark.asyncio
async def test_metrics_collector_snapshot_updates_from_events(tmp_path):
    bus = EventBus()
    collector = MetricsCollector(event_bus=bus)

    await bus.emit(WorkerSpawned(agent_id="worker-1", task_id="t1"))
    await bus.emit(
        CostUpdate(
            agent_id="worker-1",
            task_id="t1",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=5,
            cache_write_tokens=1,
            estimated_cost_usd=0.25,
        )
    )
    await bus.emit(MergeCompleted(status="success"))
    await bus.emit(WorkerCompleted(agent_id="worker-1", task_id="t1", details={"duration_seconds": 4.0}))

    snapshot = collector.snapshot()
    assert snapshot["tasks_completed"] == 1
    assert snapshot["workers_active"] == 0
    assert snapshot["workers_idle"] == 1
    assert snapshot["tokens_total"] == 156
    assert snapshot["cost_total"] == pytest.approx(0.25)
    assert snapshot["merge_success_rate"] == pytest.approx(1.0)
    assert snapshot["average_task_duration"] == pytest.approx(4.0)

    metrics_file = tmp_path / "metrics.jsonl"
    collector.to_jsonl(str(metrics_file))
    line = metrics_file.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["tasks_completed"] == 1
