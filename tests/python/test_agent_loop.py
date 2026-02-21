from unittest.mock import MagicMock

from harness.agents.base import BaseAgent
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


def make_agent(
    client: MagicMock,
    tool_handlers: dict | None = None,
    token_budget: int = 100_000,
    timeout_seconds: int = 300,
) -> BaseAgent:
    config = AgentConfig(
        agent_id="test",
        role=AgentRole.WORKER,
        token_budget=token_budget,
        timeout_seconds=timeout_seconds,
    )
    return BaseAgent(
        client=client,
        config=config,
        tool_handlers=tool_handlers or {},
        tool_schemas=[],
    )


def test_loop_exits_on_end_turn():
    client = MagicMock()
    client.messages.create.side_effect = [
        make_mock_response([make_text_block("done")], stop_reason="end_turn")
    ]

    agent = make_agent(client)
    result = agent.run("start")

    assert result == "done"
    assert client.messages.create.call_count == 1


def test_loop_executes_tool_and_continues():
    client = MagicMock()
    client.messages.create.side_effect = [
        make_mock_response(
            [make_tool_use_block("echo_tool", {"value": "x"}, "tu_1")],
            stop_reason="tool_use",
        ),
        make_mock_response([make_text_block("final response")], stop_reason="end_turn"),
    ]

    def echo_tool(value: str) -> dict:
        return {"output": "echoed", "value": value}

    agent = make_agent(client, tool_handlers={"echo_tool": echo_tool})
    result = agent.run("start")

    assert result == "final response"
    assert client.messages.create.call_count == 2


def test_token_budget_enforcement():
    client = MagicMock()
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

    agent = make_agent(client, tool_handlers={"echo_tool": echo_tool}, token_budget=200)
    result = agent.run("start")

    assert result == ""
    assert agent.total_tokens == 300
    assert client.messages.create.call_count == 2


def test_timeout_enforcement():
    client = MagicMock()
    client.messages.create.side_effect = [
        make_mock_response(
            [make_tool_use_block("echo_tool", {"value": "x"})],
            stop_reason="tool_use",
        )
    ]

    def echo_tool(value: str) -> dict:
        return {"output": value}

    agent = make_agent(client, tool_handlers={"echo_tool": echo_tool}, timeout_seconds=0)
    result = agent.run("start")

    assert result == ""
    assert client.messages.create.call_count == 1


def test_tool_results_in_messages():
    client = MagicMock()
    client.messages.create.side_effect = [
        make_mock_response(
            [make_tool_use_block("echo_tool", {"value": "abc"}, "tu_9")],
            stop_reason="tool_use",
        ),
        make_mock_response([make_text_block("ok")], stop_reason="end_turn"),
    ]

    def echo_tool(value: str) -> dict:
        return {"output": "echoed"}

    agent = make_agent(client, tool_handlers={"echo_tool": echo_tool})
    agent.run("start")

    tool_result_message = agent.messages[2]
    assert tool_result_message["role"] == "user"
    assert tool_result_message["content"][0]["type"] == "tool_result"
    assert tool_result_message["content"][0]["tool_use_id"] == "tu_9"
    assert '"output": "echoed"' in tool_result_message["content"][0]["content"]


def test_unknown_tool_returns_error():
    client = MagicMock()
    client.messages.create.side_effect = [
        make_mock_response(
            [make_tool_use_block("nonexistent_tool", {"arg": "x"}, "tu_5")],
            stop_reason="tool_use",
        ),
        make_mock_response([make_text_block("done")], stop_reason="end_turn"),
    ]

    agent = make_agent(client)
    agent.run("start")

    tool_result_message = agent.messages[2]
    assert "Unknown tool: nonexistent_tool" in tool_result_message["content"][0]["content"]


def test_messages_alternate_user_assistant_roles():
    client = MagicMock()
    client.messages.create.side_effect = [
        make_mock_response(
            [make_tool_use_block("echo_tool", {"value": "x"}, "tu_1")],
            stop_reason="tool_use",
        ),
        make_mock_response([make_text_block("done")], stop_reason="end_turn"),
    ]

    def echo_tool(value: str) -> dict:
        return {"output": value}

    agent = make_agent(client, tool_handlers={"echo_tool": echo_tool})
    agent.run("start")

    roles = [message["role"] for message in agent.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
