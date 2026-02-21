import {
  BaseAgent,
  BASH_TOOL,
  READ_FILE_TOOL,
  WRITE_FILE_TOOL,
  EDIT_FILE_TOOL,
  createMessage,
  type AgentConfig,
  type AgentState,
  type Message,
  type ContentBlock,
  type ToolDefinition,
  type ToolResultBlock,
  type ToolUseBlock,
} from "./shared";

type HandoffStatus = "Success" | "PartialFailure" | "Failed" | "Blocked";

interface Handoff {
  agent_id: string;
  task_id: string;
  status: HandoffStatus;
  diff: Record<string, { before: string; after: string }>;
  narrative: string;
  artifacts: string[];
  metrics: {
    wall_time: number;
    tokens_used: number;
    attempts: number;
    files_modified: number;
  };
}

interface WorkerState {
  name: string;
  status: "idle" | "working" | "shutdown";
  taskId: string;
  task: string;
}

interface WorkerRuntime {
  taskId: string;
  startedAt: number;
  attempts: number;
  turns: number;
  tokensUsed: number;
  diff: Record<string, { before: string; after: string }>;
  artifacts: string[];
  errors: string[];
  submitted: boolean;
  lastText: string;
}

const PLANNER_SYSTEM = [
  "You are a PLANNER.",
  "You decompose and delegate.",
  "You NEVER write code.",
  "If implementation is needed, spawn a worker.",
].join("\n");

const WORKER_SYSTEM = (name: string, planner: string) =>
  [
    `You are WORKER '${name}' for planner '${planner}'.`,
    "You execute a single assigned task.",
    "Write code and submit handoff when done.",
    "You do NOT decompose or delegate.",
    "You do NOT spawn workers.",
  ].join("\n");

export class PlannerWorkerSplitAgent extends BaseAgent {
  private plannerName: string;
  private workers = new Map<string, WorkerState>();
  private runtimes = new Map<string, WorkerRuntime>();
  private handoffs: Handoff[] = [];

  constructor(config: AgentConfig & { plannerName?: string }) {
    super(config);
    this.plannerName = config.plannerName ?? "planner";
    this.seedPlannerScratchpad();
  }

  private plannerScratchpadPath(): string {
    return `.scratchpad/${this.plannerName}.md`;
  }

  private workerScratchpadPath(worker: string): string {
    return `.scratchpad/${worker}.md`;
  }

  private inboxPath(name: string): string {
    return `.team/inbox/${name}.jsonl`;
  }

  private seedPlannerScratchpad(): void {
    if (this.toolExecutor.fs.getFile(this.plannerScratchpadPath())) return;
    this.toolExecutor.fs.writeFile(
      this.plannerScratchpadPath(),
      [
        `# Planner Scratchpad (${this.plannerName})`,
        "",
        "## Role Constraint",
        "- I NEVER write code.",
        "- I only decompose, delegate, and review handoffs.",
        "",
        "## Open Work",
        "- none",
      ].join("\n")
    );
  }

  private createRuntime(taskId: string): WorkerRuntime {
    return {
      taskId,
      startedAt: Date.now(),
      attempts: 0,
      turns: 0,
      tokensUsed: 0,
      diff: {},
      artifacts: [],
      errors: [],
      submitted: false,
      lastText: "",
    };
  }

  private nextWorkerName(): string {
    let idx = this.workers.size + 1;
    while (this.workers.has(`worker-${idx}`)) idx += 1;
    return `worker-${idx}`;
  }

  private appendInbox(to: string, payload: Record<string, unknown>): void {
    const path = this.inboxPath(to);
    const prev = this.toolExecutor.fs.getFile(path) ?? "";
    this.toolExecutor.fs.writeFile(path, `${prev}${JSON.stringify(payload)}\n`);
  }

  private readAndDrainInbox(name: string): string {
    const path = this.inboxPath(name);
    const raw = this.toolExecutor.fs.getFile(path);
    if (!raw || !raw.trim()) return "[]";
    this.toolExecutor.fs.writeFile(path, "");
    return raw.trim();
  }

  private rewritePlannerScratchpad(content: string): string {
    return this.toolExecutor.fs.writeFile(this.plannerScratchpadPath(), content);
  }

  private rewriteWorkerScratchpad(worker: string, content: string): string {
    return this.toolExecutor.fs.writeFile(this.workerScratchpadPath(worker), content);
  }

  private seedWorkerScratchpad(worker: string, task: string): void {
    this.rewriteWorkerScratchpad(
      worker,
      [
        `# Worker Scratchpad (${worker})`,
        "",
        "## Role Constraint",
        "- I execute tasks and submit handoff.",
        "- I do NOT decompose or delegate.",
        "",
        "## Assigned Task",
        `- ${task}`,
      ].join("\n")
    );
  }

