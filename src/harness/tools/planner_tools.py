from typing import Any

from harness.tools.browser_tool import browser_handler, visual_verify_handler
from harness.tools.git_tools import git_branch_handler, git_commit_handler, git_diff_handler, git_status_handler
from harness.tools.registry import ToolRegistry
from harness.tools.skill_tools import create_skill_handler, load_skill_handler
from harness.tools.web_tools import http_fetch_handler, url_extract_handler
from harness.tools.worker_tools import (
    ask_handler,
    background_task_handler,
    bash_handler,
    check_background_handler,
    edit_file_handler,
    find_files_handler,
    grep_handler,
    read_file_handler,
    submit_handoff_handler,
    todo_write_handler,
    write_file_handler,
)


def spawn_worker_handler(**kwargs) -> dict:
    return {"status": "spawned", "worker_id": kwargs.get("task_id", "unknown")}


def spawn_sub_planner_handler(**kwargs) -> dict:
    return {"status": "spawned", "planner_id": kwargs.get("scope", "unknown")}


def create_task_handler(**kwargs) -> dict:
    return {"status": "created", "task_id": kwargs.get("task_id", "unknown")}


def review_handoff_handler(**kwargs) -> dict:
    return {"status": "reviewed", "handoff_id": kwargs.get("handoff_id", "unknown")}


def accept_handoff_handler(**kwargs) -> dict:
    return {"status": "accepted", "handoff_id": kwargs.get("handoff_id", "unknown")}


def reject_handoff_handler(**kwargs) -> dict:
    return {"status": "rejected", "handoff_id": kwargs.get("handoff_id", "unknown")}


def rewrite_scratchpad_handler(**kwargs) -> dict:
    return {"status": "rewritten"}


def read_scratchpad_handler(**kwargs) -> dict:
    return {"status": "ok", "content": ""}


def send_message_handler(**kwargs) -> dict:
    return {"status": "sent"}


def read_inbox_handler(**kwargs) -> dict:
    return {"status": "ok", "messages": []}


def list_agents_handler(**kwargs) -> dict:
    return {"status": "ok", "agents": []}


def get_error_budget_handler(**kwargs) -> dict:
    return {"status": "ok", "zone": "healthy"}


async def create_skill_tool_handler(workspace_path: str = ".", **kwargs: Any) -> dict:
    return await create_skill_handler(kwargs, workspace_path=workspace_path)


async def load_skill_tool_handler(workspace_path: str = ".", **kwargs: Any) -> dict:
    return await load_skill_handler(kwargs, workspace_path=workspace_path)


