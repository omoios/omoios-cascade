import pytest

from harness.events import EventBus
from harness.orchestration.pool_scaler import PoolScaler


@pytest.mark.asyncio
async def test_pool_scaler_scales_up_and_down():
    scaler = PoolScaler(min_workers=1, max_workers=10, scale_factor=2.0)
    scaler.check_system_resources = lambda: {}

    up = await scaler.check_scaling(pending_count=10, active_count=2, idle_count=0)
    assert up.decision == "scale_up"
    assert up.target_count == 3

    down = await scaler.check_scaling(pending_count=0, active_count=5, idle_count=4)
    assert down.decision == "scale_down"
    assert down.target_count == 4


@pytest.mark.asyncio
async def test_pool_scaler_degradation_thresholds():
    bus = EventBus()
    seen = []

    def on_warning(event):
        seen.append(event.event_type)

    bus.subscribe("degradation_warning", on_warning)
    bus.subscribe("degradation_critical", on_warning)

    scaler = PoolScaler(min_workers=2, max_workers=10, scale_factor=2.0, event_bus=bus)

    scaler.check_system_resources = lambda: {"memory_percent": 85.0, "cpu_percent": 10.0}
    _ = await scaler.check_scaling(pending_count=20, active_count=2, idle_count=0)
    assert scaler._degraded_max_workers == 5

    scaler.check_system_resources = lambda: {"memory_percent": 91.0, "cpu_percent": 10.0}
    _ = await scaler.check_scaling(pending_count=20, active_count=2, idle_count=0)
    assert scaler._degraded_max_workers == 2

    scaler.check_system_resources = lambda: {"memory_percent": 50.0, "cpu_percent": 10.0}
    _ = await scaler.check_scaling(pending_count=0, active_count=2, idle_count=2)
    assert scaler._degraded_max_workers == 3

    assert "degradation_warning" in seen
    assert "degradation_critical" in seen
