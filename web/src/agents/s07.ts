/**
 * s07 - File-Based Tasks with Labels
 *
 * TaskManager with CRUD tools + dependency graph + labels, persisted as JSON files.
 * State survives compression because it lives outside the conversation.
 *
 *   Task lifecycle:        Dependency graph:
 *   pending                Task A (blockedBy: [])
 *     |                      |-- blocks --> Task B (blockedBy: [A])
 *     v                    A completes:
 *   in_progress              -> auto-removes A from B.blockedBy
 *     |
 *     v                    Storage:
 *   completed                .tasks/<id>.json in VirtualFS
 *
 *   Labels: string array for categorization/filtering
 *   +---------------------------------------------+
 *   | task_create  - create with subject + desc    |
 *   | task_update  - change status or blockedBy    |
 *   | task_list    - show all with deps            |
 *   | task_get     - full details by ID           |
 *   | task_add_label    - add label to task       |
 *   | task_remove_label - remove label from task   |
 *   | task_list_by_label - filter tasks by label  |
 *   +---------------------------------------------+
 *
 * Mechanism: TaskManager CRUD + deps + file persistence + labels
 * Tools: bash, read_file, write_file, edit_file, task_create,
 *        task_update, task_list, task_get, task_add_label,
 *        task_remove_label, task_list_by_label (11 total)
 * LOC target: 220
 */

import {
  BaseAgent, ToolExecutor, VirtualFS,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type AgentConfig, type AgentState, type TaskItem,
} from "./shared";

interface TaskData {
  id: string;
  subject: string;
  description: string;
  status: "pending" | "in_progress" | "completed";
  blockedBy: string[];
  labels: string[];
}

class TaskManager {
  private counter = 1;
  constructor(private fs: VirtualFS) {}

  create(subject: string, description: string, labels?: string[]): TaskData {
    const id = String(this.counter++);
    const task: TaskData = { 
      id, 
      subject, 
      description, 
      status: "pending", 
      blockedBy: [],
      labels: labels || [],
    };
    this.fs.writeFile(`.tasks/${id}.json`, JSON.stringify(task, null, 2));
    return task;
  }

  get(id: string): TaskData | null {
    const raw = this.fs.getFile(`.tasks/${id}.json`);
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return null; }
  }

  update(id: string, fields: Partial<Pick<TaskData, "status" | "blockedBy" | "labels">>): TaskData | null {
    const task = this.get(id);
    if (!task) return null;
    if (fields.status) task.status = fields.status;
    if (fields.blockedBy) task.blockedBy = fields.blockedBy;
    if (fields.labels) task.labels = fields.labels;
    if (task.status === "completed") this.clearDep(id);
    this.fs.writeFile(`.tasks/${id}.json`, JSON.stringify(task, null, 2));
    return task;
  }

  addLabel(id: string, label: string): TaskData | null {
    const task = this.get(id);
    if (!task) return null;
    if (!task.labels.includes(label)) {
      task.labels.push(label);
      this.fs.writeFile(`.tasks/${id}.json`, JSON.stringify(task, null, 2));
    }
    return task;
  }

  removeLabel(id: string, label: string): TaskData | null {
    const task = this.get(id);
    if (!task) return null;
    task.labels = task.labels.filter(l => l !== label);
    this.fs.writeFile(`.tasks/${id}.json`, JSON.stringify(task, null, 2));
    return task;
  }

  list(): TaskData[] {
    const tasks: TaskData[] = [];
    for (const path of this.fs.listFiles()) {
      if (!path.startsWith(".tasks/") || !path.endsWith(".json")) continue;
      const raw = this.fs.getFile(path);
      if (!raw) continue;
      try { tasks.push(JSON.parse(raw)); } catch { /* skip */ }
    }
    return tasks.sort((a, b) => Number(a.id) - Number(b.id));
  }

  listByLabel(label: string): TaskData[] {
    return this.list().filter(t => t.labels.includes(label));
  }

  getAllLabels(): string[] {
    const labels = new Set<string>();
    for (const task of this.list()) {
      for (const label of task.labels) {
        labels.add(label);
      }
    }
    return Array.from(labels).sort();
  }

  private clearDep(completedId: string): void {
    for (const path of this.fs.listFiles()) {
      if (!path.startsWith(".tasks/") || !path.endsWith(".json")) continue;
      const raw = this.fs.getFile(path);
      if (!raw) continue;
      try {
        const t: TaskData = JSON.parse(raw);
        if (t.blockedBy.includes(completedId)) {
          t.blockedBy = t.blockedBy.filter((d) => d !== completedId);
          this.fs.writeFile(path, JSON.stringify(t, null, 2));
        }
      } catch { /* skip */ }
    }
  }
}

