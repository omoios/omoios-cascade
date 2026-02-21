from unittest.mock import AsyncMock, MagicMock

import pytest

from harness.agents.base import BaseAgent
from harness.events import EventBus
from harness.models.agent import AgentConfig, AgentRole


def _text_block(text: str) -> object:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _tool_use_block(name: str, input_data: dict, tool_use_id: str = "tu_1") -> object:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_data
    block.id = tool_use_id
    return block


def _response(content: list[object], stop_reason: str = "end_turn") -> object:
    response = MagicMock()
    response.content = content
    response.stop_reason = stop_reason
    response.usage = MagicMock()
    response.usage.input_tokens = 1
    response.usage.output_tokens = 1
    return response


def _make_agent(client: AsyncMock, event_bus: EventBus | None = None) -> BaseAgent:
    config = AgentConfig(
        agent_id="ttsr-agent",
        role=AgentRole.WORKER,
        token_budget=100_000,
        timeout_seconds=120,
    )
    return BaseAgent(
        client=client,
        config=config,
        tool_handlers={"echo_tool": lambda value: {"value": value}},
        tool_schemas=[],
        event_bus=event_bus,
        system_prompt="You are helpful",
    )


@pytest.mark.asyncio
async def test_ttsr_fires_once_and_injects_start_prompt():
    client = AsyncMock()
    client.messages.create.side_effect = [_response([_text_block("done")], stop_reason="end_turn")]
    bus = EventBus()
    fired = []

    def _on_event(event):
        fired.append(event)

    bus.subscribe("ttsr_fired", _on_event)
    agent = _make_agent(client, event_bus=bus)

    await agent.run("start")

    assert agent._ttsr_fired is True
    assert len(fired) == 1
    system_prompt = client.messages.create.call_args.kwargs["system"]
    assert "Before starting, think about your approach" in system_prompt


@pytest.mark.asyncio
async def test_ttsr_injects_review_after_first_tool_result():
    client = AsyncMock()
    client.messages.create.side_effect = [
        _response([_tool_use_block("echo_tool", {"value": "x"})], stop_reason="tool_use"),
        _response([_text_block("done")], stop_reason="end_turn"),
    ]
    agent = _make_agent(client)

    await agent.run("start")

    first_system = client.messages.create.call_args_list[0].kwargs["system"]
    second_system = client.messages.create.call_args_list[1].kwargs["system"]
    assert "Before starting, think about your approach" in first_system
    assert "Review: Is your approach working? Adjust if needed." in second_system
