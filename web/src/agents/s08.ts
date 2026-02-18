/**
 * s08 - Background Execution
 *
 * BackgroundManager runs commands asynchronously via setTimeout.
 * Results queue as notifications, drained before each LLM call.
 *
 *   background_run(cmd)          setTimeout(fn)
 *     |-> returns task_id          ...executing...
 *     |   immediately              done -> notification queue
 *     v                                    |
 *   next LLM call                          |
 *   beforeLLMCall():  <--- drains ---------+
 *     inject results as user message
 *
 *   Two tools:
 *   +--------------------------------------------+
 *   | background_run   - launch async command     |
 *   | check_background - inspect task status      |
 *   +--------------------------------------------+
 *
 * Mechanism: BackgroundManager + notification queue
 * Tools: bash, read_file, write_file, edit_file,
 *        background_run, check_background (6 total)
 * LOC target: 160
 */

import {
  BaseAgent, ToolExecutor,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type AgentConfig, type AgentState,
} from "./shared";

interface BgTask {
  id: string;
  command: string;
  status: "running" | "done" | "error";
  output: string;
}

interface Notification {
  taskId: string;
  status: string;
  output: string;
}

class BackgroundManager {
  private tasks: Map<string, BgTask> = new Map();
  private queue: Notification[] = [];
  private counter = 0;

  run(command: string, executor: ToolExecutor): string {
    const id = `bg_${++this.counter}`;
    const task: BgTask = { id, command, status: "running", output: "" };
    this.tasks.set(id, task);
    setTimeout(() => {
      try {
        task.output = executor.fs.bash(command);
        task.status = "done";
      } catch (err) {
        task.output = `Error: ${err instanceof Error ? err.message : String(err)}`;
        task.status = "error";
      }
      this.queue.push({ taskId: id, status: task.status, output: task.output.slice(0, 500) });
    }, 0);
    return id;
  }

  drain(): Notification[] {
    const pending = this.queue.slice();
    this.queue = [];
    return pending;
  }

  listTasks(): { id: string; command: string; status: "running" | "done" }[] {
    const result: { id: string; command: string; status: "running" | "done" }[] = [];
    this.tasks.forEach((task) => {
      result.push({
        id: task.id, command: task.command,
        status: task.status === "error" ? "done" : task.status,
      });
    });
    return result;
  }

  getTask(id: string): BgTask | undefined {
    return this.tasks.get(id);
  }
}

const BG_RUN_TOOL: ToolDefinition = {
  name: "background_run",
  description: "Run a bash command in background. Returns task ID immediately. " +
    "Result delivered as notification before next LLM call.",
  input_schema: {
    type: "object",
    properties: { command: { type: "string", description: "Bash command to run" } },
    required: ["command"],
  },
};

const CHECK_BG_TOOL: ToolDefinition = {
  name: "check_background",
  description: "List background tasks. Pass task_id for a specific task.",
  input_schema: {
    type: "object",
    properties: { task_id: { type: "string", description: "Specific task ID (optional)" } },
    required: [],
  },
};

export class BackgroundAgent extends BaseAgent {
  private bgManager: BackgroundManager;

  constructor(config: AgentConfig, toolExecutor?: ToolExecutor) {
    const exec = toolExecutor || new ToolExecutor();
    super(config, exec);
    this.bgManager = new BackgroundManager();
    this.toolExecutor.registerTool("background_run", (input) => {
      const cmd = input.command as string;
      const taskId = this.bgManager.run(cmd, this.toolExecutor);
      return JSON.stringify({ task_id: taskId, status: "running", command: cmd });
    });
    this.toolExecutor.registerTool("check_background", (input) => {
      if (input.task_id) {
        const task = this.bgManager.getTask(input.task_id as string);
        if (!task) return `Error: Task ${input.task_id} not found`;
        return JSON.stringify(task, null, 2);
      }
      const tasks = this.bgManager.listTasks();
      if (tasks.length === 0) return "No background tasks.";
      return tasks.map((t) => `${t.id}: [${t.status}] ${t.command}`).join("\n");
    });
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, BG_RUN_TOOL, CHECK_BG_TOOL];
  }

  getSystemPrompt(): string {
    return "You are a coding agent with background execution. " +
      "Use background_run to launch long commands without blocking. " +
      "Results are auto-delivered before your next response.";
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      backgroundThreads: this.bgManager.listTasks().map((t) => ({
        id: t.id, command: t.command, status: t.status,
      })),
    };
  }

  async run(userMessage: string): Promise<string> {
    this.aborted = false;
    this.messages.push({ role: "user", content: userMessage });
    this.emit("state_change");

    let finalText = "";

    while (this.loopIteration < (this.config.maxIterations || 10)) {
      if (this.aborted) break;
      this.loopIteration++;

      // -- DRAIN NOTIFICATION QUEUE before LLM call --
      const notifications = this.bgManager.drain();
      if (notifications.length > 0) {
        const lines = notifications.map((n) =>
          `[Background task ${n.taskId} ${n.status}]: ${n.output}`
        );
        this.messages.push({
          role: "user",
          content: `[Background task notifications]\n\n${lines.join("\n\n")}`,
        });
        this.emit("state_change");
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
      this.emit("state_change");
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }
}
