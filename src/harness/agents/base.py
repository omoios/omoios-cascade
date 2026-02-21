import json
import time
from typing import Any, Callable

from harness.events import EventBus
from harness.models.agent import AgentConfig


class BaseAgent:
    COMPRESSION_THRESHOLD = 100000

    def __init__(
        self,
        client: Any,
        config: AgentConfig,
        tool_handlers: dict[str, Callable],
        tool_schemas: list[dict],
        event_bus: EventBus | None = None,
        system_prompt: str = "",
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

    def run(self, initial_message: str = "") -> str:
        self._start_time = time.time()
        if initial_message:
            self.messages.append({"role": "user", "content": initial_message})

        last_text = ""
        while True:
            self.on_before_llm_call()
            response = self._call_llm()
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
                self.on_loop_exit()
                return last_text

            tool_results: list[dict[str, str]] = []
            hook_results: list[dict] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                handler = self.tool_handlers.get(block.name)
                if handler:
                    result = handler(**block.input)
                else:
                    result = {"error": f"Unknown tool: {block.name}"}
                hook_results.append({"tool_name": block.name, "tool_use_id": block.id, "result": result})
                content = json.dumps(result) if isinstance(result, dict) else str(result)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                    }
                )

            self.messages.append({"role": "user", "content": tool_results})
            self.on_tool_result(hook_results)

            if self.total_tokens >= self.config.token_budget:
                break
            if self._start_time is not None and (time.time() - self._start_time >= self.config.timeout_seconds):
                break

        self.on_loop_exit()
        return last_text

    def _call_llm(self):
        kwargs: dict[str, Any] = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 8192,
            "messages": self.messages,
        }
        if self.system_prompt:
            kwargs["system"] = self.system_prompt
        if self.tool_schemas:
            kwargs["tools"] = self.tool_schemas
        return self.client.messages.create(**kwargs)

    def on_before_llm_call(self) -> None:
        from harness.orchestration.compression import estimate_tokens, microcompact

        current_tokens = estimate_tokens(self.messages)
        if current_tokens > self.COMPRESSION_THRESHOLD and len(self.messages) > 6:
            self.messages = microcompact(self.messages, keep_recent=3)

    def on_tool_result(self, results: list[dict]) -> None:
        pass

    def on_loop_exit(self) -> None:
        pass
