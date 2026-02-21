from typing import Any, TypeVar

import instructor
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def patch_client(client: Any) -> Any:
    return instructor.from_anthropic(client)


def extract_structured(
    client: Any,
    model: str,
    response_model: type[T],
    messages: list[dict],
    system: str = "",
) -> T:
    patched_client = patch_client(client)
    kwargs: dict[str, Any] = {
        "model": model,
        "response_model": response_model,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    return patched_client.messages.create(**kwargs)
