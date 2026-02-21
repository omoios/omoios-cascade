from unittest.mock import AsyncMock

import pytest

from harness.agents.base import BaseAgent
from harness.config import FreshnessConfig
from harness.models.agent import AgentConfig, AgentRole


def make_agent() -> BaseAgent:
    config = AgentConfig(
        agent_id="freshness-test",
        role=AgentRole.WORKER,
        token_budget=100_000,
        timeout_seconds=300,
    )
    return BaseAgent(
        client=AsyncMock(),
        config=config,
        tool_handlers={},
        tool_schemas=[],
    )


@pytest.mark.asyncio
async def test_self_reflection_injected_at_interval():
    agent = make_agent()
    agent.turn_count = 10
    agent._reflection_interval = 10
    agent.messages = [{"role": "user", "content": "start"}]

    await agent.on_before_llm_call()

    assert "[SELF-REFLECTION]" in agent.messages[-1]["content"]


@pytest.mark.asyncio
async def test_identity_reinjected_after_compression(monkeypatch):
    agent = make_agent()
    agent._identity_text = "You are a Worker"
    agent.messages = [
        {"role": "user", "content": "m1"},
        {"role": "assistant", "content": "m2"},
        {"role": "user", "content": "m3"},
        {"role": "assistant", "content": "m4"},
        {"role": "user", "content": "m5"},
        {"role": "assistant", "content": "m6"},
        {"role": "user", "content": "m7"},
    ]

    monkeypatch.setattr("harness.orchestration.compression.estimate_tokens", lambda _messages: 200_000)
    monkeypatch.setattr(
        "harness.orchestration.compression.microcompact",
        lambda _messages, keep_recent=3: [{"role": "assistant", "content": "compacted"}],
    )

    await agent.on_before_llm_call()

    assert agent.messages[0]["content"].startswith("[IDENTITY REMINDER]")


@pytest.mark.asyncio
async def test_alignment_reminder_after_compression(monkeypatch):
    agent = make_agent()
    agent._alignment_text = "Stay aligned"
    agent.messages = [
        {"role": "user", "content": "m1"},
        {"role": "assistant", "content": "m2"},
        {"role": "user", "content": "m3"},
        {"role": "assistant", "content": "m4"},
        {"role": "user", "content": "m5"},
        {"role": "assistant", "content": "m6"},
        {"role": "user", "content": "m7"},
    ]

    monkeypatch.setattr("harness.orchestration.compression.estimate_tokens", lambda _messages: 200_000)
    monkeypatch.setattr(
        "harness.orchestration.compression.microcompact",
        lambda _messages, keep_recent=3: [{"role": "assistant", "content": "compacted"}],
    )

    await agent.on_before_llm_call()

    assert agent.messages[-1]["content"].startswith("[ALIGNMENT]")


@pytest.mark.asyncio
async def test_pivot_message_at_three_failures():
    agent = make_agent()

    for _ in range(3):
        await agent.on_tool_result([{"tool_name": "bash", "result": {"error": "failed"}}])

    assert "[PIVOT]" in agent.messages[-1]["content"]


@pytest.mark.asyncio
async def test_hard_stop_message_at_five_failures():
    agent = make_agent()

    for _ in range(5):
        await agent.on_tool_result([{"tool_name": "bash", "result": {"error": "failed"}}])

    assert "[HARD STOP]" in agent.messages[-1]["content"]


@pytest.mark.asyncio
async def test_failure_counter_resets_on_success():
    agent = make_agent()

    for _ in range(2):
        await agent.on_tool_result([{"tool_name": "read_file", "result": {"error": "failed"}}])
    await agent.on_tool_result([{"tool_name": "read_file", "result": {"content": "ok"}}])

    assert agent._consecutive_failures["read_file"] == 0


def test_freshness_config_defaults():
    config = FreshnessConfig()

    assert config.self_reflection_interval == 10
    assert config.pivot_threshold == 3
    assert config.hard_stop_threshold == 5
