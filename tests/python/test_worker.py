import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from harness.agents.worker import Worker
from harness.models.agent import AgentConfig, AgentRole


def make_text_block(text: str) -> object:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def make_tool_use_block(name: str, input: dict, tool_use_id: str = "tu_1") -> object:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input
    block.id = tool_use_id
    return block


def make_mock_response(
    content: list,
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> object:
    response = MagicMock()
    response.content = content
    response.stop_reason = stop_reason
    response.usage = MagicMock()
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    return response


def make_worker(
    client: MagicMock,
    workspace_root: str,
    tool_handlers: dict | None = None,
    token_budget: int = 100_000,
) -> Worker:
    config = AgentConfig(
        agent_id="w1",
        role=AgentRole.WORKER,
        task_id="t1",
        token_budget=token_budget,
    )
    return Worker(
        client=client,
        config=config,
        tool_handlers=tool_handlers or {},
        tool_schemas=[],
        workspace_root=workspace_root,
    )


class TestWorker:
    @pytest.mark.asyncio
    async def test_worker_creates_workspace(self, tmp_path):
        client = AsyncMock()
        worker = make_worker(client=client, workspace_root=str(tmp_path))

        workspace_path = await worker.setup_workspace()

        assert os.path.isdir(workspace_path)

    @pytest.mark.asyncio
    async def test_worker_tools_operate_in_workspace(self, tmp_path):
        client = AsyncMock()
        worker = make_worker(client=client, workspace_root=str(tmp_path))

        workspace_path = await worker.setup_workspace()

        assert worker.workspace_path == workspace_path

    @pytest.mark.asyncio
    async def test_worker_tracks_file_diffs(self, tmp_path):
        client = AsyncMock()
        worker = make_worker(client=client, workspace_root=str(tmp_path))
        workspace_path = await worker.setup_workspace()

        new_file = os.path.join(workspace_path, "new_file.txt")
        with open(new_file, "w", encoding="utf-8") as f:
            f.write("hello")

        diffs = await worker.get_file_diffs()

        assert len(diffs) == 1
        assert diffs[0]["path"] == "new_file.txt"
        assert diffs[0]["before"] is None
        assert diffs[0]["after"] == "hello"

    @pytest.mark.asyncio
    async def test_worker_auto_submits_handoff_on_exit(self, tmp_path):
        client = AsyncMock()
        client.messages.create.side_effect = [make_mock_response([make_text_block("done")], stop_reason="end_turn")]
        worker = make_worker(client=client, workspace_root=str(tmp_path))

        await worker.run("start")

        assert worker.handoff is not None
        assert worker.handoff["worker_id"] == "w1"
        assert worker.handoff["status"] == "completed"

    @pytest.mark.asyncio
    async def test_worker_respects_token_budget(self, tmp_path):
        client = AsyncMock()
        client.messages.create.side_effect = [
            make_mock_response(
                [make_tool_use_block("echo_tool", {"value": "x"}, "tu_1")],
                stop_reason="tool_use",
                input_tokens=100,
                output_tokens=50,
            ),
            make_mock_response(
                [make_tool_use_block("echo_tool", {"value": "x"}, "tu_2")],
                stop_reason="tool_use",
                input_tokens=100,
                output_tokens=50,
            ),
        ]

        def echo_tool(value: str) -> dict:
            return {"output": value}

        worker = make_worker(
            client=client,
            workspace_root=str(tmp_path),
            tool_handlers={"echo_tool": echo_tool},
            token_budget=200,
        )

        await worker.run("start")

        assert worker.total_tokens == 300
        assert client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_worker_cleanup_removes_workspace(self, tmp_path):
        client = AsyncMock()
        worker = make_worker(client=client, workspace_root=str(tmp_path))
        workspace_path = await worker.setup_workspace()

        worker.cleanup()

        assert not os.path.exists(workspace_path)
