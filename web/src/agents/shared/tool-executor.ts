/**
 * Tool executor for browser-based agents.
 *
 * Wraps VirtualFS to provide sandboxed tool execution.
 * Each agent version can extend this with additional tools.
 *
 *   ToolUseBlock ──> ToolExecutor.execute() ──> ToolResultBlock
 *                         │
 *                    VirtualFS handles:
 *                      bash, read_file, write_file, edit_file
 */

import type { ToolUseBlock, ToolResultBlock, ToolDefinition } from "./types";

export class VirtualFS {
  private files: Map<string, string> = new Map();

  constructor(initialFiles?: Record<string, string>) {
    if (initialFiles) {
      for (const [path, content] of Object.entries(initialFiles)) {
        this.files.set(path, content);
      }
    } else {
      this.files.set("README.md", "# Project\n\nWelcome to the sandbox.\n");
    }
  }

  readFile(path: string): string {
    const content = this.files.get(path);
    if (content === undefined) return `Error: File not found: ${path}`;
    return content;
  }

  writeFile(path: string, content: string): string {
    this.files.set(path, content);
    return `File written: ${path}`;
  }

  editFile(path: string, oldText: string, newText: string): string {
    const content = this.files.get(path);
    if (content === undefined) return `Error: File not found: ${path}`;
    if (!content.includes(oldText)) return `Error: old_text not found in ${path}`;
    this.files.set(path, content.replace(oldText, newText));
    return `File edited: ${path}`;
  }

  bash(command: string): string {
    if (command.startsWith("cat ")) {
      return this.readFile(command.slice(4).trim());
    }
    if (command.startsWith("ls")) {
      return Array.from(this.files.keys()).join("\n") || "(empty)";
    }
    if (command.startsWith("echo ") && command.includes(">")) {
      const parts = command.split(">");
      const content = parts[0].replace(/^echo\s+/, "").replace(/['"]/g, "").trim();
      const file = parts[1].trim();
      this.files.set(file, content + "\n");
      return "";
    }
    if (command.startsWith("mkdir")) return "";
    if (command.startsWith("rm ")) {
      const path = command.slice(3).trim().replace(/-r?f?\s*/g, "");
      this.files.delete(path);
      return "";
    }
    if (command.startsWith("python ") || command.startsWith("node ")) {
      const file = command.split(" ")[1];
      const content = this.files.get(file);
      if (!content) return `Error: File not found: ${file}`;
      return `[simulated output of ${file}]`;
    }
    return `$ ${command}\n[simulated]`;
  }

  listFiles(): string[] {
    return Array.from(this.files.keys());
  }

  getFile(path: string): string | undefined {
    return this.files.get(path);
  }

  snapshot(): Record<string, string> {
    const result: Record<string, string> = {};
    for (const [k, v] of this.files) {
      result[k] = v;
    }
    return result;
  }
}

export class ToolExecutor {
  readonly fs: VirtualFS;
  private customHandlers: Map<string, (input: Record<string, unknown>) => string> = new Map();

  constructor(fs?: VirtualFS) {
    this.fs = fs || new VirtualFS();
  }

  registerTool(name: string, handler: (input: Record<string, unknown>) => string): void {
    this.customHandlers.set(name, handler);
  }

  execute(block: ToolUseBlock): ToolResultBlock {
    const input = block.input as Record<string, string>;
    let result: string;

    try {
      // Check custom handlers first
      const custom = this.customHandlers.get(block.name);
      if (custom) {
        result = custom(block.input);
      } else {
        // Built-in tools
        switch (block.name) {
          case "bash":
            result = this.fs.bash(input.command || "");
            break;
          case "read_file":
            result = this.fs.readFile(input.path || input.file_path || "");
            break;
          case "write_file":
            result = this.fs.writeFile(
              input.path || input.file_path || "",
              input.content || ""
            );
            break;
          case "edit_file":
            result = this.fs.editFile(
              input.path || input.file_path || "",
              input.old_text || input.old_string || "",
              input.new_text || input.new_string || ""
            );
            break;
          default:
            result = `[tool ${block.name} not implemented]`;
        }
      }
    } catch (err) {
      result = `Error: ${err instanceof Error ? err.message : String(err)}`;
      return { type: "tool_result", tool_use_id: block.id, content: result, is_error: true };
    }

    return { type: "tool_result", tool_use_id: block.id, content: result };
  }
}

// -- Standard tool definitions --

export const BASH_TOOL: ToolDefinition = {
  name: "bash",
  description: "Execute a bash command in the sandbox.",
  input_schema: {
    type: "object",
    properties: {
      command: { type: "string", description: "The bash command to execute" },
    },
    required: ["command"],
  },
};

export const READ_FILE_TOOL: ToolDefinition = {
  name: "read_file",
  description: "Read the contents of a file.",
  input_schema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to the file to read" },
    },
    required: ["file_path"],
  },
};

export const WRITE_FILE_TOOL: ToolDefinition = {
  name: "write_file",
  description: "Write content to a file (creates or overwrites).",
  input_schema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to the file to write" },
      content: { type: "string", description: "Content to write" },
    },
    required: ["file_path", "content"],
  },
};

export const EDIT_FILE_TOOL: ToolDefinition = {
  name: "edit_file",
  description: "Replace text in an existing file.",
  input_schema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to the file to edit" },
      old_string: { type: "string", description: "Text to find and replace" },
      new_string: { type: "string", description: "Replacement text" },
    },
    required: ["file_path", "old_string", "new_string"],
  },
};