  private updateDiff(worker: string, path: string, before: string, after: string): void {
    const rt = this.runtimes.get(worker);
    if (!rt) return;
    if (rt.diff[path]) {
      rt.diff[path] = { before: rt.diff[path].before, after };
    } else {
      rt.diff[path] = { before, after };
    }
  }

  private executeWorkerTool(worker: string, block: ToolUseBlock): ToolResultBlock {
    const rt = this.runtimes.get(worker);
    if (!rt) {
      return {
        type: "tool_result",
        tool_use_id: block.id,
        content: `Error: runtime missing for ${worker}`,
        is_error: true,
      };
    }

    if (block.name === "rewrite_scratchpad") {
      const content = String((block.input as Record<string, unknown>).content ?? "");
      const result = this.rewriteWorkerScratchpad(worker, content);
      return { type: "tool_result", tool_use_id: block.id, content: result };
    }

    if (block.name === "submit_handoff") {
      return {
        type: "tool_result",
        tool_use_id: block.id,
        content: this.submitHandoff(worker, block.input as Record<string, unknown>),
      };
    }

    if (block.name === "write_file") {
      const input = block.input as Record<string, unknown>;
      const path = String(input.path ?? input.file_path ?? "");
      const content = String(input.content ?? "");
      const before = this.toolExecutor.fs.getFile(path) ?? "";
      const result = this.toolExecutor.execute({
        ...block,
        input: { file_path: path, content },
      });
      const after = this.toolExecutor.fs.getFile(path) ?? "";
      if (!result.is_error) {
        this.updateDiff(worker, path, before, after);
        rt.artifacts.push(path);
      } else {
        rt.errors.push(String(result.content));
      }
      return result;
    }

    if (block.name === "edit_file") {
      const input = block.input as Record<string, unknown>;
      const path = String(input.path ?? input.file_path ?? "");
      const oldText = String(input.old_text ?? input.old_string ?? "");
      const newText = String(input.new_text ?? input.new_string ?? "");
      const before = this.toolExecutor.fs.getFile(path);
      const result = this.toolExecutor.execute({
        ...block,
        input: { file_path: path, old_string: oldText, new_string: newText },
      });
      const after = this.toolExecutor.fs.getFile(path);
      if (!result.is_error && before !== undefined && after !== undefined) {
        this.updateDiff(worker, path, before, after);
        rt.artifacts.push(path);
      } else if (result.is_error) {
        rt.errors.push(String(result.content));
      }
      return result;
    }

    const result = this.toolExecutor.execute(block);
    if (result.is_error) rt.errors.push(String(result.content));
    return result;
  }

  private inferHandoffStatus(worker: string): HandoffStatus {
    const rt = this.runtimes.get(worker);
    if (!rt) return "Failed";
    const modified = Object.keys(rt.diff).length;
    if (rt.errors.length === 0) return "Success";
    if (rt.errors.length > 0 && modified > 0) return "PartialFailure";
    const merged = rt.errors.join("\n").toLowerCase();
    if (merged.includes("not found") || merged.includes("blocked") || merged.includes("permission")) {
      return "Blocked";
    }
    return "Failed";
  }

  private submitHandoff(worker: string, input: Record<string, unknown>): string {
    const rt = this.runtimes.get(worker);
    if (!rt) return `Error: runtime missing for ${worker}`;
    if (rt.submitted) return `Handoff already submitted for task ${rt.taskId}`;

    const requested = input.status;
    const status: HandoffStatus =
      requested === "Success" || requested === "PartialFailure" || requested === "Failed" || requested === "Blocked"
        ? requested
        : this.inferHandoffStatus(worker);

    const narrativeInput = typeof input.narrative === "string" ? input.narrative.trim() : "";
    const narrative =
      narrativeInput.length > 0
        ? narrativeInput
        : [
            `Worker ${worker} completed task ${String(input.task_id ?? rt.taskId)} with status ${status}.`,
            `Changed files: ${Object.keys(rt.diff).join(", ") || "none"}.`,
            "Next step: planner reviews handoff and decides follow-up.",
          ].join("\n");

    const extraArtifacts = Array.isArray(input.artifacts)
      ? input.artifacts.filter((a): a is string => typeof a === "string")
      : [];

    const artifacts = Array.from(new Set([...rt.artifacts, ...extraArtifacts]));

    const handoff: Handoff = {
      agent_id: worker,
      task_id: String(input.task_id ?? rt.taskId),
      status,
      diff: { ...rt.diff },
      narrative,
      artifacts,
      metrics: {
        wall_time: (Date.now() - rt.startedAt) / 1000,
        tokens_used: rt.tokensUsed,
        attempts: rt.attempts,
        files_modified: Object.keys(rt.diff).length,
      },
    };

    this.handoffs.push(handoff);
    rt.submitted = true;

    this.appendInbox(this.plannerName, {
      type: "handoff",
      from: worker,
      to: this.plannerName,
      content: handoff.narrative,
      handoff,
      timestamp: Date.now(),
    });

    return `Submitted handoff for task ${handoff.task_id} (${handoff.status})`;
  }

