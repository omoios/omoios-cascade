import pytest

from harness.config_loader.discovery import discover_extensions
from harness.events import EventBus


@pytest.mark.asyncio
async def test_discover_extensions_finds_known_tool_dirs(tmp_path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".vscode").mkdir()

    bus = EventBus()
    captured = []

    def _on_event(event):
        captured.append(event)

    bus.subscribe("extensions_discovered", _on_event)

    discovered = await discover_extensions(tmp_path, event_bus=bus)
    names = {item.name for item in discovered}

    assert "cursor" in names
    assert "vscode" in names
    assert len(captured) == 1
    assert set(captured[0].extensions) == names
