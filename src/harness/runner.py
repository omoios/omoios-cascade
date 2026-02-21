from __future__ import annotations

import asyncio
import uuid
from functools import partial
from pathlib import Path
from typing import Any, Callable

from harness.agents.planner import RootPlanner
from harness.agents.watchdog import Watchdog
from harness.agents.worker import Worker
from harness.config import HarnessConfig
from harness.events import EventBus, WorkerSpawned
from harness.models.agent import AgentConfig, AgentRole
from harness.models.error_budget import ErrorBudget
from harness.models.task import Task, TaskStatus
from harness.orchestration.idempotency import CompletionGate
from harness.orchestration.scratchpad import Scratchpad
from harness.orchestration.shutdown import ShutdownHandler
from harness.rendering import RichRenderer
from harness.tools.worker_tools import (
    ask_handler,
    bash_handler,
    edit_file_handler,
    find_files_handler,
    grep_handler,
    read_file_handler,
    submit_handoff_handler,
    todo_write_handler,
    write_file_handler,
)

PLANNER_SYSTEM_PROMPT = (
    "You are a planner in a multi-agent orchestration harness. "
    "You delegate work to workers — you never edit files yourself.\n\n"
    "MANDATORY WORKFLOW (follow every step):\n"
    "1. Write initial scratchpad via rewrite_scratchpad with your plan.\n"
    "2. Create tasks via create_task (one per unit of work).\n"
    "3. Spawn a worker for each task via spawn_worker.\n"
    "4. After spawning, call review_handoff with the task_id to wait for "
    "the worker to finish and get its handoff.\n"
    "5. CRITICAL: After reviewing, you MUST call accept_handoff (if work "
    "looks good) or reject_handoff (if it needs redo). This marks the "
    "task complete on the board. Skipping this leaves tasks unfinished.\n"
    "6. Update scratchpad after each accept/reject.\n"
    "7. When ALL tasks are accepted, summarize results and stop.\n\n"
    "Required scratchpad sections: ## Goal, ## Active Workers, "
    "## Pending Handoffs, ## Error Budget, ## Blockers, ## Next Action\n\n"
    "Rules:\n"
    "- You CANNOT use bash, write_file, or edit_file.\n"
    "- Every spawned worker MUST be reviewed and accepted/rejected.\n"
    "- Use blocked_by in create_task when ordering matters.\n"
    "- Check error budget via get_error_budget if errors occur.\n"
)

WORKER_SYSTEM_PROMPT = (
    "You are a Worker agent in a multi-agent orchestration harness.\n\n"
    "Your task will be specified below. Execute it completely.\n\n"
    "Tools available: bash, read_file, write_file, edit_file, grep, find_files, todo_write, submit_handoff.\n\n"
    "Constraints:\n"
    "- NEVER decompose work into subtasks or spawn other agents.\n"
    "- NEVER modify files outside your assigned workspace.\n"
    "- NEVER skip testing your changes.\n"
    "- ALWAYS submit a handoff via submit_handoff when your work is complete.\n"
    "- Do NOT ask for clarification unless the task is truly ambiguous.\n"
    "- Do NOT plan beyond your delegated scope.\n"
)

SUB_PLANNER_SYSTEM_PROMPT = (
    "You are a Sub-Planner in a multi-agent orchestration harness.\n\n"
    "You handle a scoped subset of work delegated by the Root Planner.\n\n"
    "Constraints:\n"
    "- NEVER plan beyond your delegated scope.\n"
    "- NEVER write code or make file changes.\n"
    "- ALWAYS report progress to the root planner.\n"
    "- Do NOT spawn sub-planners of your own unless depth allows.\n"
)

WATCHDOG_SYSTEM_PROMPT = (
    "You are a Watchdog agent monitoring worker health.\n\nYou detect failure modes and recommend interventions.\n"
)