  private reviewHandoffs(input: Record<string, unknown>): string {
    const taskId = input.task_id ? String(input.task_id) : undefined;
    const agentId = input.agent_id ? String(input.agent_id) : undefined;
    const includeDiff = Boolean(input.include_diff);

    const selected = this.handoffs.filter((h) => {
      if (taskId && h.task_id !== taskId) return false;
      if (agentId && h.agent_id !== agentId) return false;
      return true;
    });

    if (selected.length === 0) return "No handoffs found.";

    return JSON.stringify(
      selected.map((h) => {
        const base = {
          agent_id: h.agent_id,
          task_id: h.task_id,
          status: h.status,
          narrative: h.narrative,
          artifacts: h.artifacts,
          metrics: h.metrics,
        };
        return includeDiff ? { ...base, diff: h.diff } : base;
      }),
      null,
      2
    );
  }

  private async runWorker(worker: string, task: string, taskId: string): Promise<void> {
    const state = this.workers.get(worker);
    const rt = this.runtimes.get(worker);
    if (!state || !rt) return;

    const workerMessages: Message[] = [
      {
        role: "user",
        content: `<assignment>task_id=${taskId}\n${task}</assignment>`,
      },
      {
        role: "user",
        content: `<scratchpad>${this.toolExecutor.fs.getFile(this.workerScratchpadPath(worker)) || "(empty)"}</scratchpad>`,
      },
    ];

    const maxTurns = 20;

    for (let i = 0; i < maxTurns; i += 1) {
      const response = await createMessage({
        apiKey: this.config.apiKey,
        model: this.config.model,
        system: WORKER_SYSTEM(worker, this.plannerName),
        messages: workerMessages,
        tools: this.getWorkerTools(),
      });

      this.totalInputTokens += response.usage.input_tokens;
      this.totalOutputTokens += response.usage.output_tokens;
      rt.tokensUsed += response.usage.input_tokens + response.usage.output_tokens;
      rt.attempts += 1;
      rt.turns += 1;

      workerMessages.push({ role: "assistant", content: response.content });

      if (response.stop_reason !== "tool_use") {
        rt.lastText = this.extractText(response.content);
        if (!rt.submitted) this.submitHandoff(worker, { task_id: taskId });
        break;
      }

      const toolResults: ToolResultBlock[] = [];
      for (const block of response.content) {
        if (block.type !== "tool_use") continue;
        const result = this.executeWorkerTool(worker, block as ToolUseBlock);
        toolResults.push(result);
      }
      workerMessages.push({ role: "user", content: toolResults });

      if (rt.submitted) break;
    }

    if (!rt.submitted) this.submitHandoff(worker, { task_id: taskId });

    state.status = "idle";
  }

  private async spawnWorker(input: Record<string, unknown>): Promise<string> {
    const task = String(input.task ?? "").trim();
    if (!task) return "Error: task is required";

    const name =
      typeof input.name === "string" && input.name.trim().length > 0
        ? input.name.trim()
        : this.nextWorkerName();
    const taskId =
      typeof input.task_id === "string" && input.task_id.trim().length > 0
        ? input.task_id.trim()
        : `task-${Date.now()}`;

    const existing = this.workers.get(name);
    if (existing && existing.status === "working") {
      return `Error: '${name}' is currently working`;
    }

    this.workers.set(name, {
      name,
      status: "working",
      task,
      taskId,
    });
    this.runtimes.set(name, this.createRuntime(taskId));
    this.seedWorkerScratchpad(name, task);

    // Fresh context starts inside runWorker with assignment + worker scratchpad.
    await this.runWorker(name, task, taskId);
    return `Spawned '${name}' with task_id=${taskId}`;
  }