const TASK_CREATE: ToolDefinition = {
  name: "task_create", description: "Create a new task with optional labels.",
  input_schema: { type: "object", properties: {
    subject: { type: "string", description: "Brief imperative title" },
    description: { type: "string", description: "Detailed description" },
    labels: { type: "array", items: { type: "string" }, description: "Optional labels (e.g., bug, feature, urgent)" },
  }, required: ["subject", "description"] },
};
const TASK_UPDATE: ToolDefinition = {
  name: "task_update", description: "Update task status, dependencies, or labels. Completing auto-unblocks dependents.",
  input_schema: { type: "object", properties: {
    id: { type: "string" }, 
    status: { type: "string" }, 
    blockedBy: { type: "array" },
    labels: { type: "array", items: { type: "string" } },
  }, required: ["id"] },
};
const TASK_LIST: ToolDefinition = {
  name: "task_list", description: "List all tasks with status, dependencies, and labels.",
  input_schema: { type: "object", properties: {}, required: [] },
};
const TASK_GET: ToolDefinition = {
  name: "task_get", description: "Get full details of a task by ID.",
  input_schema: { type: "object", properties: { id: { type: "string" } }, required: ["id"] },
};
const TASK_ADD_LABEL: ToolDefinition = {
  name: "task_add_label", description: "Add a label to a task.",
  input_schema: { type: "object", properties: {
    id: { type: "string", description: "Task ID" },
    label: { type: "string", description: "Label to add (e.g., bug, feature, urgent)" },
  }, required: ["id", "label"] },
};
const TASK_REMOVE_LABEL: ToolDefinition = {
  name: "task_remove_label", description: "Remove a label from a task.",
  input_schema: { type: "object", properties: {
    id: { type: "string", description: "Task ID" },
    label: { type: "string", description: "Label to remove" },
  }, required: ["id", "label"] },
};
const TASK_LIST_BY_LABEL: ToolDefinition = {
  name: "task_list_by_label", description: "List all tasks filtered by a specific label.",
  input_schema: { type: "object", properties: {
    label: { type: "string", description: "Label to filter by" },
  }, required: ["label"] },
};

export class TasksAgent extends BaseAgent {
  private taskManager: TaskManager;

  constructor(config: AgentConfig, toolExecutor?: ToolExecutor) {
    const exec = toolExecutor || new ToolExecutor();
    super(config, exec);
    this.taskManager = new TaskManager(exec.fs);
    this.toolExecutor.registerTool("task_create", (input) => {
      const labels = input.labels as string[] | undefined;
      return JSON.stringify(this.taskManager.create(input.subject as string, input.description as string, labels), null, 2);
    });
    this.toolExecutor.registerTool("task_update", (input) => {
      const fields: Partial<Pick<TaskData, "status" | "blockedBy" | "labels">> = {};
      if (input.status) fields.status = input.status as TaskData["status"];
      if (input.blockedBy) fields.blockedBy = input.blockedBy as string[];
      if (input.labels) fields.labels = input.labels as string[];
      const task = this.taskManager.update(input.id as string, fields);
      return task ? JSON.stringify(task, null, 2) : `Error: Task ${input.id} not found`;
    });
    this.toolExecutor.registerTool("task_list", () => {
      const tasks = this.taskManager.list();
      if (tasks.length === 0) return "No tasks.";
      return tasks.map((t) => {
        const icon = { completed: "[x]", in_progress: "[>]", pending: "[ ]" }[t.status];
        const dep = t.blockedBy.length > 0 ? ` (blocked by: ${t.blockedBy.join(", ")})` : "";
        const labels = t.labels.length > 0 ? ` [${t.labels.join(", ")}]` : "";
        return `#${t.id}. ${icon} ${t.subject}${labels}${dep}`;
      }).join("\n");
    });
    this.toolExecutor.registerTool("task_get", (input) => {
      const task = this.taskManager.get(input.id as string);
      return task ? JSON.stringify(task, null, 2) : `Error: Task ${input.id} not found`;
    });
    this.toolExecutor.registerTool("task_add_label", (input) => {
      const task = this.taskManager.addLabel(input.id as string, input.label as string);
      return task ? JSON.stringify(task, null, 2) : `Error: Task ${input.id} not found`;
    });
    this.toolExecutor.registerTool("task_remove_label", (input) => {
      const task = this.taskManager.removeLabel(input.id as string, input.label as string);
      return task ? JSON.stringify(task, null, 2) : `Error: Task ${input.id} not found`;
    });
    this.toolExecutor.registerTool("task_list_by_label", (input) => {
      const tasks = this.taskManager.listByLabel(input.label as string);
      if (tasks.length === 0) return `No tasks with label "${input.label}".`;
      return tasks.map((t) => {
        const icon = { completed: "[x]", in_progress: "[>]", pending: "[ ]" }[t.status];
        const dep = t.blockedBy.length > 0 ? ` (blocked by: ${t.blockedBy.join(", ")})` : "";
        return `#${t.id}. ${icon} ${t.subject}${dep}`;
      }).join("\n");
    });
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
      TASK_CREATE, TASK_UPDATE, TASK_LIST, TASK_GET, 
      TASK_ADD_LABEL, TASK_REMOVE_LABEL, TASK_LIST_BY_LABEL];
  }

  getSystemPrompt(): string {
    return "You are a coding agent with persistent task management. " +
      "Use task_create to plan work with optional labels (e.g., labels: [\"bug\", \"urgent\"]), " +
      "task_update to track progress, task_add_label/task_remove_label to manage labels. " +
      "Use task_list_by_label to filter tasks. " +
      "Tasks persist across compression. Use blockedBy for ordering.";
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      tasks: this.taskManager.list().map((t): TaskItem => ({
        id: t.id, 
        subject: t.subject, 
        status: t.status, 
        blockedBy: t.blockedBy,
        labels: t.labels,
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
