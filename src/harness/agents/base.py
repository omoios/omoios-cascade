from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, Callable

from harness.agents.ttsr import TTSRMixin
from harness.events import EventBus, IdentityReinjected, PivotEncouraged, SelfReflectionInjected
from harness.models.agent import AgentConfig

if TYPE_CHECKING:
    from harness.storage import HarnessDB

class BaseAgent(TTSRMixin):
    COMPRESSION_THRESHOLD = 100000

    def __init__(
        self,
        client: Any,
        config: AgentConfig,
        tool_handlers: dict[str, Callable],
        tool_schemas: list[dict],
        event_bus: EventBus | None = None,
        system_prompt: str = "",
        db: HarnessDB | None = None,
    ):
        self.client = client
        self.config = config
        self.tool_handlers = tool_handlers
        self.tool_schemas = tool_schemas
        self.event_bus = event_bus
        self.system_prompt = system_prompt or config.system_prompt
        self.messages: list[dict] = []
        self.total_tokens: int = 0
        self.turn_count: int = 0
        self._start_time: float | None = None
        self._identity_text: str = ""
        self._alignment_text: str = ""
        self._reflection_interval: int = 10
        self._consecutive_failures: dict[str, int] = {}
        self._pivot_threshold: int = 3
        self._hard_stop_threshold: int = 5
        self.activity_logger = None
        self._agents_md: str = ""
        self._skill_content: str = ""
        self._injected_skills: set[str] = set()
        self._db: HarnessDB | None = db
        self._init_ttsr_state()

    async def run(self, initial_message: str = "") -> str:
        self._start_time = time.time()
        if initial_message:
            self.messages.append({"role": "user", "content": initial_message})

        last_text = ""
        while True:
            await self.on_before_llm_call()
            response = await self._call_llm()
            self.total_tokens += int(getattr(response.usage, "input_tokens", 0)) + int(
                getattr(response.usage, "output_tokens", 0)
            )
            self.turn_count += 1
            # Filter out ThinkingBlocks before appending to conversation history
            filtered_content = [
                block for block in response.content
                if getattr(block, 'type', None) != 'thinking'
            ]
            self.messages.append({"role": "assistant", "content": filtered_content or response.content})

            text_blocks = [
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text" and hasattr(block, "text")
            ]
            if text_blocks:
                last_text = "\n".join(text_blocks)

            if response.stop_reason != "tool_use":
                # Check if subclass wants to nudge the model into using tools
                nudge = self._get_tool_nudge()
                if nudge:
                    self.messages.append({"role": "user", "content": nudge})
                    continue
                await self.on_loop_exit()
                return last_text

            tool_results: list[dict[str, str]] = []
            hook_results: list[dict] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if self.activity_logger:
                    await self.activity_logger.log(
                        self.config.agent_id,
                        "tool_use",
                        tool=block.name,
                        metrics={"turn_count": self.turn_count, "total_tokens": self.total_tokens},
                        tool_use_id=block.id,
                    )
                handler = self.tool_handlers.get(block.name)
                if handler:
                    result = handler(**block.input)
                    if asyncio.iscoroutine(result):
                        result = await result
                else:
                    result = {"error": f"Unknown tool: {block.name}"}
                hook_results.append({"tool_name": block.name, "tool_use_id": block.id, "result": result})
                if self.activity_logger:
                    await self.activity_logger.log(
                        self.config.agent_id,
                        "tool_result",
                        tool=block.name,
                        metrics={"turn_count": self.turn_count, "total_tokens": self.total_tokens},
                        tool_use_id=block.id,
                        success=not (isinstance(result, dict) and "error" in result),
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

    async def _call_llm(self):
        system_prompt = self.system_prompt
        if self._agents_md:
            system_prompt = f"{system_prompt}\n\n# AGENTS.md\n{self._agents_md}".strip()
        if self._skill_content:
            system_prompt = f"{system_prompt}\n\n# Skills\n{self._skill_content}".strip()
        ttsr_prompt = self._ttsr_consume_system_messages()
        if ttsr_prompt:
            system_prompt = f"{system_prompt}\n\n{ttsr_prompt}".strip()

        kwargs: dict[str, Any] = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 8192,
            "messages": self.messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if self.tool_schemas:
            kwargs["tools"] = self.tool_schemas
        return await self.client.messages.create(**kwargs)

    async def on_before_llm_call(self) -> None:
        await self._ttsr_before_llm_call()

        from harness.orchestration.compression import estimate_tokens, microcompact

        current_tokens = estimate_tokens(self.messages)
        if current_tokens > self.COMPRESSION_THRESHOLD and len(self.messages) > 6:
            self.messages = microcompact(self.messages, keep_recent=3)
            if self._identity_text:
                self.messages.insert(0, {"role": "user", "content": f"[IDENTITY REMINDER] {self._identity_text}"})
                if self.event_bus:
                    await self.event_bus.emit(IdentityReinjected(agent_id=self.config.agent_id))
            if self._alignment_text:
                self.messages.append({"role": "user", "content": f"[ALIGNMENT] {self._alignment_text}"})
            # Persist compressed messages to SQLite
            self._persist_messages()

        if self.turn_count > 0 and self.turn_count % self._reflection_interval == 0:
            self.messages.append(
                {
                    "role": "user",
                    "content": (
                        "[SELF-REFLECTION] Pause and assess:\n"
                        "- Are you making progress or going in circles?\n"
                        "- Is your current approach working? If not, consider a different strategy.\n"
                        "- What is the most important next step?"
                    ),
                }
            )
            if self.event_bus:
                await self.event_bus.emit(
                    SelfReflectionInjected(agent_id=self.config.agent_id, turn_count=self.turn_count)
                )

    async def on_tool_result(self, results: list[dict]) -> None:
        await self._ttsr_on_tool_result(results)

        for result in results:
            tool_name = result.get("tool_name", "")
            tool_result = result.get("result", {})
            is_error = isinstance(tool_result, dict) and "error" in tool_result

            if is_error:
                self._consecutive_failures[tool_name] = self._consecutive_failures.get(tool_name, 0) + 1
                count = self._consecutive_failures[tool_name]
                if count >= self._hard_stop_threshold:
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[HARD STOP] This approach is not working after 5 failures. "
                                "Step back and reconsider the problem entirely."
                            ),
                        }
                    )
                elif count >= self._pivot_threshold:
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"[PIVOT] Your current approach with {tool_name} has failed {count} times. "
                                "Try a completely different approach."
                            ),
                        }
                    )
                    if self.event_bus:
                        await self.event_bus.emit(
                            PivotEncouraged(
                                agent_id=self.config.agent_id,
                                tool_name=tool_name,
                                failure_count=count,
                            )
                        )
            else:
                self._consecutive_failures[tool_name] = 0

    async def on_loop_exit(self) -> None:
        # Persist final messages to SQLite on exit
        self._persist_messages()


    def _get_tool_nudge(self) -> str | None:
        """Override in subclass to nudge model into using tools. Return None to skip."""
        return None

    def _persist_messages(self) -> None:
        """Write current messages to HarnessDB if available."""
        if self._db is None:
            return
        self._db.replace_messages(self.config.agent_id, self.messages)