  protected override async processToolCalls(content: ContentBlock[]): Promise<ToolResultBlock[]> {
    const results: ToolResultBlock[] = [];

    for (const block of content) {
      if (block.type !== "tool_use") continue;
      this.emit("tool_call", { name: block.name, input: block.input });

      let result: ToolResultBlock;

      if (block.name === "spawn_worker") {
        const output = await this.spawnWorker(block.input as Record<string, unknown>);
        result = { type: "tool_result", tool_use_id: block.id, content: output };
      } else if (block.name === "review_handoff") {
        const output = this.reviewHandoffs(block.input as Record<string, unknown>);
        result = { type: "tool_result", tool_use_id: block.id, content: output };
      } else if (block.name === "rewrite_scratchpad") {
        const contentText = String((block.input as Record<string, unknown>).content ?? "");
        const output = this.rewritePlannerScratchpad(contentText);
        result = { type: "tool_result", tool_use_id: block.id, content: output };
      } else if (block.name === "send_message") {
        const input = block.input as Record<string, unknown>;
        const to = String(input.to ?? "");
        const contentText = String(input.content ?? "");
        if (!to) {
          result = {
            type: "tool_result",
            tool_use_id: block.id,
            content: "Error: missing to",
            is_error: true,
          };
        } else {
          this.appendInbox(to, {
            type: String(input.msg_type ?? "message"),
            from: this.plannerName,
            to,
            content: contentText,
            timestamp: Date.now(),
          });
          result = { type: "tool_result", tool_use_id: block.id, content: `Message sent to ${to}` };
        }
      } else if (block.name === "read_inbox") {
        const output = this.readAndDrainInbox(this.plannerName);
        result = { type: "tool_result", tool_use_id: block.id, content: output };
      } else if (block.name === "list_workers") {
        const output =
          this.workers.size === 0
            ? "No workers."
            : Array.from(this.workers.values())
                .map((w) => `- ${w.name}: status=${w.status} task=${w.taskId}`)
                .join("\n");
        result = { type: "tool_result", tool_use_id: block.id, content: output };
      } else {
        result = {
          type: "tool_result",
          tool_use_id: block.id,
          content: `Error: tool not allowed for planner: ${block.name}`,
          is_error: true,
        };
      }

      results.push(result);
      this.emit("tool_result", {
        tool_use_id: block.id,
        name: block.name,
        content: result.content,
        is_error: result.is_error,
      });
    }

    return results;
  }

  async run(userMessage: string): Promise<string> {
    this.aborted = false;
    this.messages.push({ role: "user", content: userMessage });
    this.emit("state_change");

    let finalText = "";

    while (this.loopIteration < (this.config.maxIterations || 10)) {
      if (this.aborted) break;
      this.loopIteration += 1;

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

  private getWorkerTools(): ToolDefinition[] {
    return [
      BASH_TOOL,
      READ_FILE_TOOL,
      WRITE_FILE_TOOL,
      EDIT_FILE_TOOL,
      {
        name: "submit_handoff",
        description: "Submit structured handoff to planner.",
        input_schema: {
          type: "object",
          properties: {
            task_id: { type: "string" },
            status: { type: "string", enum: ["Success", "PartialFailure", "Failed", "Blocked"] },
            narrative: { type: "string" },
            artifacts: { type: "array", items: { type: "string" } },
          },
        },
      },
      {
        name: "rewrite_scratchpad",
        description: "Rewrite worker scratchpad by replacement.",
        input_schema: {
          type: "object",
          properties: {
            content: { type: "string" },
          },
          required: ["content"],
        },
      },
    ];
  }

  getTools(): ToolDefinition[] {
    return [
      {
        name: "spawn_worker",
        description: "Spawn a worker for one concrete task.",
        input_schema: {
          type: "object",
          properties: {
            name: { type: "string" },
            task: { type: "string" },
            task_id: { type: "string" },
          },
          required: ["task"],
        },
      },
      {
        name: "review_handoff",
        description: "Review worker handoffs by task/agent.",
        input_schema: {
          type: "object",
          properties: {
            task_id: { type: "string" },
            agent_id: { type: "string" },
            include_diff: { type: "boolean" },
          },
        },
      },
      {
        name: "rewrite_scratchpad",
        description: "Rewrite planner scratchpad by replacement.",
        input_schema: {
          type: "object",
          properties: { content: { type: "string" } },
          required: ["content"],
        },
      },
      {
        name: "send_message",
        description: "Send message to worker inbox.",
        input_schema: {
          type: "object",
          properties: {
            to: { type: "string" },
            content: { type: "string" },
            msg_type: { type: "string", enum: ["message", "broadcast"] },
          },
          required: ["to", "content"],
        },
      },
      {
        name: "read_inbox",
        description: "Read and drain planner inbox.",
        input_schema: { type: "object", properties: {} },
      },
      {
        name: "list_workers",
        description: "List worker status.",
        input_schema: { type: "object", properties: {} },
      },
    ];
  }

  getSystemPrompt(): string {
    return PLANNER_SYSTEM;
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      teammates: Array.from(this.workers.values()).map((w) => ({
        name: w.name,
        status: w.status,
        currentTask: w.task,
      })),
      handoffs: this.handoffs,
      scratchpads: {
        [this.plannerName]: this.toolExecutor.fs.getFile(this.plannerScratchpadPath()) ?? "",
        ...Array.from(this.workers.keys()).reduce<Record<string, string>>((acc, worker) => {
          acc[worker] = this.toolExecutor.fs.getFile(this.workerScratchpadPath(worker)) ?? "";
          return acc;
        }, {}),
      },
    } as AgentState;
  }
}
