import asyncio
import json
import time
from typing import Any, Callable

from harness.agents.base import BaseAgent
from harness.models.agent import AgentConfig
from harness.orchestration.idempotency import CompletionGate, IdempotencyGuard
from harness.orchestration.scheduler import Scheduler

PLANNER_FORBIDDEN_TOOLS = {"bash", "write_file", "edit_file"}


class PlannerGuard:
    def __init__(self, forbidden_tools: set[str] | None = None):
        self.forbidden = forbidden_tools or PLANNER_FORBIDDEN_TOOLS

    def check(self, tool_name: str) -> bool:
        return tool_name not in self.forbidden


class RootPlanner(BaseAgent):
    def __init__(
        self,
        client: Any,
        config: AgentConfig,
        tool_handlers: dict[str, Callable],
        tool_schemas: list[dict],
        event_bus=None,
        system_prompt: str = "",
        scheduler: Scheduler | None = None,
        idempotency_guard: IdempotencyGuard | None = None,
        completion_gate: CompletionGate | None = None,
        max_planner_turns: int = 50,
        max_wall_time_seconds: int = 600,
    ):
        super().__init__(
            client=client,
            config=config,
            tool_handlers=tool_handlers,
            tool_schemas=tool_schemas,
            event_bus=event_bus,
            system_prompt=system_prompt,
        )
        self.scheduler = scheduler
        self.idempotency_guard = idempotency_guard
        self.completion_gate = completion_gate
        self.guard = PlannerGuard()
        self.max_planner_turns = max_planner_turns
        self.max_wall_time_seconds = max_wall_time_seconds
        self._spawned_workers: list[str] = []
        self._reviewed_handoffs: list[str] = []
        self._requested_worker_skills: dict[str, list[str]] = {}

    async def run(self, initial_message: str = "") -> str:
        self._start_time = time.time()
        if initial_message:
            self.messages.append({"role": "user", "content": initial_message})

        last_text = ""
        while True:
            if self.is_over_limits():
                break

            await self.on_before_llm_call()
            response = await self._call_llm()
            self.total_tokens += int(getattr(response.usage, "input_tokens", 0)) + int(
                getattr(response.usage, "output_tokens", 0)
            )
            self.turn_count += 1
            self.messages.append({"role": "assistant", "content": response.content})

            text_blocks = [
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text" and hasattr(block, "text")
            ]
            if text_blocks:
                last_text = "\n".join(text_blocks)

            if response.stop_reason != "tool_use":
                await self.on_loop_exit()
                return last_text

            tool_results: list[dict[str, str]] = []
            hook_results: list[dict] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                handler = self.tool_handlers.get(block.name)
                if handler:
                    result = handler(**block.input)
                    if asyncio.iscoroutine(result):
                        result = await result
                else:
                    result = {"error": f"Unknown tool: {block.name}"}
                hook_results.append(
                    {
                        "tool_name": block.name,
                        "tool_use_id": block.id,
                        "tool_input": dict(block.input),
                        "result": result,
                    }
                )
                content = json.dumps(result) if isinstance(result, dict) else str(result)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                    }
                )

            self.messages.append({"role": "user", "content": tool_results})
            await self.on_tool_result(hook_results)

            if self.total_tokens >= self.config.token_budget:
                break
            if self._start_time is not None and (time.time() - self._start_time >= self.config.timeout_seconds):
                break

        await self.on_loop_exit()
        return last_text

    async def on_tool_result(self, results: list[dict]) -> None:
        for result in list(results):
            tool_name = result.get("tool_name", "")
            if not self.guard.check(tool_name):
                results.append(
                    {
                        "tool_name": tool_name,
                        "error": f"Planner cannot use tool: {tool_name}",
                    }
                )
                continue

            if tool_name == "spawn_worker":
                tool_input = result.get("tool_input", {})
                task_id = str(tool_input.get("task_id", "")).strip()
                skills = tool_input.get("skills", [])
                if task_id and isinstance(skills, list):
                    self._requested_worker_skills[task_id] = [
                        str(skill).strip() for skill in skills if str(skill).strip()
                    ]
        await super().on_tool_result(results)

    def can_spawn_worker(self, task_id: str) -> bool:
        if self.idempotency_guard:
            return self.idempotency_guard.can_spawn_worker(task_id)
        return True

    def spawn_worker(self, task_id: str) -> str:
        if not self.can_spawn_worker(task_id):
            raise ValueError(f"Worker already spawned for task: {task_id}")

        self._spawned_workers.append(task_id)
        if self.idempotency_guard:
            self.idempotency_guard.mark_worker_spawned(task_id)
        return f"worker-{task_id}"

    def check_completion(
        self,
        workers,
        handoffs,
        tasks,
        error_budget,
        reconciliation_passed,
    ) -> tuple[bool, list[str]]:
        if self.completion_gate:
            return self.completion_gate.declare_done(
                workers,
                handoffs,
                tasks,
                error_budget,
                reconciliation_passed,
            )
        return (True, [])

    def is_over_limits(self) -> bool:
        if self.turn_count >= self.max_planner_turns:
            return True

        if self._start_time is not None:
            if time.time() - self._start_time >= self.max_wall_time_seconds:
                return True

        return False

    def _handle_sub_planner_failure(
        self,
        sub_planner_id: str,
        completed_handoffs: list[dict] | None,
        remaining_tasks: list[str] | None,
    ) -> dict:
        merged_handoffs = completed_handoffs or []
        pending_tasks = remaining_tasks or []
        recovery_task_id = f"recovery-{sub_planner_id}-{int(time.time())}"
        recovery_task = {
            "task_id": recovery_task_id,
            "description": (
                f"Recover failed sub-planner {sub_planner_id}. "
                f"Completed handoffs: {len(merged_handoffs)}. "
                f"Remaining tasks: {', '.join(pending_tasks) if pending_tasks else 'none'}."
            ),
            "metadata": {
                "source_sub_planner": sub_planner_id,
                "completed_handoffs": merged_handoffs,
                "remaining_tasks": pending_tasks,
            },
        }

        self.messages.append(
            {
                "role": "user",
                "content": (
                    "[SUB-PLANNER FAILURE RECOVERY] "
                    f"Merged {len(merged_handoffs)} completed handoffs from {sub_planner_id}. "
                    f"Created recovery task {recovery_task_id} for remaining scope."
                ),
            }
        )

        return {
            "status": "recovered",
            "sub_planner_id": sub_planner_id,
            "merged_handoffs": merged_handoffs,
            "recovery_task": recovery_task,
        }


class SubPlanner(BaseAgent):
    def __init__(
        self,
        client: Any,
        config: AgentConfig,
        tool_handlers: dict[str, Callable],
        tool_schemas: list[dict],
        event_bus=None,
        system_prompt: str = "",
        max_depth: int = 3,
    ):
        super().__init__(
            client=client,
            config=config,
            tool_handlers=tool_handlers,
            tool_schemas=tool_schemas,
            event_bus=event_bus,
            system_prompt=system_prompt,
        )
        self.max_depth = max_depth
        self.guard = PlannerGuard()

    def can_delegate(self) -> bool:
        return self.config.depth < self.max_depth

    async def on_tool_result(self, results: list[dict]) -> None:
        for result in list(results):
            tool_name = result.get("tool_name", "")
            if not self.guard.check(tool_name):
                results.append(
                    {
                        "tool_name": tool_name,
                        "error": f"Planner cannot use tool: {tool_name}",
                    }
                )
        await super().on_tool_result(results)
