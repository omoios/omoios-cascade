import pytest

from harness.config_loader.hooks import HookRegistry, discover_hooks


def test_hook_registry_on_registers_callback():
    registry = HookRegistry()

    async def callback(**kwargs):
        return kwargs

    registry.on("session_start", callback)

    assert registry.has_hooks("session_start") is True


@pytest.mark.asyncio
async def test_hook_registry_fire_calls_registered_callbacks():
    registry = HookRegistry()

    async def callback_one(value):
        return value + 1

    async def callback_two(value):
        return value * 2

    registry.on("turn_start", callback_one)
    registry.on("turn_start", callback_two)

    results = await registry.fire("turn_start", value=3)

    assert results == [4, 6]


@pytest.mark.asyncio
async def test_hook_registry_fire_with_no_hooks_returns_empty():
    registry = HookRegistry()

    results = await registry.fire("turn_end", value=10)

    assert results == []


def test_hook_registry_on_rejects_invalid_event_name():
    registry = HookRegistry()

    async def callback(**kwargs):
        return kwargs

    with pytest.raises(ValueError, match="Invalid hook event"):
        registry.on("invalid_event", callback)


def test_hook_registry_has_hooks_returns_correct_boolean():
    registry = HookRegistry()

    async def callback(**kwargs):
        return kwargs

    assert registry.has_hooks("worker_spawn") is False
    registry.on("worker_spawn", callback)
    assert registry.has_hooks("worker_spawn") is True


def test_discover_hooks_finds_py_files_in_hook_dirs(tmp_path):
    omp_hooks = tmp_path / ".omp" / "hooks"
    claude_hooks = tmp_path / ".claude" / "hooks"
    omp_hooks.mkdir(parents=True)
    claude_hooks.mkdir(parents=True)

    file_one = omp_hooks / "one.py"
    file_two = claude_hooks / "two.py"
    ignored = omp_hooks / "ignore.txt"

    file_one.write_text("x = 1", encoding="utf-8")
    file_two.write_text("x = 2", encoding="utf-8")
    ignored.write_text("nope", encoding="utf-8")

    discovered = discover_hooks(tmp_path)

    assert file_one in discovered
    assert file_two in discovered
    assert ignored not in discovered


def test_discover_hooks_returns_empty_for_missing_dirs(tmp_path):
    discovered = discover_hooks(tmp_path)

    assert discovered == []
