from unittest.mock import MagicMock

from harness.agents.planner import PlannerGuard, RootPlanner, SubPlanner
from harness.models.agent import AgentConfig, AgentRole
from harness.models.error_budget import ErrorBudget
from harness.models.task import Task
from harness.orchestration.idempotency import CompletionGate


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


def make_root_planner(client: MagicMock, max_planner_turns: int = 50) -> RootPlanner:
    config = AgentConfig(
        agent_id="root",
        role=AgentRole.ROOT_PLANNER,
        token_budget=100_000,
        timeout_seconds=300,
    )
    return RootPlanner(
        client=client,
        config=config,
        tool_handlers={"spawn_worker": lambda task_id: {"status": "ok", "task_id": task_id}},
        tool_schemas=[],
        max_planner_turns=max_planner_turns,
    )


def make_sub_planner(depth: int, max_depth: int) -> SubPlanner:
    config = AgentConfig(
        agent_id="sub",
        role=AgentRole.SUB_PLANNER,
        depth=depth,
        token_budget=100_000,
        timeout_seconds=300,
    )
    return SubPlanner(
        client=MagicMock(),
        config=config,
        tool_handlers={},
        tool_schemas=[],
        max_depth=max_depth,
    )


class TestPlannerGuard:
    def test_planner_cannot_use_bash(self):
        guard = PlannerGuard()
        assert guard.check("bash") is False

    def test_planner_cannot_use_write(self):
        guard = PlannerGuard()
        assert guard.check("write_file") is False

    def test_planner_cannot_use_edit(self):
        guard = PlannerGuard()
        assert guard.check("edit_file") is False

    def test_planner_can_use_spawn_worker(self):
        guard = PlannerGuard()
        assert guard.check("spawn_worker") is True


class TestRootPlanner:
    def test_spawns_worker_for_task(self):
        planner = make_root_planner(MagicMock())
        worker_id = planner.spawn_worker("t1")
        assert worker_id == "worker-t1"

    def test_planner_loop_bounds_max_turns(self):
        client = MagicMock()
        client.messages.create.side_effect = [
            make_mock_response(
                [make_tool_use_block("spawn_worker", {"task_id": "t1"}, "tu_1")],
                stop_reason="tool_use",
            ),
            make_mock_response(
                [make_tool_use_block("spawn_worker", {"task_id": "t2"}, "tu_2")],
                stop_reason="tool_use",
            ),
        ]
        planner = make_root_planner(client, max_planner_turns=1)

        planner.run("start")

        assert planner.turn_count == 1
        assert client.messages.create.call_count == 1

    def test_completion_gate_blocks_premature(self):
        planner = make_root_planner(MagicMock())
        planner.completion_gate = CompletionGate()
        pending_task = Task(id="t1", title="Task 1", description="pending")

        done, failures = planner.check_completion(
            workers=[],
            handoffs=[],
            tasks=[pending_task],
            error_budget=ErrorBudget(),
            reconciliation_passed=True,
        )

        assert done is False
        assert "all_tasks_terminal" in failures


class TestSubPlanner:
    def test_sub_planner_respects_depth_limit(self):
        planner = make_sub_planner(depth=3, max_depth=3)
        assert planner.can_delegate() is False
