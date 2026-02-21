import json
import os
import signal
from typing import Callable

from pydantic import BaseModel, Field


class HarnessCheckpoint(BaseModel):
    task_states: dict[str, str] = Field(default_factory=dict)
    worker_states: dict[str, str] = Field(default_factory=dict)
    error_budget_snapshot: dict = Field(default_factory=dict)
    scratchpad_content: dict[str, str] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


def checkpoint(state: HarnessCheckpoint, path: str) -> None:
    with open(path, "w", encoding="utf-8") as file:
        file.write(state.model_dump_json(indent=2))


def resume(path: str) -> HarnessCheckpoint:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as file:
        data = file.read()
    json.loads(data)
    return HarnessCheckpoint.model_validate_json(data)


class ShutdownHandler:
    def __init__(self) -> None:
        self._shutdown_requested = False
        self._callbacks: list[Callable] = []

    def register(self) -> None:
        def _handler(_signum: int, _frame: object | None) -> None:
            self.request_shutdown()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def add_callback(self, fn: Callable) -> None:
        self._callbacks.append(fn)

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        for callback in list(self._callbacks):
            try:
                callback()
            except Exception:
                pass
