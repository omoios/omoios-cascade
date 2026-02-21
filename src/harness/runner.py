from __future__ import annotations

import threading
import uuid
from functools import partial
from typing import Any

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
    bash_handler,
    edit_file_handler,
    read_file_handler,
    submit_handoff_handler,
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

    def create(self, **kwargs: Any) -> Any:
        kwargs["model"] = self._model
        kwargs["max_tokens"] = self._max_tokens
        return self._client.messages.create(**kwargs)


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
        self._threads: dict[str, threading.Thread] = {}
        self._handoffs: dict[str, dict] = {}

    def _on_shutdown(self) -> None:
        from harness.orchestration.shutdown import HarnessCheckpoint, checkpoint

        state = HarnessCheckpoint(
            task_states={task_id: task.status.value for task_id, task in self._tasks.items()},
            worker_states={
                task_id: "running" if (self._threads.get(task_id) and self._threads[task_id].is_alive()) else "stopped"
                for task_id in self._workers
            },
            error_budget_snapshot={
                "failures": self.error_budget.failures,
                "total": self.error_budget.total,
                "zone": self.error_budget.zone.value,
            },
            scratchpad_content={"planner": self.scratchpad.read("planner") or ""},
            metadata={"config_model": self.config.llm.model},
        )
        checkpoint(state, ".harness-checkpoint.json")

    def _make_client(self) -> _ClientProxy:
        import anthropic

        kwargs: dict[str, Any] = {"api_key": self.config.llm.api_key}
        if self.config.llm.base_url:
            kwargs["base_url"] = self.config.llm.base_url
        real_client = anthropic.Anthropic(**kwargs)
        return _ClientProxy(real_client, self.config.llm.model, self.config.llm.max_tokens)

    def _handle_create_task(self, task_id: str, description: str, blocked_by: list[str] | None = None) -> dict:
        task = Task(id=task_id, title=task_id, description=description, blocked_by=blocked_by or [])
        self._tasks[task_id] = task
        return {"status": "created", "task_id": task_id, "description": description}

    def _handle_spawn_worker(self, task_id: str, task: str = "") -> dict:
        if task_id in self._workers:
            return {"error": f"Worker already spawned for task: {task_id}"}

        stored_task = self._tasks.get(task_id)
        if stored_task:
            stored_task.status = TaskStatus.IN_PROGRESS
            stored_task.assigned_to = f"worker-{task_id}"

        worker_id = f"worker-{task_id}"
        repo = self.config.repos[0] if self.config.repos else None

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
                f"You are a worker. Complete this task: "
                f"{task or (stored_task.description if stored_task else task_id)}. "
                "Use bash, read_file, write_file, and edit_file. "
                "When done, submit your work via submit_handoff."
            ),
            workspace_root=workspace_root,
            scratchpad=Scratchpad(),
            watchdog=self.watchdog,
        )

        self._workers[task_id] = worker

        def _run_worker() -> None:
            try:
                worker.setup_workspace()
                worker.run(f"Execute task: {task or (stored_task.description if stored_task else task_id)}")
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

        thread = threading.Thread(target=_run_worker, name=worker_id, daemon=True)
        self._threads[task_id] = thread
        thread.start()

        self.event_bus.emit(WorkerSpawned(agent_id=worker_id, task_id=task_id))

        return {"status": "spawned", "worker_id": worker_id, "task_id": task_id}

    def _handle_review_handoff(self, handoff_id: str) -> dict:
        thread = self._threads.get(handoff_id)
        if thread and thread.is_alive():
            thread.join(timeout=30)

        alerts = self.watchdog.check_agents()

        handoff = self._handoffs.get(handoff_id)
        if handoff:
            result = {"status": "ready", "handoff": handoff}
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
        if thread and thread.is_alive():
            return {"status": "worker_still_running", "handoff_id": handoff_id}
        return {"status": "no_handoff_found", "handoff_id": handoff_id}

    def _apply_diffs_to_canonical(self, handoff: dict) -> list[str]:
        import os

        diffs = handoff.get("diffs", [])
        repo = self.config.repos[0] if self.config.repos else None
        if not repo or not diffs:
            return []
        applied: list[str] = []
        for diff in diffs:
            rel_path = diff.get("path", "")
            after = diff.get("after")
            if not rel_path:
                continue
            full_path = os.path.join(repo, rel_path)
            if after is None:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    applied.append(f"deleted {rel_path}")
            else:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(after)
                applied.append(f"wrote {rel_path}")
        return applied

    def _handle_accept_handoff(self, handoff_id: str) -> dict:
        task = self._tasks.get(handoff_id)
        if task:
            task.status = TaskStatus.COMPLETED
            self.error_budget.record(success=True)
        handoff = self._handoffs.get(handoff_id, {})
        applied = self._apply_diffs_to_canonical(handoff)
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
        self._threads.pop(handoff_id, None)
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
            "failures": self.error_budget.failures,
            "total": self.error_budget.total,
            "threshold": self.error_budget.threshold,
        }

    def _make_worker_tool_handlers(self, workspace_root: str, worker_id: str) -> dict:
        workspace_path = f"{workspace_root}/{worker_id}"
        return {
            "bash": partial(bash_handler, workspace_path=workspace_path),
            "read_file": partial(read_file_handler, workspace_path=workspace_path),
            "write_file": partial(write_file_handler, workspace_path=workspace_path),
            "edit_file": partial(edit_file_handler, workspace_path=workspace_path),
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

    def run(self, instructions: str) -> str:
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
            system_prompt=PLANNER_SYSTEM_PROMPT,
            completion_gate=self.completion_gate,
            max_planner_turns=50,
            max_wall_time_seconds=600,
        )

        self.renderer.console.print("[bold]Harness started[/]")
        self.renderer.console.print(f"[dim]Model: {self.config.llm.model}[/]")
        self.renderer.console.print(f"[dim]Instructions: {instructions}[/]")
        self.renderer.console.print()

        result = planner.run(instructions)

        reconciliation_report = None
        if self.config.test_command and self.config.repos:
            from harness.orchestration.reconcile import reconcile

            reconciliation_report = reconcile(
                repo_path=self.config.repos[0],
                test_command=self.config.test_command,
                max_rounds=3,
            )
            self.renderer.console.print(f"[bold]Reconciliation: {reconciliation_report.final_verdict}[/]")
            self.renderer.console.print(
                f"[dim]Rounds: {reconciliation_report.rounds}, Fixes: {reconciliation_report.fixes_attempted}[/]"
            )

        for thread in self._threads.values():
            if thread.is_alive():
                thread.join(timeout=60)

        if self.config.workspace.cleanup_on_success:
            for worker in self._workers.values():
                worker.cleanup()
        else:
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


def run_harness(
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
    return runner.run(instructions)
