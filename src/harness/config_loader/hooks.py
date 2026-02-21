from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable

HookCallback = Callable[..., Awaitable[Any]]


class HookRegistry:
    VALID_EVENTS = frozenset(
        [
            "session_start",
            "session_end",
            "turn_start",
            "turn_end",
            "pre_tool_call",
            "post_tool_call",
            "worker_spawn",
            "worker_complete",
        ]
    )

    def __init__(self):
        self._hooks: dict[str, list[HookCallback]] = defaultdict(list)

    def on(self, event_name: str, callback: HookCallback) -> None:
        if event_name not in self.VALID_EVENTS:
            raise ValueError(f"Invalid hook event: {event_name}. Valid: {sorted(self.VALID_EVENTS)}")
        self._hooks[event_name].append(callback)

    async def fire(self, event_name: str, **kwargs: Any) -> list[Any]:
        results = []
        for callback in self._hooks.get(event_name, []):
            result = await callback(**kwargs)
            results.append(result)
        return results

    def has_hooks(self, event_name: str) -> bool:
        return bool(self._hooks.get(event_name))


def discover_hooks(workspace_root: str | Path) -> list[Path]:
    workspace_root = Path(workspace_root).resolve()

    search_dirs = [
        workspace_root / ".omp" / "hooks",
        workspace_root / ".claude" / "hooks",
    ]

    hook_files: list[Path] = []
    for hooks_dir in search_dirs:
        if not hooks_dir.is_dir():
            continue
        for py_file in sorted(hooks_dir.glob("*.py")):
            hook_files.append(py_file)

    return hook_files
