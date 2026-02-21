import {
  BaseAgent,
  createMessage,
  type AgentConfig,
  type AgentState,
  type ContentBlock,
  type Message,
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
  workspace_path: string;
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
  workspacePath: string;
}

interface WorkerRuntime {
  taskId: string;
  startedAt: number;
  attempts: number;
  turns: number;
  tokensUsed: number;
  artifacts: string[];
  errors: string[];
  submitted: boolean;
  lastText: string;
  workspacePath: string;
  workspaceCleaned: boolean;
}

const PLANNER_SYSTEM = [
  "You are a PLANNER.",
  "You decompose and delegate.",
  "You NEVER write code.",
  "Workers run inside isolated workspaces.",
  "Review worker handoffs and decide follow-up.",
].join("\n");

const WORKER_SYSTEM = (name: string, planner: string) =>
  [
    `You are WORKER '${name}' for planner '${planner}'.`,
    "You execute one assigned task.",
    "You operate only inside your own workspace.",
    "You do NOT decompose or spawn workers.",
    "Submit handoff when done.",
  ].join("\n");

class WorkerWorkspace {
  readonly workerId: string;
  readonly workspacePath: string;
  private files: Map<string, string>;
  cleaned = false;

  constructor(workerId: string, canonicalSnapshot: Record<string, string>) {
    this.workerId = workerId;
    this.workspacePath = `.workspaces/${workerId}`;
    this.files = new Map(Object.entries(canonicalSnapshot));
  }

  private assertActive(): void {
    if (this.cleaned) {
      throw new Error(`Workspace ${this.workspacePath} already cleaned`);
    }
  }

  private normalizePath(path: string): string {
    const raw = path.trim();
    if (!raw) throw new Error("Path is empty");
    if (raw.startsWith("/")) throw new Error("Absolute paths are not allowed");
    if (raw.startsWith(".workspaces/")) {
      throw new Error("Cannot access other workspace paths");
    }

    const parts = raw.split("/").filter((p) => p.length > 0);
    const out: string[] = [];
    for (const part of parts) {
      if (part === ".") continue;
      if (part === "..") {
        throw new Error(`Path escapes worker workspace: ${path}`);
      }
      out.push(part);
    }
    const normalized = out.join("/");
    if (!normalized) throw new Error("Path resolves to workspace root");
    return normalized;
  }

  readFile(path: string, limit?: number): string {
    this.assertActive();
    const normalized = this.normalizePath(path);
    const content = this.files.get(normalized);
    if (content === undefined) throw new Error(`File not found: ${normalized}`);

    if (!limit || limit <= 0) return content;
    const lines = content.split(/\r?\n/);
    if (lines.length <= limit) return content;
    return `${lines.slice(0, limit).join("\n")}\n... (${lines.length - limit} more lines)`;
  }

  writeFile(path: string, content: string): string {
    this.assertActive();
    const normalized = this.normalizePath(path);
    this.files.set(normalized, content);
    return `File written: ${normalized}`;
  }

  editFile(path: string, oldText: string, newText: string): string {
    this.assertActive();
    const normalized = this.normalizePath(path);
    const existing = this.files.get(normalized);
    if (existing === undefined) throw new Error(`File not found: ${normalized}`);
    if (!existing.includes(oldText)) throw new Error(`old_text not found in ${normalized}`);

    this.files.set(normalized, existing.replace(oldText, newText));
    return `File edited: ${normalized}`;
  }

