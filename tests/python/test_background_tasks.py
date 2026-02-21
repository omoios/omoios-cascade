import asyncio

import pytest

from harness.tools.worker_tools import (
    _background_results,
    _background_tasks,
    background_task_handler,
    check_background_handler,
)


@pytest.fixture(autouse=True)
def clear_background_state():
    _background_tasks.clear()
    _background_results.clear()


async def _wait_for_terminal_result(task_id: str, attempts: int = 20, delay: float = 0.1) -> dict:
    for _ in range(attempts):
        result = await check_background_handler(task_id=task_id)
        if result.get("status") != "running":
            return result
        await asyncio.sleep(delay)
    return {"status": "running"}


@pytest.mark.asyncio
async def test_background_task_handler_spawns_and_returns_task_id(tmp_path):
    result = await background_task_handler(
        description="echo test",
        command="echo hello",
        workspace_path=str(tmp_path),
    )

    assert result["status"] == "running"
    assert result["task_id"].startswith("bg_")


@pytest.mark.asyncio
async def test_check_background_handler_returns_running_for_active_task(tmp_path):
    spawned = await background_task_handler(
        description="sleep",
        command="sleep 1",
        workspace_path=str(tmp_path),
    )

    result = await check_background_handler(task_id=spawned["task_id"])
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_check_background_handler_returns_completed_after_finish(tmp_path):
    spawned = await background_task_handler(
        description="echo",
        command="echo done",
        workspace_path=str(tmp_path),
    )

    result = await _wait_for_terminal_result(spawned["task_id"])
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert "done" in result["stdout"]


@pytest.mark.asyncio
async def test_background_task_handler_timeout_handling(tmp_path):
    spawned = await background_task_handler(
        description="timeout",
        command="sleep 2",
        workspace_path=str(tmp_path),
        timeout=1,
    )

    result = await _wait_for_terminal_result(spawned["task_id"], attempts=30, delay=0.1)
    assert result["status"] == "timeout"
    assert result["exit_code"] == -1
    assert "Timed out" in result["stderr"]


@pytest.mark.asyncio
async def test_check_background_handler_returns_not_found_for_unknown_task_id():
    result = await check_background_handler(task_id="bg_unknown")
    assert result["status"] == "not_found"
    assert "Unknown task_id" in result["error"]
