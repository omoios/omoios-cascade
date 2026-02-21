import asyncio
import os
import shutil
from typing import Any, Callable

from harness.agents.base import BaseAgent
from harness.events import WorkerCompleted
from harness.git.workspace import snapshot_workspace
from harness.models.agent import AgentConfig
from harness.orchestration.scratchpad import Scratchpad


class Worker(BaseAgent):
    def __init__(
        self,
        client: Any,
        config: AgentConfig,
        tool_handlers: dict[str, Callable],
        tool_schemas: list[dict],
        event_bus=None,
        system_prompt: str = "",
        workspace_root: str = ".workspaces",
        scratchpad: Scratchpad | None = None,
        watchdog=None,
    ):
        super().__init__(client, config, tool_handlers, tool_schemas, event_bus, system_prompt)
        self.workspace_root = workspace_root
        self.workspace_path: str | None = None
        self.scratchpad = scratchpad or Scratchpad()
        self.watchdog = watchdog
        self._base_snapshot: dict[str, str] = {}
        self._handoff: dict | None = None

    async def setup_workspace(self) -> str:
        workspace_path = os.path.join(self.workspace_root, self.config.agent_id)
        os.makedirs(workspace_path, exist_ok=True)
        self.workspace_path = workspace_path

        if self.config.repo:
            await asyncio.to_thread(shutil.copytree, self.config.repo, workspace_path, dirs_exist_ok=True)

        self._base_snapshot = await asyncio.to_thread(snapshot_workspace, workspace_path)
        return workspace_path

    async def get_file_diffs(self) -> list[dict]:
        if not self.workspace_path:
            return []

        current_snapshot = await asyncio.to_thread(snapshot_workspace, self.workspace_path)
        diffs: list[dict] = []
        all_paths = set(self._base_snapshot.keys()) | set(current_snapshot.keys())

        for rel_path in sorted(all_paths):
            before_content = self._base_snapshot.get(rel_path)
            after_content = current_snapshot.get(rel_path)
            if before_content != after_content:
                diffs.append(
                    {
                        "path": rel_path,
                        "before": before_content,
                        "after": after_content,
                    }
                )

        return diffs

    async def build_handoff(self, status: str = "completed", narrative: str = "") -> dict:
        return {
            "worker_id": self.config.agent_id,
            "task_id": self.config.task_id,
            "status": status,
            "narrative": narrative,
            "diffs": await self.get_file_diffs(),
            "tokens_used": self.total_tokens,
            "turns": self.turn_count,
        }

    async def on_loop_exit(self) -> None:
        self._handoff = await self.build_handoff()
        if self.event_bus:
            await self.event_bus.emit(
                WorkerCompleted(
                    agent_id=self.config.agent_id,
                    task_id=self.config.task_id or "",
                    details={"handoff": self._handoff},
                )
            )

    async def on_tool_result(self, results: list[dict]) -> None:
        if self.watchdog:
            from harness.models.watchdog import ActivityEntry

            for result in results:
                tool_name = result.get("tool_name", "")
                files_touched = []
                tool_result = result.get("result", {})
                if isinstance(tool_result, dict):
                    path = tool_result.get("path", "")
                    if path:
                        files_touched.append(path)
                self.watchdog.record_activity(
                    ActivityEntry(
                        event_type=f"tool:{tool_name}",
                        agent_id=self.config.agent_id,
                        tokens_used=0,
                        files_touched=files_touched,
                    )
                )

        await super().on_tool_result(results)

    def cleanup(self) -> None:
        if self.workspace_path and os.path.isdir(self.workspace_path):
            shutil.rmtree(self.workspace_path)

    @property
    def handoff(self) -> dict | None:
        return self._handoff