  bash(command: string): string {
    this.assertActive();
    const cmd = command.trim();

    if (cmd.startsWith("cat ")) {
      const path = cmd.slice(4).trim();
      return this.readFile(path);
    }

    if (cmd === "ls" || cmd.startsWith("ls ")) {
      const files = Array.from(this.files.keys()).sort();
      return files.length > 0 ? files.join("\n") : "(empty)";
    }

    if (cmd.startsWith("echo ") && cmd.includes(">")) {
      const [left, right] = cmd.split(">", 2);
      const content = left.replace(/^echo\s+/, "").replace(/^["']|["']$/g, "").trim();
      const filePath = right.trim();
      this.writeFile(filePath, `${content}\n`);
      return "";
    }

    if (cmd.startsWith("mkdir ")) return "";

    if (cmd.startsWith("rm ")) {
      const target = cmd
        .slice(3)
        .trim()
        .replace(/^-r\s*/, "")
        .replace(/^-f\s*/, "")
        .replace(/^-rf\s*/, "")
        .trim();
      const normalized = this.normalizePath(target);
      this.files.delete(normalized);
      return "";
    }

    if (cmd.startsWith("python ") || cmd.startsWith("node ")) {
      const file = cmd.split(/\s+/)[1] ?? "";
      const normalized = this.normalizePath(file);
      if (!this.files.has(normalized)) return `Error: File not found: ${normalized}`;
      return `[simulated output of ${normalized}]`;
    }

    return `$ ${cmd}\n[simulated in ${this.workspacePath}]`;
  }

  diffAgainstCanonical(canonicalSnapshot: Record<string, string>): Record<string, { before: string; after: string }> {
    this.assertActive();
    const allPaths = new Set<string>([
      ...Object.keys(canonicalSnapshot),
      ...Array.from(this.files.keys()),
    ]);

    const diff: Record<string, { before: string; after: string }> = {};
    for (const path of Array.from(allPaths).sort()) {
      const before = canonicalSnapshot[path] ?? "";
      const after = this.files.get(path) ?? "";
      if (before === after) continue;
      diff[path] = { before, after };
    }

    return diff;
  }

  cleanup(): void {
    this.files.clear();
    this.cleaned = true;
  }
}

export class WorkerIsolationAgent extends BaseAgent {
  private plannerName: string;
  private workers = new Map<string, WorkerState>();
  private runtimes = new Map<string, WorkerRuntime>();
  private workspaces = new Map<string, WorkerWorkspace>();
  private handoffs: Handoff[] = [];
  private canonicalSnapshot: Record<string, string>;

  constructor(config: AgentConfig & { plannerName?: string }) {
    super(config);
    this.plannerName = config.plannerName ?? "planner";
    this.canonicalSnapshot = this.toolExecutor.fs.snapshot();
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
        "## Workspace Rule",
        "- Every worker gets private .workspaces/{worker_id} copy.",
        "- Worker diff is against canonical snapshot.",
      ].join("\n")
    );
  }

  private createRuntime(taskId: string, workspacePath: string): WorkerRuntime {
    return {
      taskId,
      startedAt: Date.now(),
      attempts: 0,
      turns: 0,
      tokensUsed: 0,
      artifacts: [],
      errors: [],
      submitted: false,
      lastText: "",
      workspacePath,
      workspaceCleaned: false,
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

  private seedWorkerScratchpad(worker: string, task: string, workspacePath: string): void {
    this.rewriteWorkerScratchpad(
      worker,
      [
        `# Worker Scratchpad (${worker})`,
        "",
        "## Role Constraint",
        "- I execute one task and submit handoff.",
        "- I do NOT decompose or delegate.",
        "",
        "## Workspace Constraint",
        `- Workspace: ${workspacePath}`,
        "- I only read/write inside this workspace.",
        "",
        "## Assigned Task",
        `- ${task}`,
      ].join("\n")
    );
  }

  private dedupeKeepOrder(items: string[]): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const item of items) {
      if (seen.has(item)) continue;
      seen.add(item);
      out.push(item);
    }
    return out;
  }

  private workerWorkspace(worker: string): WorkerWorkspace | undefined {
    return this.workspaces.get(worker);
  }

  private inferHandoffStatus(worker: string, diffCount: number): HandoffStatus {
    const rt = this.runtimes.get(worker);
    if (!rt) return "Failed";
    if (rt.errors.length === 0) return "Success";
    if (rt.errors.length > 0 && diffCount > 0) return "PartialFailure";

    const merged = rt.errors.join("\n").toLowerCase();
    if (
      merged.includes("not found") ||
      merged.includes("blocked") ||
      merged.includes("permission") ||
      merged.includes("escape")
    ) {
      return "Blocked";
    }
    return "Failed";
  }

  private async composeNarrative(worker: string, handoff: Handoff): Promise<string> {
    const rt = this.runtimes.get(worker);
    if (!rt) return `Task ${handoff.task_id} completed with status ${handoff.status}.`;

    const payload = {
      worker,
      task_id: handoff.task_id,
      status: handoff.status,
      workspace_path: handoff.workspace_path,
      files_modified: handoff.metrics.files_modified,
      artifacts: handoff.artifacts,
      errors: rt.errors.slice(-5),
      scratchpad: this.toolExecutor.fs.getFile(this.workerScratchpadPath(worker)) ?? "",
      assistant_final_text: rt.lastText,
    };

    try {
      const response = await createMessage({
        apiKey: this.config.apiKey,
        model: this.config.model,
        system:
          "Write concise worker handoff narrative for planner. Include changed files, risks, and one next step. <= 10 lines.",
        messages: [{ role: "user", content: JSON.stringify(payload, null, 2) }],
        tools: [],
      });

      this.totalInputTokens += response.usage.input_tokens;
      this.totalOutputTokens += response.usage.output_tokens;
      rt.tokensUsed += response.usage.input_tokens + response.usage.output_tokens;

      const text = response.content
        .filter((b): b is { type: "text"; text: string } => b.type === "text")
        .map((b) => b.text)
        .join("\n")
        .trim();
      if (text) return text;
    } catch {
      // Fallback narrative below.
    }

    return [
      `Worker ${worker} completed task ${handoff.task_id} with status ${handoff.status}.`,
      `Workspace: ${handoff.workspace_path}.`,
      `Changed files: ${Object.keys(handoff.diff).join(", ") || "none"}.`,
      "Next step: planner reviews diff and decides follow-up.",
    ].join("\n");
  }

