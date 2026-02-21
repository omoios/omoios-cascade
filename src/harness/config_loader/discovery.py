from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from harness.events import EventBus, ExtensionsDiscovered

_EXTENSION_DIRS: list[tuple[str, str, str]] = [
    ("cursor", ".cursor", "cursor"),
    ("copilot", ".github/copilot", "copilot"),
    ("vscode", ".vscode", "vscode"),
    ("claude", ".claude", "claude"),
    ("omp", ".omp", "omp"),
    ("aider", ".aider", "aider"),
    ("continue", ".continue", "continue"),
    ("windsurf", ".windsurf", "windsurf"),
]


class DiscoveredExtension(BaseModel):
    name: str
    config_path: str
    tool_type: str


async def discover_extensions(
    workspace_root: str | Path,
    event_bus: EventBus | None = None,
) -> list[DiscoveredExtension]:
    root = Path(workspace_root).resolve()
    discovered: list[DiscoveredExtension] = []

    for name, rel_path, tool_type in _EXTENSION_DIRS:
        candidate = root / rel_path
        if candidate.exists():
            discovered.append(
                DiscoveredExtension(
                    name=name,
                    config_path=str(candidate),
                    tool_type=tool_type,
                )
            )

    if event_bus:
        await event_bus.emit(
            ExtensionsDiscovered(
                extensions=[ext.name for ext in discovered],
                details={"count": len(discovered)},
            )
        )

    return discovered
