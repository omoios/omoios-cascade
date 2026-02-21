from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harness.config import HarnessConfig, LLMConfig, WorkspaceConfig
from harness.runner import HarnessRunner

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def make_text_block(text: str) -> object:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def make_tool_use_block(name: str, input_dict: dict) -> object:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_dict
    block.id = f"call_{name}"
    return block


def make_response(blocks: list, stop_reason: str) -> object:
    response = MagicMock()
    response.content = blocks
    response.stop_reason = stop_reason
    response.usage = MagicMock(input_tokens=100, output_tokens=50)
    return response


def make_config(tmp_path: Path) -> HarnessConfig:
    return HarnessConfig(
        llm=LLMConfig(api_key="test-key"),
        workspace=WorkspaceConfig(
            root_dir=str(tmp_path / ".workspaces"),
            canonical_dir=str(tmp_path),
            cleanup_on_success=True,
            retain_count=5,
        ),
        repos=[str(tmp_path)],
    )


def test_runner_init(tmp_path):
    config = make_config(tmp_path)
    runner = HarnessRunner(config)
    assert runner.config is config


def test_runner_creates_scratchpad(tmp_path):
    runner = HarnessRunner(make_config(tmp_path))
    assert runner.scratchpad is not None


def test_runner_creates_event_bus(tmp_path):
    runner = HarnessRunner(make_config(tmp_path))
    assert runner.event_bus is not None


def test_runner_creates_error_budget(tmp_path):
    runner = HarnessRunner(make_config(tmp_path))
    assert runner.error_budget is not None


def test_runner_creates_completion_gate(tmp_path):
    runner = HarnessRunner(make_config(tmp_path))
    assert runner.completion_gate is not None


@pytest.mark.asyncio
async def test_runner_handles_empty_instructions(tmp_path):
    runner = HarnessRunner(make_config(tmp_path))

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=make_response([make_text_block("No instructions provided.")], "end_turn")
    )

    with patch.object(runner, "_make_client", return_value=mock_client):
        result = await runner.run("")

    assert result == "No instructions provided."


@pytest.mark.asyncio
async def test_runner_planner_gets_system_prompt(tmp_path):
    runner = HarnessRunner(make_config(tmp_path))

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=make_response([make_text_block("done")], "end_turn"))

    with patch.object(runner, "_make_client", return_value=mock_client):
        await runner.run("Do a tiny run")

    kwargs = mock_client.messages.create.call_args.kwargs
    assert "system" in kwargs
    assert "Root Planner" in kwargs["system"]


@pytest.mark.asyncio
async def test_runner_prunes_workspaces(tmp_path, tmp_git_repo):
    workspace_root = tmp_path / ".workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)

    for idx in range(6):
        entry = workspace_root / f"worker-{idx}"
        entry.mkdir()

    config = HarnessConfig(
        llm=LLMConfig(api_key="test-key"),
        workspace=WorkspaceConfig(
            root_dir=str(workspace_root),
            canonical_dir=str(tmp_path),
            cleanup_on_success=True,
            retain_count=2,
        ),
        repos=[str(tmp_git_repo)],
    )
    runner = HarnessRunner(config)

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=make_response([make_text_block("done")], "end_turn"))

    with patch.object(runner, "_make_client", return_value=mock_client):
        await runner.run("prune")

    remaining = [p for p in workspace_root.iterdir() if p.is_dir()]
    assert len(remaining) == 2
