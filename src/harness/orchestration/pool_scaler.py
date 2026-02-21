import asyncio
from typing import Literal

from pydantic import BaseModel

from harness.events import DegradationCritical, DegradationWarning, EventBus, PoolScaleDown, PoolScaleUp


class ScalingDecision(BaseModel):
    decision: Literal["scale_up", "scale_down", "no_change"]
    target_count: int


class PoolScaler:
    def __init__(
        self,
        min_workers: int = 1,
        max_workers: int = 20,
        scale_factor: float = 2.0,
        check_interval: int = 30,
        event_bus: EventBus | None = None,
    ):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.scale_factor = scale_factor
        self.check_interval = check_interval
        self.event_bus = event_bus
        self._base_max_workers = max_workers
        self._degraded_max_workers = max_workers
        self._degradation_state = "normal"

    def check_system_resources(self) -> dict[str, float]:
        try:
            import psutil
        except ImportError:
            return {}

        memory_percent = float(psutil.virtual_memory().percent)
        cpu_percent = float(psutil.cpu_percent(interval=None))
        return {"memory_percent": memory_percent, "cpu_percent": cpu_percent}

    async def check_scaling(self, pending_count: int, active_count: int, idle_count: int) -> ScalingDecision:
        resources = self.check_system_resources()
        await self._apply_degradation(resources)

        effective_max_workers = self._degraded_max_workers
        if pending_count > (active_count * self.scale_factor) and active_count < effective_max_workers:
            target = min(effective_max_workers, max(active_count + 1, self.min_workers))
            await self._emit_scale_up(target, pending_count, active_count)
            return ScalingDecision(decision="scale_up", target_count=target)

        if pending_count == 0 and idle_count > self.min_workers:
            target = max(self.min_workers, active_count - 1)
            await self._emit_scale_down(target, idle_count)
            return ScalingDecision(decision="scale_down", target_count=target)

        return ScalingDecision(decision="no_change", target_count=active_count)

    async def _apply_degradation(self, resources: dict[str, float]) -> None:
        if not resources:
            return

        memory = resources.get("memory_percent", 0.0)
        cpu = resources.get("cpu_percent", 0.0)

        if memory > 90.0:
            self._degraded_max_workers = self.min_workers
            if self._degradation_state != "critical":
                self._degradation_state = "critical"
                await self._emit_degradation_critical(memory, cpu)
            return

        if memory > 80.0:
            self._degraded_max_workers = max(self.min_workers, self._base_max_workers // 2)
            if self._degradation_state != "warning":
                self._degradation_state = "warning"
                await self._emit_degradation_warning(memory, cpu)
            return

        if self._degraded_max_workers < self._base_max_workers:
            self._degraded_max_workers = min(self._base_max_workers, self._degraded_max_workers + 1)
        self._degradation_state = "normal"

    async def _emit_scale_up(self, target_count: int, pending_count: int, active_count: int) -> None:
        if not self.event_bus:
            return
        await self.event_bus.emit(
            PoolScaleUp(
                target_count=target_count,
                details={"pending_count": pending_count, "active_count": active_count},
            )
        )

    async def _emit_scale_down(self, target_count: int, idle_count: int) -> None:
        if not self.event_bus:
            return
        await self.event_bus.emit(
            PoolScaleDown(
                target_count=target_count,
                details={"idle_count": idle_count},
            )
        )

    async def _emit_degradation_warning(self, memory_percent: float, cpu_percent: float) -> None:
        if not self.event_bus:
            return
        await self.event_bus.emit(DegradationWarning(memory_percent=memory_percent, cpu_percent=cpu_percent))

    async def _emit_degradation_critical(self, memory_percent: float, cpu_percent: float) -> None:
        if not self.event_bus:
            return
        await self.event_bus.emit(DegradationCritical(memory_percent=memory_percent, cpu_percent=cpu_percent))

    def emit_scale_up(self, target_count: int, pending_count: int, active_count: int) -> None:
        if not self.event_bus:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._emit_scale_up(target_count, pending_count, active_count))
            return
        loop.create_task(self._emit_scale_up(target_count, pending_count, active_count))

    def emit_scale_down(self, target_count: int, idle_count: int) -> None:
        if not self.event_bus:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._emit_scale_down(target_count, idle_count))
            return
        loop.create_task(self._emit_scale_down(target_count, idle_count))
