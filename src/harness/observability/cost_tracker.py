import asyncio

from pydantic import BaseModel

from harness.events import CostUpdate, EventBus


class CostRecord(BaseModel):
    agent_id: str = ""
    task_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    estimated_cost_usd: float = 0.0


class CostTracker:
    def __init__(
        self,
        event_bus: EventBus | None = None,
        cost_per_input_token: float = 0.0,
        cost_per_output_token: float = 0.0,
    ):
        self.event_bus = event_bus
        self.cost_per_input_token = cost_per_input_token
        self.cost_per_output_token = cost_per_output_token
        self._records: list[CostRecord] = []

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.cost_per_input_token) + (output_tokens * self.cost_per_output_token)

    def record(
        self,
        agent_id: str,
        task_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> CostRecord:
        record = CostRecord(
            agent_id=agent_id,
            task_id=task_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read=cache_read,
            cache_write=cache_write,
            estimated_cost_usd=self._estimate_cost(input_tokens, output_tokens),
        )
        self._records.append(record)
        self._emit_update(record)
        return record

    def _emit_update(self, record: CostRecord) -> None:
        if not self.event_bus:
            return

        event = CostUpdate(
            agent_id=record.agent_id,
            task_id=record.task_id,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            cache_read_tokens=record.cache_read,
            cache_write_tokens=record.cache_write,
            estimated_cost_usd=record.estimated_cost_usd,
            details={"record": record.model_dump()},
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.event_bus.emit(event))
            return

        loop.create_task(self.event_bus.emit(event))

    def _aggregate(self, records: list[CostRecord], agent_id: str = "", task_id: str = "") -> CostRecord:
        return CostRecord(
            agent_id=agent_id,
            task_id=task_id,
            input_tokens=sum(record.input_tokens for record in records),
            output_tokens=sum(record.output_tokens for record in records),
            cache_read=sum(record.cache_read for record in records),
            cache_write=sum(record.cache_write for record in records),
            estimated_cost_usd=sum(record.estimated_cost_usd for record in records),
        )

    def get_agent_cost(self, agent_id: str) -> CostRecord:
        records = [record for record in self._records if record.agent_id == agent_id]
        return self._aggregate(records, agent_id=agent_id)

    def get_task_cost(self, task_id: str) -> CostRecord:
        records = [record for record in self._records if record.task_id == task_id]
        return self._aggregate(records, task_id=task_id)

    def get_total_cost(self) -> CostRecord:
        return self._aggregate(self._records)
