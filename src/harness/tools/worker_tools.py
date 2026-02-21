import asyncio
import os
from pathlib import Path
from typing import Any

from harness.models.todo import TodoItem

try:
    import harness_core as _harness_core

    _rust_grep = getattr(_harness_core, "rust_grep", None)
    _rust_glob = getattr(_harness_core, "rust_glob", None)
    HAS_RUST_GREP = callable(_rust_grep) and callable(_rust_glob)
except ImportError:
    _rust_grep = None
    _rust_glob = None
    HAS_RUST_GREP = False

_background_tasks: dict[str, asyncio.Task] = {}
_background_results: dict[str, dict] = {}


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


async def grep_handler(
    pattern: str,
    path: str = ".",
    workspace_path: str = ".",
    include: str | None = None,
    context_lines: int = 0,
) -> dict[str, Any]:
    workspace_real = os.path.realpath(workspace_path)
    search_real = os.path.realpath(os.path.join(workspace_path, path))

    if os.path.commonpath([workspace_real, search_real]) != workspace_real:
        return {"error": f"Path escapes workspace: {path}"}
    if not os.path.exists(search_real):
        return {"error": f"Path not found: {path}"}

    if HAS_RUST_GREP and context_lines == 0:
        try:
            raw_matches = await asyncio.to_thread(_rust_grep, search_real, pattern, include, 10000)
        except Exception as exc:
            return {"error": str(exc)}

        matches: list[dict[str, Any]] = []
        search_base = search_real if os.path.isdir(search_real) else os.path.dirname(search_real)
        for file_path, line_num, content in raw_matches:
            full_file_path = file_path if os.path.isabs(file_path) else os.path.join(search_base, file_path)
            matches.append(
                {
                    "file": os.path.relpath(full_file_path, workspace_real),
                    "line": int(line_num),
                    "content": content,
                }
            )

        total = len(matches)
        truncated = total > 100
        result: dict[str, Any] = {
            "matches": matches[:100],
            "total": total,
            "truncated": truncated,
        }
        if truncated:
            result["notice"] = "Output truncated to 100 matches"
        return result

    cmd = ["grep", "-rn"]
    if include:
        cmd.append(f"--include={include}")
    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])
    cmd.extend(["--", pattern, search_real])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode() if stdout_bytes else ""
    stderr = stderr_bytes.decode() if stderr_bytes else ""

    if proc.returncode not in (0, 1):
        return {"error": stderr or "grep failed", "exit_code": proc.returncode}

    matches: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        line_num = parts[1]
        if not line_num.isdigit():
            continue
        file_path = os.path.relpath(parts[0], workspace_real)
        matches.append(
            {
                "file": file_path,
                "line": int(line_num),
                "content": parts[2],
            }
        )

    total = len(matches)
    truncated = total > 100
    result: dict[str, Any] = {
        "matches": matches[:100],
        "total": total,
        "truncated": truncated,
    }
    if truncated:
        result["notice"] = "Output truncated to 100 matches"
    return result


async def find_files_handler(
    pattern: str,
    workspace_path: str = ".",
    max_results: int = 100,
) -> dict[str, Any]:
    workspace = Path(workspace_path)

    if HAS_RUST_GREP:
        try:
            files = await asyncio.to_thread(_rust_glob, str(workspace), pattern, 10000)
        except Exception as exc:
            return {"error": str(exc)}
        total = len(files)
        truncated = total > max_results
        return {
            "files": files[:max_results],
            "total": total,
            "truncated": truncated,
        }

    def _glob() -> list[str]:
        matches = [str(path.relative_to(workspace)) for path in workspace.glob(pattern) if path.is_file()]
        return sorted(matches)

    files = await asyncio.to_thread(_glob)
    total = len(files)
    truncated = total > max_results
    return {
        "files": files[:max_results],
        "total": total,
        "truncated": truncated,
    }


async def todo_write_handler(
    todos: list[dict],
    workspace_path: str = ".",
) -> dict[str, Any]:
    _ = workspace_path
    required = {"content", "status", "priority"}
    for idx, todo in enumerate(todos):
        missing = required - todo.keys()
        if missing:
            missing_fields = ", ".join(sorted(missing))
            return {"error": f"Todo at index {idx} missing fields: {missing_fields}"}
        try:
            TodoItem.model_validate(todo)
        except Exception as exc:
            return {"error": f"Todo at index {idx} invalid: {exc}"}
    return {"status": "ok", "count": len(todos)}


async def ask_handler(
    question: str,
    options: list[dict] | None = None,
    workspace_path: str = ".",
) -> dict[str, Any]:
    _ = options
    _ = workspace_path
    return {"status": "asked", "question": question}


async def background_task_handler(
    description: str,
    command: str,
    workspace_path: str = ".",
    timeout: int = 120,
) -> dict[str, Any]:
    import uuid

    task_id = f"bg_{uuid.uuid4().hex[:8]}"

    async def _run() -> None:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace_path,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            _background_results[task_id] = {
                "status": "completed",
                "exit_code": proc.returncode,
                "stdout": stdout.decode(errors="replace")[:10000],
                "stderr": stderr.decode(errors="replace")[:5000],
            }
        except asyncio.TimeoutError:
            _background_results[task_id] = {
                "status": "timeout",
                "exit_code": -1,
                "stdout": "",
                "stderr": "Timed out",
            }
        except Exception as e:
            _background_results[task_id] = {
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
            }

    task = asyncio.create_task(_run())
    _background_tasks[task_id] = task
    return {"task_id": task_id, "status": "running", "description": description}


async def check_background_handler(
    task_id: str,
    workspace_path: str = ".",
) -> dict[str, Any]:
    _ = workspace_path
    if task_id in _background_results:
        result = _background_results.pop(task_id)
        _background_tasks.pop(task_id, None)
        return result

    if task_id in _background_tasks:
        task = _background_tasks[task_id]
        if task.done():
            return _background_results.pop(
                task_id,
                {"status": "completed", "exit_code": 0, "stdout": "", "stderr": ""},
            )
        return {"status": "running"}

    return {"status": "not_found", "error": f"Unknown task_id: {task_id}"}
