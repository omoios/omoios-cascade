interface ToolDef {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

interface PlaygroundConfig {
  systemPrompt: string;
  tools: ToolDef[];
  model: string;
}

const BASH_TOOL: ToolDef = {
  name: "bash",
  description: "Execute a bash command",
  input_schema: {
    type: "object",
    properties: {
      command: { type: "string", description: "The bash command to run" },
    },
    required: ["command"],
  },
};

const READ_FILE_TOOL: ToolDef = {
  name: "read_file",
  description: "Read the contents of a file",
  input_schema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to the file" },
    },
    required: ["file_path"],
  },
};

const WRITE_FILE_TOOL: ToolDef = {
  name: "write_file",
  description: "Write content to a file (creates or overwrites)",
  input_schema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to the file" },
      content: { type: "string", description: "Content to write" },
    },
    required: ["file_path", "content"],
  },
};

const EDIT_FILE_TOOL: ToolDef = {
  name: "edit_file",
  description: "Replace text in a file",
  input_schema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to the file" },
      old_string: { type: "string", description: "Text to find" },
      new_string: { type: "string", description: "Replacement text" },
    },
    required: ["file_path", "old_string", "new_string"],
  },
};

const TODO_TOOL: ToolDef = {
  name: "todo",
  description: "Manage a todo list: create, update, or list todos",
  input_schema: {
    type: "object",
    properties: {
      action: { type: "string", enum: ["create", "update", "list"], description: "Action to perform" },
      title: { type: "string", description: "Todo title (for create)" },
      id: { type: "number", description: "Todo ID (for update)" },
      status: { type: "string", enum: ["pending", "done"], description: "Status (for update)" },
    },
    required: ["action"],
  },
};

const TASK_TOOL: ToolDef = {
  name: "task",
  description: "Delegate work to a subagent with isolated context",
  input_schema: {
    type: "object",
    properties: {
      description: { type: "string", description: "Task description for the subagent" },
    },
    required: ["description"],
  },
};

const SKILL_TOOL: ToolDef = {
  name: "load_skill",
  description: "Load a SKILL.md file to gain specialized knowledge",
  input_schema: {
    type: "object",
    properties: {
      skill_name: { type: "string", description: "Name of the skill to load" },
    },
    required: ["skill_name"],
  },
};

const TASK_MANAGER_TOOL: ToolDef = {
  name: "task_manager",
  description: "Manage persistent tasks: create, update, list, with dependency tracking",
  input_schema: {
    type: "object",
    properties: {
      action: { type: "string", enum: ["create", "update", "list", "get"], description: "Action to perform" },
      title: { type: "string", description: "Task title (for create)" },
      id: { type: "string", description: "Task ID (for update/get)" },
      status: { type: "string", enum: ["open", "in_progress", "done"], description: "Task status" },
      blocked_by: { type: "array", items: { type: "string" }, description: "Task IDs this depends on" },
    },
    required: ["action"],
  },
};

const BACKGROUND_TOOL: ToolDef = {
  name: "background",
  description: "Run a command in the background without blocking",
  input_schema: {
    type: "object",
    properties: {
      command: { type: "string", description: "Command to run in background" },
    },
    required: ["command"],
  },
};

const SEND_MESSAGE_TOOL: ToolDef = {
  name: "send_message",
  description: "Send a message to a teammate",
  input_schema: {
    type: "object",
    properties: {
      to: { type: "string", description: "Teammate name" },
      content: { type: "string", description: "Message content" },
    },
    required: ["to", "content"],
  },
};

const SPAWN_TEAMMATE_TOOL: ToolDef = {
  name: "spawn_teammate",
  description: "Spawn a new teammate agent",
  input_schema: {
    type: "object",
    properties: {
      name: { type: "string", description: "Teammate name" },
      role: { type: "string", description: "Teammate role description" },
    },
    required: ["name", "role"],
  },
};

const SHUTDOWN_TOOL: ToolDef = {
  name: "shutdown_teammate",
  description: "Request a teammate to shut down gracefully",
  input_schema: {
    type: "object",
    properties: {
      name: { type: "string", description: "Teammate name to shut down" },
    },
    required: ["name"],
  },
};

