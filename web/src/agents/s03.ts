/**
 * s03 - Structured Planning (Todos)
 *
 * Adds agent-writable state: a TodoManager the model updates via tool calls.
 * A nag reminder is injected if the model forgets to update todos.
 *
 *   +-- Agent Loop (same as s02) --------+
 *   |                                     |
 *   |  beforeLLMCall():                   |
 *   |    if roundsWithoutTodo >= 3:       |
 *   |      inject <reminder> into msgs    |
 *   |                                     |
 *   |  tools: [bash, read, write, edit,   |
 *   |          todo]                      |
 *   |                                     |
 *   |  TodoManager state:                 |
 *   |    items[] with constraints:        |
 *   |    - max 20 items                   |
 *   |    - single in_progress             |
 *   +------------------------------------+
 *
 * Mechanism: TodoManager + nag reminder injection
 * Tools: bash, read_file, write_file, edit_file, todo (5 total)
 * LOC target: 155
 */

import {
  BaseAgent,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type ToolUseBlock, type ToolResultBlock,
  type AgentConfig, type AgentState, type TodoItem,
} from "./shared";

interface TodoEntry {
  content: string;
  status: "pending" | "in_progress" | "completed";
  activeForm: string;
}

class TodoManager {
  items: TodoEntry[] = [];

  update(rawItems: Record<string, unknown>[]): string {
    const validated: TodoEntry[] = [];
    let inProgressCount = 0;
    for (let i = 0; i < rawItems.length; i++) {
      const raw = rawItems[i];
      const content = String(raw.content ?? "").trim();
      const status = String(raw.status ?? "pending").toLowerCase();
      const activeForm = String(raw.activeForm ?? "").trim();
      if (!content) throw new Error(`Item ${i}: content required`);
      if (!activeForm) throw new Error(`Item ${i}: activeForm required`);
      if (!["pending", "in_progress", "completed"].includes(status)) {
        throw new Error(`Item ${i}: invalid status '${status}'`);
      }
      if (status === "in_progress") inProgressCount++;
      validated.push({ content, status: status as TodoEntry["status"], activeForm });
    }
    if (validated.length > 20) throw new Error("Max 20 todos allowed");
    if (inProgressCount > 1) throw new Error("Only one task can be in_progress");
    this.items = validated;
    return this.render();
  }

  render(): string {
    if (this.items.length === 0) return "No todos.";
    const lines = this.items.map((item) => {
      if (item.status === "completed") return `[x] ${item.content}`;
      if (item.status === "in_progress") return `[>] ${item.content} <- ${item.activeForm}`;
      return `[ ] ${item.content}`;
    });
    const done = this.items.filter((t) => t.status === "completed").length;
    lines.push(`\n(${done}/${this.items.length} completed)`);
    return lines.join("\n");
  }

  toTodoItems(): TodoItem[] {
    return this.items.map((item, i) => ({
      id: `todo-${i}`,
      text: item.content,
      done: item.status === "completed",
    }));
  }
}

const TODO_TOOL: ToolDefinition = {
  name: "todo",
  description: "Update the task list. Send a complete replacement list to track progress.",
  input_schema: {
    type: "object",
    properties: {
      items: {
        type: "array",
        description: "Complete list of tasks (replaces existing)",
        items: {
          type: "object",
          properties: {
            content: { type: "string", description: "Task description" },
            status: { type: "string", enum: ["pending", "in_progress", "completed"] },
            activeForm: { type: "string", description: "Present tense, e.g. 'Reading files'" },
          },
          required: ["content", "status", "activeForm"],
        },
      },
    },
    required: ["items"],
  },
};

export class TodoAgent extends BaseAgent {
  private todoManager = new TodoManager();
  private roundsWithoutTodo = 0;

  constructor(config: AgentConfig) {
    super(config);
    this.toolExecutor.registerTool("todo", (input) => {
      return this.todoManager.update(input.items as Record<string, unknown>[]);
    });
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, TODO_TOOL];
  }

  getSystemPrompt(): string {
    return [
      "You are a coding agent with structured planning.",
      "Loop: plan -> act with tools -> update todos -> report.",
      "Use the todo tool to track multi-step tasks.",
      "Mark tasks in_progress before starting, completed when done.",
    ].join("\n");
  }

  getState(): AgentState {
    return { ...super.getState(), todos: this.todoManager.toTodoItems() };
  }

  async run(userMessage: string): Promise<string> {
    this.aborted = false;
    this.messages.push({ role: "user", content: userMessage });
    this.emit("state_change");

    let finalText = "";

    while (this.loopIteration < (this.config.maxIterations || 10)) {
      if (this.aborted) break;
      this.loopIteration++;

      // -- NAG REMINDER: inject if model hasn't updated todos recently --
      if (this.todoManager.items.length > 0 && this.roundsWithoutTodo >= 3) {
        const reminder = `<reminder>Current todos:\n${this.todoManager.render()}\nPlease update todos.</reminder>`;
        const lastMsg = this.messages[this.messages.length - 1];
        if (lastMsg && lastMsg.role === "user" && Array.isArray(lastMsg.content)) {
          (lastMsg.content as unknown as Array<Record<string, unknown>>).push({
            type: "text", text: reminder,
          });
        }
      }

      this.emit("llm_request", { iteration: this.loopIteration });
      const response = await createMessage({
        apiKey: this.config.apiKey,
        model: this.config.model,
        system: this.getSystemPrompt(),
        messages: this.messages,
        tools: this.getTools(),
      });
      this.totalInputTokens += response.usage.input_tokens;
      this.totalOutputTokens += response.usage.output_tokens;
      this.emit("llm_response", { stopReason: response.stop_reason });

      this.messages.push({ role: "assistant", content: response.content });
      this.emit("state_change");

      if (response.stop_reason !== "tool_use") {
        finalText = this.extractText(response.content);
        break;
      }

      const toolResults = await this.processToolCalls(response.content);
      this.messages.push({ role: "user", content: toolResults });

      // Track whether todo tool was used this iteration
      const usedTodo = (response.content as ToolUseBlock[]).some(
        (b) => b.type === "tool_use" && b.name === "todo"
      );
      this.roundsWithoutTodo = usedTodo ? 0 : this.roundsWithoutTodo + 1;

      this.emit("state_change");
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }
}
