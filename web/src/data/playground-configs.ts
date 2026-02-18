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

export const PLAYGROUND_CONFIGS: Record<string, PlaygroundConfig> = {
  s01: {
    systemPrompt:
      "You are a helpful coding assistant. You have access to bash. Use it to help the user with their tasks. Be concise.",
    tools: [BASH_TOOL],
    model: "claude-sonnet-4-20250514",
  },
  s02: {
    systemPrompt:
      "You are a helpful coding assistant with file management tools. Use read_file to inspect files, write_file to create files, edit_file to modify files, and bash for commands.",
    tools: [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL],
    model: "claude-sonnet-4-20250514",
  },
  s03: {
    systemPrompt:
      "You are a helpful coding assistant. Before starting a complex task, outline your plan. Use the available tools to implement the plan step by step.",
    tools: [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL],
    model: "claude-sonnet-4-20250514",
  },
};

export function getPlaygroundConfig(version: string): PlaygroundConfig {
  return PLAYGROUND_CONFIGS[version] || PLAYGROUND_CONFIGS["s02"];
}