const CLAIM_TASK_TOOL: ToolDef = {
  name: "claim_task",
  description: "Claim an unowned task from the shared board",
  input_schema: {
    type: "object",
    properties: {
      task_id: { type: "string", description: "ID of the task to claim" },
    },
    required: ["task_id"],
  },
};

const MODEL = "claude-sonnet-4-20250514";
const MULTI_TOOLS = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL];

export const PLAYGROUND_CONFIGS: Record<string, PlaygroundConfig> = {
  s01: {
    systemPrompt:
      "You are a helpful coding assistant. You have access to bash. Use it to help the user with their tasks. Be concise.",
    tools: [BASH_TOOL],
    model: MODEL,
  },
  s02: {
    systemPrompt:
      "You are a helpful coding assistant with file management tools. Use read_file to inspect files, write_file to create files, edit_file to modify files, and bash for commands.",
    tools: MULTI_TOOLS,
    model: MODEL,
  },
  s03: {
    systemPrompt:
      "You are a helpful coding assistant. Before starting any task, create a todo plan. Work through each todo, marking them done as you go. Use the available tools to implement step by step.",
    tools: [...MULTI_TOOLS, TODO_TOOL],
    model: MODEL,
  },
  s04: {
    systemPrompt:
      "You are a helpful coding assistant. For complex tasks, delegate subtasks to subagents using the task tool. Each subagent runs with fresh context to avoid confusion.",
    tools: [...MULTI_TOOLS, TODO_TOOL, TASK_TOOL],
    model: MODEL,
  },
  s05: {
    systemPrompt:
      "You are a helpful coding assistant. When you need specialized knowledge, use load_skill to load a SKILL.md file. Skills provide domain-specific instructions injected via tool_result.",
    tools: [...MULTI_TOOLS, TODO_TOOL, TASK_TOOL, SKILL_TOOL],
    model: MODEL,
  },
  s06: {
    systemPrompt:
      "You are a helpful coding assistant with context compression. When context grows large, old tool results are compacted and conversations are summarized to stay within token limits.",
    tools: [...MULTI_TOOLS, TODO_TOOL, TASK_TOOL, SKILL_TOOL],
    model: MODEL,
  },
  s07: {
    systemPrompt:
      "You are a helpful coding assistant with persistent task management. Use task_manager to create tasks with dependencies, track progress, and manage complex workflows that survive context compression.",
    tools: [...MULTI_TOOLS, TASK_MANAGER_TOOL],
    model: MODEL,
  },
  s08: {
    systemPrompt:
      "You are a helpful coding assistant with background execution. Use the background tool for long-running commands. You'll be notified when they complete so you can continue other work.",
    tools: [...MULTI_TOOLS, TASK_MANAGER_TOOL, BACKGROUND_TOOL],
    model: MODEL,
  },
  s09: {
    systemPrompt:
      "You are a team lead agent. Spawn teammates for parallel work and coordinate via async messages. Each teammate has a JSONL inbox for reliable communication.",
    tools: [...MULTI_TOOLS, TASK_MANAGER_TOOL, SPAWN_TEAMMATE_TOOL, SEND_MESSAGE_TOOL],
    model: MODEL,
  },
  s10: {
    systemPrompt:
      "You are a team lead agent with protocol support. Use shutdown_teammate for graceful lifecycle control. Teammates can submit plans for your approval before executing.",
    tools: [...MULTI_TOOLS, TASK_MANAGER_TOOL, SPAWN_TEAMMATE_TOOL, SEND_MESSAGE_TOOL, SHUTDOWN_TOOL],
    model: MODEL,
  },
  s11: {
    systemPrompt:
      "You are an autonomous team lead. Create tasks on a shared board and spawn teammates. Teammates auto-claim unowned tasks via idle cycle polling. Minimal micromanagement needed.",
    tools: [...MULTI_TOOLS, TASK_MANAGER_TOOL, SPAWN_TEAMMATE_TOOL, SEND_MESSAGE_TOOL, SHUTDOWN_TOOL, CLAIM_TASK_TOOL],
    model: MODEL,
  },
};

export function getPlaygroundConfig(version: string): PlaygroundConfig {
  return PLAYGROUND_CONFIGS[version] || PLAYGROUND_CONFIGS["s02"];
}