WORKER_TOOL_SPECS = [
    {
        "name": "bash",
        "description": "Run a shell command in workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
        "handler": bash_handler,
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
        "handler": read_file_handler,
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
        "handler": write_file_handler,
    },
    {
        "name": "edit_file",
        "description": "Edit file content in workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        "handler": edit_file_handler,
    },
    {
        "name": "submit_handoff",
        "description": "Submit worker handoff details.",
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
        "handler": submit_handoff_handler,
    },
    {
        "name": "grep",
        "description": "Search file contents using regex pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Relative path to search in"},
                "include": {"type": "string", "description": "File pattern filter (e.g., *.py)"},
                "context_lines": {"type": "integer", "description": "Lines of context around matches"},
            },
            "required": ["pattern"],
        },
        "handler": grep_handler,
    },
    {
        "name": "find_files",
        "description": "Find files in workspace by glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match files"},
                "max_results": {"type": "integer", "description": "Maximum number of files to return"},
            },
            "required": ["pattern"],
        },
        "handler": find_files_handler,
    },
    {
        "name": "todo_write",
        "description": "Write and validate a structured todo list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "List of todo items",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                        },
                        "required": ["content", "status", "priority"],
                    },
                }
            },
            "required": ["todos"],
        },
        "handler": todo_write_handler,
    },
    {
        "name": "ask",
        "description": "Ask a clarification question back to planner.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question to ask the planner"},
                "options": {
                    "type": "array",
                    "description": "Optional response choices",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["label", "value"],
                    },
                },
            },
            "required": ["question"],
        },
        "handler": ask_handler,
    },
    {
        "name": "background_task",
        "description": "Spawn a background command that runs asynchronously.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What this background task does"},
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
            },
            "required": ["description", "command"],
        },
        "handler": background_task_handler,
    },
    {
        "name": "check_background",
        "description": "Check status of a background task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID returned by background_task"},
            },
            "required": ["task_id"],
        },
        "handler": check_background_handler,
    },
    {
        "name": "create_skill",
        "description": "Create a new SKILL.md in project-level .omp skills.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "content": {"type": "string"},
                "triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["name", "description", "content"],
        },
        "handler": create_skill_tool_handler,
    },
    {
        "name": "load_skill",
        "description": "Load a skill by name and return its content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
        "handler": load_skill_tool_handler,
    },
    {
        "name": "browser",
        "description": "Automate a headless browser: navigate, screenshot, click, type, evaluate JS, get text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "Action: navigate, screenshot, click, type, evaluate, get_text, accessibility_snapshot, close"
                    ),
                },
                "url": {"type": "string", "description": "URL for navigate action"},
                "selector": {"type": "string", "description": "CSS selector for click/type/get_text"},
                "text": {"type": "string", "description": "Text for type action"},
                "script": {"type": "string", "description": "JavaScript for evaluate action"},
                "path": {"type": "string", "description": "File path for screenshot save"},
                "session_id": {"type": "string", "description": "Browser session ID (default: 'default')"},
            },
            "required": ["action"],
        },
        "handler": browser_handler,
    },
    {
        "name": "visual_verify",
        "description": "Navigate to URL, screenshot, and verify page matches expected description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to verify"},
                "expected": {
                    "type": "string",
                    "description": "Expected description of what the page should show",
                },
                "session_id": {"type": "string", "description": "Browser session ID"},
            },
            "required": ["url", "expected"],
        },
        "handler": visual_verify_handler,
    },
    {
        "name": "git_status",
        "description": "Run git status --porcelain in workspace.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": git_status_handler,
    },
    {
        "name": "git_diff",
        "description": "Run git diff in workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "staged": {"type": "boolean", "description": "Use --staged"},
            },
            "required": [],
        },
        "handler": git_diff_handler,
    },
    {
        "name": "git_commit",
        "description": "Stage all changes and commit with a message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
            },
            "required": ["message"],
        },
        "handler": git_commit_handler,
    },
    {
        "name": "git_branch",
        "description": "List branches or create and checkout a new branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "create": {"type": "boolean", "description": "Create a new branch"},
                "name": {"type": "string", "description": "Branch name when create=true"},
            },
            "required": [],
        },
        "handler": git_branch_handler,
    },
    {
        "name": "http_fetch",
        "description": "Fetch URL content over HTTP.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
            },
            "required": ["url"],
        },
        "handler": http_fetch_handler,
    },
    {
        "name": "url_extract",
        "description": "Fetch URL and extract text content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
            },
            "required": ["url"],
        },
        "handler": url_extract_handler,
    },
]


PLANNER_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "spawn_worker",
        "description": "Spawn a worker for a delegated task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "task": {"type": "string"},
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "spawn_sub_planner",
        "description": "Spawn a sub-planner for scoped planning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string"},
                "task": {"type": "string"},
            },
            "required": ["scope"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a task on the scheduler.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "description": {"type": "string"},
                "blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["task_id", "description"],
        },
    },
    {
        "name": "review_handoff",
        "description": "Review a handoff before decision.",
        "input_schema": {
            "type": "object",
            "properties": {
                "handoff_id": {"type": "string"},
            },
            "required": ["handoff_id"],
        },
    },
    {
        "name": "accept_handoff",
        "description": "Accept a reviewed handoff.",
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
        "description": "Reject a reviewed handoff.",
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
        "description": "Rewrite planner scratchpad content.",
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
        "description": "Read planner scratchpad content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "send_message",
        "description": "Send a planner coordination message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["to", "content"],
        },
    },
    {
        "name": "read_inbox",
        "description": "Read planner inbox messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "list_agents",
        "description": "List currently known agents.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_error_budget",
        "description": "Get current error budget zone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string"},
            },
            "required": [],
        },
    },
]


PLANNER_TOOL_HANDLERS = {
    "spawn_worker": spawn_worker_handler,
    "spawn_sub_planner": spawn_sub_planner_handler,
    "create_task": create_task_handler,
    "review_handoff": review_handoff_handler,
    "accept_handoff": accept_handoff_handler,
    "reject_handoff": reject_handoff_handler,
    "rewrite_scratchpad": rewrite_scratchpad_handler,
    "read_scratchpad": read_scratchpad_handler,
    "send_message": send_message_handler,
    "read_inbox": read_inbox_handler,
    "list_agents": list_agents_handler,
    "get_error_budget": get_error_budget_handler,
}


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    for tool_spec in WORKER_TOOL_SPECS:
        schema = {
            "name": tool_spec["name"],
            "description": tool_spec["description"],
            "input_schema": tool_spec["input_schema"],
        }
        registry.register(
            name=tool_spec["name"],
            handler=tool_spec["handler"],
            schema=schema,
            allowed_roles=["worker"],
        )

    planner_roles = ["root_planner", "sub_planner"]
    for schema in PLANNER_TOOL_SCHEMAS:
        registry.register(
            name=schema["name"],
            handler=PLANNER_TOOL_HANDLERS[schema["name"]],
            schema=schema,
            allowed_roles=planner_roles,
        )

    return registry
