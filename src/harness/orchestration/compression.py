from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness.models.state import StateSnapshot


def estimate_tokens(messages: list[dict]) -> int:
    return sum(len(str(message)) // 4 for message in messages)


def _compact_message_content(content: object) -> object:
    if not isinstance(content, list):
        return content

    new_content: list[object] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "tool_result":
            compacted_part = dict(part)
            compacted_part["content"] = "[compacted]"
            new_content.append(compacted_part)
            continue
        new_content.append(part)
    return new_content


def microcompact(messages: list[dict], keep_recent: int = 3) -> list[dict]:
    user_indices = [index for index, message in enumerate(messages) if message.get("role") == "user"]

    if len(user_indices) <= keep_recent:
        return deepcopy(messages)

    cutoff_index = user_indices[-keep_recent]
    compacted: list[dict] = []

    for index, message in enumerate(messages):
        new_message = deepcopy(message)

        if index < cutoff_index:
            if new_message.get("type") == "tool_result":
                new_message["content"] = "[compacted]"
            else:
                new_message["content"] = _compact_message_content(new_message.get("content"))

        compacted.append(new_message)

    return compacted


def auto_compact(messages: list[dict], client: object, snapshot: StateSnapshot) -> list[dict]:
    _ = client
    compacted = microcompact(messages)
    injected_state = {
        "role": "user",
        "content": f"[state_snapshot]\n{snapshot.model_dump_json()}",
    }
    return [injected_state, *compacted]


class CompressionTracker:
    def __init__(self):
        self.count = 0

    def record_compression(self) -> None:
        self.count += 1