WORKER_TOOL_SCHEMAS = [
    {
        "name": "bash",
        "description": "Run a shell command in the worker workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file content from workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write file content to workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Find and replace text in a workspace file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "submit_handoff",
        "description": "Submit a structured handoff when work is complete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "task_id": {"type": "string"},
                "status": {"type": "string"},
                "narrative": {"type": "string"},
            },
            "required": ["agent_id", "task_id", "status", "narrative"],
        },
    },
    {
        "name": "grep",
        "description": "Search file contents using regex pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Relative path to search in"},
                "include": {"type": "string", "description": "File pattern filter (e.g., *.py)"},
                "context_lines": {"type": "integer", "description": "Lines of context around matches"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "find_files",
        "description": "Find files in workspace by glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match files"},
                "max_results": {"type": "integer", "description": "Maximum number of files to return"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "todo_write",
        "description": "Write and validate a structured todo list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "List of todo items",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                        },
                        "required": ["content", "status", "priority"],
                    },
                }
            },
            "required": ["todos"],
        },
    },
    {
        "name": "ask",
        "description": "Ask a clarification question back to planner.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question to ask the planner"},
                "options": {
                    "type": "array",
                    "description": "Optional response choices",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["label", "value"],
                    },
                },
            },
            "required": ["question"],
        },
    },
]

