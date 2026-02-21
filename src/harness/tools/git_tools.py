import asyncio
import os
from typing import Any


def _workspace_guard(workspace_path: str) -> tuple[bool, str]:
    resolved = os.path.realpath(workspace_path)
    if not os.path.isdir(resolved):
        return False, "Workspace path does not exist"
    return True, resolved


async def _run_git_command(args: list[str], workspace_path: str) -> dict[str, Any]:
    ok, resolved_or_error = _workspace_guard(workspace_path)
    if not ok:
        return {"output": "", "exit_code": -1, "error": resolved_or_error}

    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=resolved_or_error,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
    output = (stdout or stderr) if proc.returncode == 0 else (stderr or stdout)
    return {"output": output, "exit_code": proc.returncode}


async def git_status_handler(workspace_path: str, input: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = input
    return await _run_git_command(["status", "--porcelain"], workspace_path)


async def git_diff_handler(
    workspace_path: str,
    staged: bool = False,
    input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    staged_flag = staged
    if input and isinstance(input, dict):
        staged_flag = bool(input.get("staged", staged_flag))
    args = ["diff", "--staged"] if staged_flag else ["diff"]
    return await _run_git_command(args, workspace_path)


async def git_commit_handler(
    workspace_path: str,
    message: str = "",
    input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msg = message.strip()
    if input and isinstance(input, dict):
        msg = str(input.get("message", msg)).strip()
    if not msg:
        return {"output": "", "exit_code": -1, "error": "Commit message is required"}

    add_result = await _run_git_command(["add", "-A"], workspace_path)
    if add_result["exit_code"] != 0:
        return add_result
    return await _run_git_command(["commit", "-m", msg], workspace_path)


async def git_branch_handler(
    workspace_path: str,
    name: str = "",
    create: bool = False,
    input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    branch_name = name.strip()
    should_create = create
    if input and isinstance(input, dict):
        branch_name = str(input.get("name", branch_name)).strip()
        should_create = bool(input.get("create", should_create))

    if should_create:
        if not branch_name:
            return {"output": "", "exit_code": -1, "error": "Branch name is required"}
        return await _run_git_command(["checkout", "-b", branch_name], workspace_path)

    return await _run_git_command(["branch"], workspace_path)
