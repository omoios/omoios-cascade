import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ActivityLogger:
    def __init__(self, output_dir: str = ".activity", run_id: str | None = None):
        self.output_dir = Path(output_dir)
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.run_dir = self.output_dir / self.run_id
        self._lock = asyncio.Lock()

    async def log(self, agent_id: str, event_type: str, **kwargs: Any) -> None:
        metrics = kwargs.pop("metrics", {})
        tool = kwargs.pop("tool", None)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "tool": tool,
            "metrics": metrics if isinstance(metrics, dict) else {"value": metrics},
            "agent_id": agent_id,
        }
        if kwargs:
            payload.update(kwargs)

        line = json.dumps(payload, ensure_ascii=True)
        target = self.run_dir / f"{agent_id}.jsonl"

        async with self._lock:
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(self._append_line, target, line)

    def _append_line(self, path: Path, line: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")

    async def flush(self) -> None:
        async with self._lock:
            return None
