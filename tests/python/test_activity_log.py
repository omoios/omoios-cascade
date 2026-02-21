import json

import pytest

from harness.observability.activity_log import ActivityLogger


@pytest.mark.asyncio
async def test_activity_logger_writes_per_agent_jsonl(tmp_path):
    logger = ActivityLogger(output_dir=str(tmp_path), run_id="run-1")
    await logger.log("agent-a", "tool_use", tool="bash", metrics={"tokens": 12})
    await logger.log("agent-a", "tool_result", tool="bash", metrics={"tokens": 24}, success=True)

    target = tmp_path / "run-1" / "agent-a.jsonl"
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["event"] == "tool_use"
    assert first["tool"] == "bash"
    assert first["agent_id"] == "agent-a"
    assert first["metrics"] == {"tokens": 12}


@pytest.mark.asyncio
async def test_activity_logger_flush_is_safe(tmp_path):
    logger = ActivityLogger(output_dir=str(tmp_path), run_id="run-2")
    await logger.log("agent-b", "shutdown", metrics={})
    await logger.flush()

    target = tmp_path / "run-2" / "agent-b.jsonl"
    assert target.exists()
