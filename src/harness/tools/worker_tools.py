import asyncio
import os
from typing import Any


async def bash_handler(command: str, workspace_path: str, timeout: int = 30) -> dict[str, Any]:
    dangerous = ["rm -rf /", "mkfs", "dd if=", "format", "> /dev/"]
    cmd_check = command.strip()
    if any(d in cmd_check for d in dangerous):
        return {"stdout": "", "stderr": "Dangerous command blocked", "exit_code": -1}
    if cmd_check.startswith("rm -rf"):
        return {"stdout": "", "stderr": "Dangerous command blocked", "exit_code": -1}

    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "stdout": stdout_bytes.decode() if stdout_bytes else "",
            "stderr": stderr_bytes.decode() if stderr_bytes else "",
            "exit_code": proc.returncode,
        }
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"stdout": "", "stderr": "Command timed out", "exit_code": -1}


async def read_file_handler(path: str, workspace_path: str, offset: int = 0, limit: int = 2000) -> dict[str, Any]:
    full_path = os.path.join(workspace_path, path)
    resolved = os.path.realpath(full_path)
    if not resolved.startswith(os.path.realpath(workspace_path)):
        return {"error": f"Path escapes workspace: {path}"}

    if not os.path.exists(resolved):
        return {"error": f"File not found: {path}"}

    try:
        with open(resolved, "r") as f:
            lines = f.readlines()

        total_lines = len(lines)
        selected_lines = lines[offset : offset + limit]

        return {
            "content": "".join(selected_lines),
            "lines_read": len(selected_lines),
            "total_lines": total_lines,
        }
    except Exception as e:
        return {"error": str(e)}


async def write_file_handler(path: str, content: str, workspace_path: str) -> dict[str, Any]:
    full_path = os.path.join(workspace_path, path)
    resolved = os.path.realpath(full_path)
    if not resolved.startswith(os.path.realpath(workspace_path)):
        return {"error": f"Path escapes workspace: {path}"}

    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        bytes_written = len(content.encode("utf-8"))
        with open(resolved, "w") as f:
            f.write(content)
        return {"path": path, "bytes_written": bytes_written}
    except Exception as e:
        return {"error": str(e)}


async def edit_file_handler(path: str, old_string: str, new_string: str, workspace_path: str) -> dict[str, Any]:
    full_path = os.path.join(workspace_path, path)
    resolved = os.path.realpath(full_path)
    if not resolved.startswith(os.path.realpath(workspace_path)):
        return {"error": f"Path escapes workspace: {path}"}

    if not os.path.exists(resolved):
        return {"error": f"File not found: {path}"}

    try:
        with open(resolved, "r") as f:
            content = f.read()

        if old_string not in content:
            return {"error": f"old_string not found in {path}"}

        new_content = content.replace(old_string, new_string, 1)
        with open(resolved, "w") as f:
            f.write(new_content)

        return {"path": path, "replacements": 1}
    except Exception as e:
        return {"error": str(e)}


async def submit_handoff_handler(
    agent_id: str,
    task_id: str,
    status: str,
    narrative: str,
    **kwargs,
) -> dict[str, Any]:
    handoff = {
        "submitted": True,
        "agent_id": agent_id,
        "task_id": task_id,
        "status": status,
        "narrative": narrative,
    }
    for key, value in kwargs.items():
        handoff[key] = value
    return handoff
