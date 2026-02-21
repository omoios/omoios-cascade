from __future__ import annotations

import re
from typing import Any

try:
    import httpx

    HAS_HTTPX = True
except Exception:
    httpx = None
    HAS_HTTPX = False

try:
    from markdownify import markdownify

    HAS_MARKDOWNIFY = True
except Exception:
    markdownify = None
    HAS_MARKDOWNIFY = False

MAX_RESPONSE_BYTES = 100 * 1024


def _html_to_text(content: str) -> str:
    if HAS_MARKDOWNIFY and markdownify is not None:
        return markdownify(content)
    no_scripts = re.sub(r"<script.*?>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)
    no_styles = re.sub(r"<style.*?>.*?</style>", "", no_scripts, flags=re.IGNORECASE | re.DOTALL)
    no_tags = re.sub(r"<[^>]+>", " ", no_styles)
    return re.sub(r"\s+", " ", no_tags).strip()


def _truncate_bytes(raw: bytes) -> tuple[str, bool]:
    truncated = len(raw) > MAX_RESPONSE_BYTES
    payload = raw[:MAX_RESPONSE_BYTES]
    return payload.decode(errors="replace"), truncated


async def http_fetch_handler(
    workspace_path: str,
    url: str = "",
    timeout: int = 30,
    input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ = workspace_path
    if not HAS_HTTPX or httpx is None:
        return {
            "output": "",
            "exit_code": -1,
            "error": "httpx is not installed. Install with: uv add httpx",
        }

    target_url = url.strip()
    req_timeout = timeout
    if input and isinstance(input, dict):
        target_url = str(input.get("url", target_url)).strip()
        req_timeout = int(input.get("timeout", req_timeout))

    if not target_url:
        return {"output": "", "exit_code": -1, "error": "URL is required"}

    try:
        async with httpx.AsyncClient(timeout=req_timeout) as client:
            response = await client.get(target_url, follow_redirects=True)
        body, truncated = _truncate_bytes(response.content)
        return {
            "output": body,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "truncated": truncated,
            "exit_code": 0,
        }
    except Exception as exc:
        return {"output": "", "exit_code": -1, "error": str(exc)}


async def url_extract_handler(
    workspace_path: str,
    url: str = "",
    timeout: int = 30,
    input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fetch = await http_fetch_handler(workspace_path=workspace_path, url=url, timeout=timeout, input=input)
    if fetch.get("exit_code") != 0:
        return fetch

    output = str(fetch.get("output", ""))
    content_type = str(fetch.get("headers", {}).get("content-type", "")).lower()
    if "html" in content_type or "<html" in output.lower():
        output = _html_to_text(output)

    return {
        "output": output,
        "status_code": fetch.get("status_code", 0),
        "truncated": bool(fetch.get("truncated", False)),
        "exit_code": 0,
    }