  private async submitHandoff(worker: string, input: Record<string, unknown>): Promise<string> {
    const rt = this.runtimes.get(worker);
    if (!rt) return `Error: runtime missing for ${worker}`;
    if (rt.submitted) return `Handoff already submitted for task ${rt.taskId}`;

    const workspace = this.workerWorkspace(worker);
    if (!workspace) return `Error: workspace missing for ${worker}`;

    const diff = workspace.diffAgainstCanonical(this.canonicalSnapshot);
    const requested = input.status;
    const status: HandoffStatus =
      requested === "Success" || requested === "PartialFailure" || requested === "Failed" || requested === "Blocked"
        ? requested
        : this.inferHandoffStatus(worker, Object.keys(diff).length);

    const extraArtifacts = Array.isArray(input.artifacts)
      ? input.artifacts.filter((a): a is string => typeof a === "string")
      : [];
    const artifacts = this.dedupeKeepOrder([...rt.artifacts, ...extraArtifacts]);

    const handoff: Handoff = {
      agent_id: worker,
      task_id: String(input.task_id ?? rt.taskId),
      status,
      diff,
      narrative: "",
      artifacts,
      workspace_path: rt.workspacePath,
      metrics: {
        wall_time: (Date.now() - rt.startedAt) / 1000,
        tokens_used: rt.tokensUsed,
        attempts: rt.attempts,
        files_modified: Object.keys(diff).length,
      },
    };

    const narrativeInput = typeof input.narrative === "string" ? input.narrative.trim() : "";
    handoff.narrative = narrativeInput.length > 0 ? narrativeInput : await this.composeNarrative(worker, handoff);

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

  private cleanupWorkspace(worker: string): void {
    const workspace = this.workerWorkspace(worker);
    const rt = this.runtimes.get(worker);
    if (!workspace || !rt) return;
    workspace.cleanup();
    rt.workspaceCleaned = true;
  }

  private executeWorkerTool(worker: string, block: ToolUseBlock): ToolResultBlock {
    const rt = this.runtimes.get(worker);
    const workspace = this.workerWorkspace(worker);

    if (!rt || !workspace) {
      return {
        type: "tool_result",
        tool_use_id: block.id,
        content: `Error: runtime/workspace missing for ${worker}`,
        is_error: true,
      };
    }

    try {
      if (block.name === "rewrite_scratchpad") {
        const content = String((block.input as Record<string, unknown>).content ?? "");
        const out = this.rewriteWorkerScratchpad(worker, content);
        return { type: "tool_result", tool_use_id: block.id, content: out };
      }

      if (block.name === "submit_handoff") {
        return {
          type: "tool_result",
          tool_use_id: block.id,
          content: "submit_handoff handled asynchronously",
        };
      }

      if (block.name === "write_file") {
        const input = block.input as Record<string, unknown>;
        const path = String(input.path ?? input.file_path ?? "");
        const content = String(input.content ?? "");
        const out = workspace.writeFile(path, content);
        rt.artifacts.push(path);
        return { type: "tool_result", tool_use_id: block.id, content: out };
      }

      if (block.name === "edit_file") {
        const input = block.input as Record<string, unknown>;
        const path = String(input.path ?? input.file_path ?? "");
        const oldText = String(input.old_text ?? input.old_string ?? "");
        const newText = String(input.new_text ?? input.new_string ?? "");
        const out = workspace.editFile(path, oldText, newText);
        rt.artifacts.push(path);
        return { type: "tool_result", tool_use_id: block.id, content: out };
      }

      if (block.name === "read_file") {
        const input = block.input as Record<string, unknown>;
        const path = String(input.path ?? input.file_path ?? "");
        const limitRaw = input.limit;
        const limit = typeof limitRaw === "number" ? limitRaw : undefined;
        const out = workspace.readFile(path, limit);
        return {
          type: "tool_result",
          tool_use_id: block.id,
          content: out.length > 50000 ? out.slice(0, 50000) : out,
        };
      }

      if (block.name === "bash") {
        const command = String((block.input as Record<string, unknown>).command ?? "");
        const out = workspace.bash(command);
        return {
          type: "tool_result",
          tool_use_id: block.id,
          content: out.length > 50000 ? out.slice(0, 50000) : out,
        };
      }

      return {
        type: "tool_result",
        tool_use_id: block.id,
        content: `Error: worker tool not allowed: ${block.name}`,
        is_error: true,
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      rt.errors.push(msg);
      return { type: "tool_result", tool_use_id: block.id, content: `Error: ${msg}`, is_error: true };
    }
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
        content: `<workspace>${rt.workspacePath}</workspace>`,
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
        if (!rt.submitted) {
          await this.submitHandoff(worker, { task_id: taskId });
        }
        break;
      }

      const toolResults: ToolResultBlock[] = [];
      for (const block of response.content) {
        if (block.type !== "tool_use") continue;

        if (block.name === "submit_handoff") {
          const output = await this.submitHandoff(worker, block.input as Record<string, unknown>);
          toolResults.push({ type: "tool_result", tool_use_id: block.id, content: output });
          continue;
        }

        toolResults.push(this.executeWorkerTool(worker, block as ToolUseBlock));
      }

      workerMessages.push({ role: "user", content: toolResults });
      if (rt.submitted) break;
    }

    if (!rt.submitted) {
      await this.submitHandoff(worker, { task_id: taskId });
    }

    this.cleanupWorkspace(worker);
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

    const workspace = new WorkerWorkspace(name, this.canonicalSnapshot);
    this.workspaces.set(name, workspace);

    this.workers.set(name, {
      name,
      status: "working",
      task,
      taskId,
      workspacePath: workspace.workspacePath,
    });

    this.runtimes.set(name, this.createRuntime(taskId, workspace.workspacePath));
    this.seedWorkerScratchpad(name, task, workspace.workspacePath);

    await this.runWorker(name, task, taskId);
    return `Spawned '${name}' with task_id=${taskId} workspace=${workspace.workspacePath}`;
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
          workspace_path: h.workspace_path,
          metrics: h.metrics,
        };
        return includeDiff ? { ...base, diff: h.diff } : base;
      }),
      null,
      2
    );
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
                .map((w) => {
                  const rt = this.runtimes.get(w.name);
                  return `- ${w.name}: status=${w.status} task=${w.taskId} workspace=${w.workspacePath} cleaned=${rt?.workspaceCleaned ?? false}`;
                })
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
      {
        name: "bash",
        description: "Run command inside worker workspace.",
        input_schema: {
          type: "object",
          properties: { command: { type: "string" } },
          required: ["command"],
        },
      },
      {
        name: "read_file",
        description: "Read file from worker workspace.",
        input_schema: {
          type: "object",
          properties: { path: { type: "string" }, limit: { type: "integer" } },
          required: ["path"],
        },
      },
      {
        name: "write_file",
        description: "Write/create file in worker workspace.",
        input_schema: {
          type: "object",
          properties: { path: { type: "string" }, content: { type: "string" } },
          required: ["path", "content"],
        },
      },
      {
        name: "edit_file",
        description: "Replace text in worker workspace file.",
        input_schema: {
          type: "object",
          properties: {
            path: { type: "string" },
            old_text: { type: "string" },
            new_text: { type: "string" },
          },
          required: ["path", "old_text", "new_text"],
        },
      },
      {
        name: "submit_handoff",
        description: "Submit structured handoff with canonical diff.",
        input_schema: {
          type: "object",
          properties: {
            task_id: { type: "string" },
            status: {
              type: "string",
              enum: ["Success", "PartialFailure", "Failed", "Blocked"],
            },
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
          properties: { content: { type: "string" } },
          required: ["content"],
        },
      },
    ];
  }

  getTools(): ToolDefinition[] {
    return [
      {
        name: "spawn_worker",
        description: "Spawn worker with private workspace for one concrete task.",
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
        description: "Review handoffs by task/agent.",
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
        description: "List worker status and workspace cleanup state.",
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
        currentTask: `${w.task} (${w.workspacePath})`,
      })),
      handoffs: this.handoffs,
      scratchpads: {
        [this.plannerName]: this.toolExecutor.fs.getFile(this.plannerScratchpadPath()) ?? "",
        ...Array.from(this.workers.keys()).reduce<Record<string, string>>((acc, worker) => {
          acc[worker] = this.toolExecutor.fs.getFile(this.workerScratchpadPath(worker)) ?? "";
          return acc;
        }, {}),
      },
      workspaces: Array.from(this.workers.values()).map((w) => ({
        worker: w.name,
        path: w.workspacePath,
        cleaned: this.runtimes.get(w.name)?.workspaceCleaned ?? false,
      })),
    } as AgentState;
  }
}
