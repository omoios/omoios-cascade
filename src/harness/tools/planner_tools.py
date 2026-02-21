from harness.tools.registry import ToolRegistry
from harness.tools.worker_tools import (
    ask_handler,
    bash_handler,
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