PLANNER_TOOL_SCHEMAS = [
    {
        "name": "create_task",
        "description": "Create a task on the task board.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Unique task identifier"},
                "description": {"type": "string", "description": "What the task should accomplish"},
                "blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task IDs this depends on",
                },
            },
            "required": ["task_id", "description"],
        },
    },
    {
        "name": "spawn_worker",
        "description": "Spawn a worker to execute a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to assign"},
                "task": {"type": "string", "description": "Instructions for the worker"},
            },
            "required": ["task_id", "task"],
        },
    },
    {
        "name": "review_handoff",
        "description": "Review a completed worker's handoff.",
        "input_schema": {
            "type": "object",
            "properties": {
                "handoff_id": {"type": "string", "description": "The task_id / worker_id"},
            },
            "required": ["handoff_id"],
        },
    },
    {
        "name": "accept_handoff",
        "description": "Accept a reviewed handoff and mark the task complete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "handoff_id": {"type": "string"},
            },
            "required": ["handoff_id"],
        },
    },
    {
        "name": "reject_handoff",
        "description": "Reject a handoff and requeue the task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "handoff_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["handoff_id"],
        },
    },
    {
        "name": "rewrite_scratchpad",
        "description": (
            "Rewrite the planner scratchpad. Required sections: "
            "## Goal, ## Active Workers, ## Pending Handoffs, "
            "## Error Budget, ## Blockers, ## Next Action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "read_scratchpad",
        "description": "Read the current scratchpad content.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_error_budget",
        "description": "Get the current error budget status.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


class _ClientProxy:
    def __init__(self, real_client: Any, model: str, max_tokens: int):
        self._client = real_client
        self._model = model
        self._max_tokens = max_tokens

    @property
    def messages(self):
        return _MessagesProxy(self._client, self._model, self._max_tokens)


class _MessagesProxy:
    def __init__(self, client: Any, model: str, max_tokens: int):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    async def create(self, **kwargs: Any) -> Any:
        kwargs["model"] = self._model
        kwargs["max_tokens"] = self._max_tokens
        return await self._client.messages.create(**kwargs)


class HarnessRunner:
    def __init__(self, config: HarnessConfig):
        self.config = config
        self.event_bus = EventBus()
        self.renderer = RichRenderer(event_bus=self.event_bus)
        self.error_budget = ErrorBudget(
            threshold=config.errors.budget_percentage,
            window_size=config.errors.window_size,
        )
        self.scratchpad = Scratchpad()
        self.completion_gate = CompletionGate()
        self.shutdown_handler = ShutdownHandler()
        self.watchdog = Watchdog(config=config.watchdog, event_bus=self.event_bus)

        self._tasks: dict[str, Task] = {}
        self._workers: dict[str, Worker] = {}
        self._async_tasks: dict[str, asyncio.Task] = {}
        self._handoffs: dict[str, dict] = {}
        self._base_snapshots: dict[str, dict[str, str]] = {}
        self._prompt_texts = self._load_prompts()

    def _load_prompt_file(self, filename: str, fallback: str) -> str:
        prompt_path = Path(__file__).resolve().parent / "prompts" / filename
        if not prompt_path.exists():
            return fallback
        return prompt_path.read_text(encoding="utf-8").strip()

    def _load_prompts(self) -> dict[str, str]:
        return {
            "planner": self._load_prompt_file("planner.md", PLANNER_SYSTEM_PROMPT),
            "worker": self._load_prompt_file("worker.md", WORKER_SYSTEM_PROMPT),
            "sub_planner": self._load_prompt_file("sub_planner.md", SUB_PLANNER_SYSTEM_PROMPT),
            "watchdog": self._load_prompt_file("watchdog.md", WATCHDOG_SYSTEM_PROMPT),
        }

    def _on_shutdown(self) -> None:
        try:
            from harness.orchestration.shutdown import HarnessCheckpoint, checkpoint

            state = HarnessCheckpoint(
                task_states={task_id: task.status.value for task_id, task in self._tasks.items()},
                worker_states={
                    task_id: "running"
                    if (self._async_tasks.get(task_id) and not self._async_tasks[task_id].done())
                    else "stopped"
                    for task_id in self._workers
                },
                error_budget_snapshot={
                    "failures": self.error_budget.failed_tasks,
                    "total": self.error_budget.total_tasks,
                    "zone": self.error_budget.zone.value,
                },
                scratchpad_content={"planner": self.scratchpad.read("planner") or ""},
                metadata={"config_model": self.config.llm.model},
            )
            checkpoint_path = ".harness-checkpoint.json"
            if self.config.repos:
                import os

                checkpoint_path = os.path.join(self.config.repos[0], ".harness-checkpoint.json")
            checkpoint(state, checkpoint_path)
        except Exception:
            pass

    def _make_client(self) -> _ClientProxy:
        import anthropic

        kwargs: dict[str, Any] = {"api_key": self.config.llm.api_key}
        if self.config.llm.base_url:
            kwargs["base_url"] = self.config.llm.base_url
        real_client = anthropic.AsyncAnthropic(**kwargs)
        return _ClientProxy(real_client, self.config.llm.model, self.config.llm.max_tokens)

    def _handle_create_task(self, task_id: str, description: str, blocked_by: list[str] | None = None) -> dict:
        task = Task(id=task_id, title=task_id, description=description, blocked_by=blocked_by or [])
        self._tasks[task_id] = task
        return {"status": "created", "task_id": task_id, "description": description}

    async def _handle_spawn_worker(self, task_id: str, task: str = "") -> dict:
        if task_id in self._workers:
            return {"error": f"Worker already spawned for task: {task_id}"}

        stored_task = self._tasks.get(task_id)
        if stored_task:
            stored_task.status = TaskStatus.IN_PROGRESS
            stored_task.assigned_to = f"worker-{task_id}"

        worker_id = f"worker-{task_id}"
        repo = self.config.repos[0] if self.config.repos else None
        if repo:
            from harness.git.workspace import snapshot_workspace

            self._base_snapshots[task_id] = await asyncio.to_thread(snapshot_workspace, repo)

        client = self._make_client()
        worker_config = AgentConfig(
            agent_id=worker_id,
            role=AgentRole.WORKER,
            task_id=task_id,
            repo=repo,
            token_budget=self.config.agents.worker_token_budget,
            timeout_seconds=self.config.agents.worker_timeout_seconds,
        )

        workspace_root = self.config.workspace.root_dir
        worker_tool_handlers = self._make_worker_tool_handlers(workspace_root, worker_id)

        worker = Worker(
            client=client,
            config=worker_config,
            tool_handlers=worker_tool_handlers,
            tool_schemas=WORKER_TOOL_SCHEMAS,
            event_bus=self.event_bus,
            system_prompt=(
                f"{self._prompt_texts['worker']}\n\n"
                f"Task: {task or (stored_task.description if stored_task else task_id)}"
            ),
            workspace_root=workspace_root,
            scratchpad=Scratchpad(),
            watchdog=self.watchdog,
        )
        worker._identity_text = "You are a Worker. Execute the assigned task. Do NOT decompose or spawn."
        worker._alignment_text = "Remember: you are a Worker. Execute the task. Do not plan or decompose."
        worker._reflection_interval = self.config.freshness.self_reflection_interval
        worker._pivot_threshold = self.config.freshness.pivot_threshold
        worker._hard_stop_threshold = self.config.freshness.hard_stop_threshold

        self._workers[task_id] = worker

        async def _run_worker() -> None:
            try:
                await worker.setup_workspace()
                await worker.run(f"Execute task: {task or (stored_task.description if stored_task else task_id)}")
            except Exception as exc:
                self._handoffs[task_id] = {
                    "worker_id": worker_id,
                    "task_id": task_id,
                    "status": "failed",
                    "narrative": f"Worker crashed: {exc}",
                    "diffs": [],
                }
            finally:
                if worker.handoff:
                    self._handoffs[task_id] = worker.handoff

        async_task = asyncio.create_task(_run_worker(), name=worker_id)
        self._async_tasks[task_id] = async_task

        await self.event_bus.emit(WorkerSpawned(agent_id=worker_id, task_id=task_id))

        return {"status": "spawned", "worker_id": worker_id, "task_id": task_id}

    async def _handle_review_handoff(self, handoff_id: str) -> dict:
        atask = self._async_tasks.get(handoff_id)
        if atask and not atask.done():
            try:
                await asyncio.wait_for(asyncio.shield(atask), timeout=30)
            except (asyncio.TimeoutError, Exception):
                pass

        alerts = await self.watchdog.check_agents()

        handoff = self._handoffs.get(handoff_id)
        if handoff:
            result: dict[str, Any] = {"status": "ready", "handoff": handoff}
            if alerts:
                result["watchdog_alerts"] = [
                    {
                        "agent_id": alert.agent_id,
                        "failure_mode": alert.failure_mode.value,
                        "evidence": alert.evidence,
                    }
                    for alert in alerts
                ]
            return result
        if atask and not atask.done():
            return {"status": "worker_still_running", "handoff_id": handoff_id}
        return {"status": "no_handoff_found", "handoff_id": handoff_id}

    def _apply_diffs_to_canonical(self, handoff: dict, task_id: str = "") -> list[str]:
        import os

        diffs = handoff.get("diffs", [])
        repo = self.config.repos[0] if self.config.repos else None
        if not repo or not diffs:
            return []

        base_snapshot = self._base_snapshots.get(task_id, {})
        applied: list[str] = []
        conflicts: list[str] = []

        for diff in diffs:
            rel_path = diff.get("path", "")
            after = diff.get("after")
            if not rel_path:
                continue

            full_path = os.path.join(repo, rel_path)
            base_content = base_snapshot.get(rel_path)

            current_content = None
            if os.path.exists(full_path):
                with open(full_path, "r") as f:
                    current_content = f.read()

            if base_content is not None and current_content != base_content and after is not None:
                conflicts.append(rel_path)

            if after is None:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    applied.append(f"deleted {rel_path}")
            else:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(after)
                applied.append(f"wrote {rel_path}")

        if conflicts:
            applied.append(f"CONFLICTS (overwritten): {', '.join(conflicts)}")

        return applied

    def _handle_accept_handoff(self, handoff_id: str) -> dict:
        task = self._tasks.get(handoff_id)
        if task:
            task.status = TaskStatus.COMPLETED
            self.error_budget.record(success=True)
        handoff = self._handoffs.get(handoff_id, {})
        applied = self._apply_diffs_to_canonical(handoff, task_id=handoff_id)
        self._base_snapshots.pop(handoff_id, None)
        worker = self._workers.get(handoff_id)
        if worker and self.config.workspace.cleanup_on_success:
            worker.cleanup()
        return {"status": "accepted", "handoff_id": handoff_id, "files_applied": applied}

    def _handle_reject_handoff(self, handoff_id: str, reason: str = "") -> dict:
        task = self._tasks.get(handoff_id)
        if task:
            task.status = TaskStatus.PENDING
            task.assigned_to = None
            self.error_budget.record(success=False)
        worker = self._workers.get(handoff_id)
        if worker:
            worker.cleanup()
        self._workers.pop(handoff_id, None)
        self._async_tasks.pop(handoff_id, None)
        self._handoffs.pop(handoff_id, None)
        return {"status": "rejected", "handoff_id": handoff_id, "reason": reason}

    def _handle_rewrite_scratchpad(self, content: str) -> dict:
        valid, missing = self.scratchpad.validate(content)
        self.scratchpad.rewrite("planner", content)
        if not valid:
            return {"status": "written_with_warnings", "missing_sections": missing}
        return {"status": "ok"}

    def _handle_read_scratchpad(self, **_kwargs: Any) -> dict:
        content = self.scratchpad.read("planner")
        return {"status": "ok", "content": content or "(empty)"}

    def _handle_get_error_budget(self, **_kwargs: Any) -> dict:
        return {
            "status": "ok",
            "zone": self.error_budget.zone.value,
            "failures": self.error_budget.failed_tasks,
            "total": self.error_budget.total_tasks,
            "threshold": self.error_budget.budget_percentage,
        }

    def _make_worker_tool_handlers(self, workspace_root: str, worker_id: str) -> dict:
        workspace_path = f"{workspace_root}/{worker_id}"
        return {
            "bash": partial(bash_handler, workspace_path=workspace_path),
            "read_file": partial(read_file_handler, workspace_path=workspace_path),
            "write_file": partial(write_file_handler, workspace_path=workspace_path),
            "edit_file": partial(edit_file_handler, workspace_path=workspace_path),
            "grep": partial(grep_handler, workspace_path=workspace_path),
            "find_files": partial(find_files_handler, workspace_path=workspace_path),
            "todo_write": partial(todo_write_handler, workspace_path=workspace_path),
            "ask": partial(ask_handler, workspace_path=workspace_path),
            "submit_handoff": submit_handoff_handler,
        }

    def _build_planner_handlers(self) -> dict[str, Any]:
        return {
            "create_task": self._handle_create_task,
            "spawn_worker": self._handle_spawn_worker,
            "review_handoff": self._handle_review_handoff,
            "accept_handoff": self._handle_accept_handoff,
            "reject_handoff": self._handle_reject_handoff,
            "rewrite_scratchpad": self._handle_rewrite_scratchpad,
            "read_scratchpad": self._handle_read_scratchpad,
            "get_error_budget": self._handle_get_error_budget,
        }

    def _build_fixer_fn(self) -> Callable[[list[str]], Any] | None:
        repo = self.config.repos[0] if self.config.repos else None
        if not repo:
            return None

        async def fixer_fn(failures: list[str]) -> None:
            import os

            fixer_id = f"fixer-{uuid.uuid4().hex[:8]}"
            failure_summary = "\n".join(failures[:20])

            client = self._make_client()
            fixer_config = AgentConfig(
                agent_id=fixer_id,
                role=AgentRole.WORKER,
                task_id=f"fix-{fixer_id}",
                repo=repo,
                token_budget=self.config.agents.worker_token_budget,
                timeout_seconds=self.config.agents.worker_timeout_seconds,
            )

            tool_handlers = {
                "bash": partial(bash_handler, workspace_path=repo),
                "read_file": partial(read_file_handler, workspace_path=repo),
                "write_file": partial(write_file_handler, workspace_path=repo),
                "edit_file": partial(edit_file_handler, workspace_path=repo),
                "grep": partial(grep_handler, workspace_path=repo),
                "find_files": partial(find_files_handler, workspace_path=repo),
                "todo_write": partial(todo_write_handler, workspace_path=repo),
                "ask": partial(ask_handler, workspace_path=repo),
                "submit_handoff": submit_handoff_handler,
            }

            fixer = Worker(
                client=client,
                config=fixer_config,
                tool_handlers=tool_handlers,
                tool_schemas=WORKER_TOOL_SCHEMAS,
                event_bus=self.event_bus,
                system_prompt=(
                    f"You are a fixer agent. The test command failed with these errors:\n"
                    f"{failure_summary}\n\n"
                    f"Fix the code in the current directory so the tests pass. "
                    f"Read the failing files, understand the errors, and edit to fix. "
                    f"When done, submit your work via submit_handoff."
                ),
                workspace_root=os.path.dirname(repo),
                scratchpad=Scratchpad(),
            )

            await fixer.run(f"Fix these test failures:\n{failure_summary}")

        return fixer_fn

    def _prune_workspaces(self) -> None:
        import os
        import shutil

        root = self.config.workspace.root_dir
        retain = self.config.workspace.retain_count
        if retain == 0 or not os.path.isdir(root):
            return

        entries = []
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if os.path.isdir(path):
                entries.append((os.path.getmtime(path), path))

        entries.sort(reverse=True)
        for _mtime, path in entries[retain:]:
            shutil.rmtree(path, ignore_errors=True)

    async def run(self, instructions: str) -> str:
        self.shutdown_handler.register()
        self.shutdown_handler.add_callback(self._on_shutdown)

        client = self._make_client()

        planner_config = AgentConfig(
            agent_id=f"root-planner-{uuid.uuid4().hex[:8]}",
            role=AgentRole.ROOT_PLANNER,
            token_budget=200_000,
            timeout_seconds=600,
        )

        planner = RootPlanner(
            client=client,
            config=planner_config,
            tool_handlers=self._build_planner_handlers(),
            tool_schemas=PLANNER_TOOL_SCHEMAS,
            event_bus=self.event_bus,
            system_prompt=self._prompt_texts["planner"],
            completion_gate=self.completion_gate,
            max_planner_turns=50,
            max_wall_time_seconds=600,
        )
        planner._identity_text = "You are a Planner. Decompose and delegate. NEVER write code."
        planner._alignment_text = "Remember: you are a Planner. Decompose and delegate. Never write code."
        planner._reflection_interval = self.config.freshness.self_reflection_interval
        planner._pivot_threshold = self.config.freshness.pivot_threshold
        planner._hard_stop_threshold = self.config.freshness.hard_stop_threshold

        self.renderer.console.print("[bold]Harness started[/]")
        self.renderer.console.print(f"[dim]Model: {self.config.llm.model}[/]")
        self.renderer.console.print(f"[dim]Instructions: {instructions}[/]")
        self.renderer.console.print()

        result = await planner.run(instructions)

        reconciliation_report = None
        if self.config.test_command and self.config.repos:
            from harness.orchestration.reconcile import reconcile

            reconciliation_report = await reconcile(
                repo_path=self.config.repos[0],
                test_command=self.config.test_command,
                max_rounds=self.config.errors.max_reconciliation_rounds,
                spawn_fixer_fn=self._build_fixer_fn(),
            )
            self.renderer.console.print(f"[bold]Reconciliation: {reconciliation_report.final_verdict}[/]")
            self.renderer.console.print(
                f"[dim]Rounds: {reconciliation_report.rounds}, Fixes: {reconciliation_report.fixes_attempted}[/]"
            )

        for atask in self._async_tasks.values():
            if not atask.done():
                try:
                    await asyncio.wait_for(atask, timeout=60)
                except (asyncio.TimeoutError, Exception):
                    pass

        if self.config.workspace.cleanup_on_success:
            for worker in self._workers.values():
                worker.cleanup()
        self._prune_workspaces()

        self.renderer.console.print()
        self.renderer.console.print("[bold]Harness complete[/]")
        self.renderer.render_task_board(
            {
                "pending": sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING),
                "in_progress": sum(1 for t in self._tasks.values() if t.status == TaskStatus.IN_PROGRESS),
                "completed": sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED),
                "blocked": sum(1 for t in self._tasks.values() if t.status == TaskStatus.BLOCKED),
            }
        )

        return result


async def run_harness(
    instructions: str,
    config_path: str | None = None,
    repos: list[str] | None = None,
) -> str:
    import os

    from dotenv import load_dotenv

    env_path = config_path or os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)

    config = HarnessConfig()
    if repos:
        config.repos = repos

    runner = HarnessRunner(config)
    return await runner.run(instructions)
