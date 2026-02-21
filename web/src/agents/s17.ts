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

type AgentRole = "root_planner" | "sub_planner" | "worker";
type HandoffStatus = "Success" | "PartialFailure" | "Failed" | "Blocked";

interface Handoff {
  handoff_id: string;
  agent_id: string;
  role: AgentRole;
  parent_id: string;
  task_id: string;
  depth: number;
  status: HandoffStatus;
  diff: Record<string, { before: string; after: string }>;
  narrative: string;
  artifacts: string[];
  child_handoff_ids: string[];
  workspace_path: string;
  aggregated: boolean;
  metrics: {
    wall_time: number;
    tokens_used: number;
    attempts: number;
    files_modified: number;
    child_handoffs: number;
  };
}

interface AgentSpec {
  agentId: string;
  role: AgentRole;
  parentId: string | null;
  depth: number;
  taskId: string;
  assignedTask: string;
  status: "idle" | "working" | "shutdown";
}

interface AgentRuntime {
  agentId: string;
  taskId: string;
  startedAt: number;
  attempts: number;
  turns: number;
  tokensUsed: number;
  errors: string[];
  artifacts: string[];
  lastText: string;
  handoffSubmitted: boolean;
  workspacePath: string;
  workspaceCleaned: boolean;
  baseSnapshot: Record<string, string>;
}

interface WorkerState {
  name: string;
  status: "idle" | "working" | "shutdown";
  taskId: string;
  task: string;
  workspacePath: string;
  role: AgentRole;
  parentId: string | null;
  depth: number;
}

const MAX_HIERARCHY_DEPTH = 3;
const MAX_WORKER_TURNS = 24;
const MAX_PLANNER_TURNS = 24;

const ROOT_SYSTEM = [
  "You are ROOT PLANNER.",
  "Lifecycle: INIT -> DECOMPOSE -> ORCHESTRATE -> RECONCILE -> DONE.",
  "Delegate only. NEVER write code.",
  "Use SubPlanners for complex slices and Workers for simple slices.",
  "SubPlanners must submit aggregate handoffs that bubble upward.",
].join("\n");

const SUB_PLANNER_SYSTEM = (name: string, depth: number, parent: string) =>
  [
    `You are SUB PLANNER '${name}' at depth ${depth} with parent '${parent}'.`,
    "You own one delegated slice.",
    "You can spawn workers and (if depth allows) deeper sub planners.",
    "You NEVER write code.",
    "Submit exactly one aggregate handoff upward.",
  ].join("\n");

const WORKER_SYSTEM = (name: string, parent: string) =>
  [
    `You are WORKER '${name}' with parent '${parent}'.`,
    "Execute only assigned task in private workspace.",
    "Do NOT decompose or spawn.",
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
    if (raw.startsWith(".workspaces/")) throw new Error("Cannot access other workspace paths");

    const parts = raw.split("/").filter((p) => p.length > 0);
    const out: string[] = [];
    for (const part of parts) {
      if (part === ".") continue;
      if (part === "..") throw new Error(`Path escapes worker workspace: ${path}`);
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

  snapshot(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [k, v] of this.files) out[k] = v;
    return out;
  }

  diffAgainstBase(baseSnapshot: Record<string, string>): Record<string, { before: string; after: string }> {
    this.assertActive();
    const current = this.snapshot();
    const allPaths = new Set<string>([...Object.keys(baseSnapshot), ...Object.keys(current)]);

    const diff: Record<string, { before: string; after: string }> = {};
    for (const path of Array.from(allPaths).sort()) {
      const before = baseSnapshot[path] ?? "";
      const after = current[path] ?? "";
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

export class RecursiveHierarchy extends BaseAgent {
  private rootName: string;
  private agents = new Map<string, AgentSpec>();
  private runtimes = new Map<string, AgentRuntime>();
  private workers = new Map<string, WorkerState>();
  private workspaces = new Map<string, WorkerWorkspace>();
  private handoffs: Handoff[] = [];

  constructor(config: AgentConfig & { rootName?: string }) {
    super(config);
    this.rootName = config.rootName ?? "root";
    this.bootstrapRoot();
  }

  async spawnSubPlanner(input: Record<string, unknown>): Promise<string> {
    const parentId =
      typeof input.parent_id === "string" && input.parent_id.trim().length > 0
        ? input.parent_id.trim()
        : this.rootName;
    return this.spawnSubPlannerForPlanner(parentId, input, false);
  }

  async spawn_sub_planner(input: Record<string, unknown>): Promise<string> {
    return this.spawnSubPlanner(input);
  }

  private plannerScratchpadPath(plannerId: string): string {
    return `.scratchpad/${plannerId}.md`;
  }

  private workerScratchpadPath(workerId: string): string {
    return `.scratchpad/${workerId}.md`;
  }

  private inboxPath(name: string): string {
    return `.team/inbox/${name}.jsonl`;
  }

  private bootstrapRoot(): void {
    if (this.agents.has(this.rootName)) return;

    this.agents.set(this.rootName, {
      agentId: this.rootName,
      role: "root_planner",
      parentId: null,
      depth: 0,
      taskId: "root-task",
      assignedTask: "Top-level orchestration",
      status: "idle",
    });

    if (!this.toolExecutor.fs.getFile(this.plannerScratchpadPath(this.rootName))) {
      this.toolExecutor.fs.writeFile(
        this.plannerScratchpadPath(this.rootName),
        [
          `# Root Planner Scratchpad (${this.rootName})`,
          "",
          "## Constraints",
          "- Delegate only, never code.",
          "- SubPlanner recursion is allowed.",
          "- Aggregate handoffs bubble upward.",
          `- Max depth: ${MAX_HIERARCHY_DEPTH}`,
        ].join("\n")
      );
    }

    this.runtimes.set(this.rootName, this.createRuntime(this.rootName, "root-task", "", {}));
  }

  private createRuntime(
    agentId: string,
    taskId: string,
    workspacePath: string,
    baseSnapshot: Record<string, string>
  ): AgentRuntime {
    return {
      agentId,
      taskId,
      startedAt: Date.now(),
      attempts: 0,
      turns: 0,
      tokensUsed: 0,
      errors: [],
      artifacts: [],
      lastText: "",
      handoffSubmitted: false,
      workspacePath,
      workspaceCleaned: false,
      baseSnapshot,
    };
  }

  private nextChildName(parentId: string, role: AgentRole): string {
    const base = role === "sub_planner" ? `${parentId}-sp` : `${parentId}-w`;
    let idx = 1;
    while (this.agents.has(`${base}${idx}`)) idx += 1;
    return `${base}${idx}`;
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

  private plannerSystem(plannerId: string): string {
    const spec = this.agents.get(plannerId);
    if (!spec) return ROOT_SYSTEM;
    if (spec.role === "root_planner") return ROOT_SYSTEM;
    return SUB_PLANNER_SYSTEM(plannerId, spec.depth, spec.parentId ?? this.rootName);
  }

  private rewritePlannerScratchpad(plannerId: string, content: string): string {
    return this.toolExecutor.fs.writeFile(this.plannerScratchpadPath(plannerId), content);
  }

  private rewriteWorkerScratchpad(worker: string, content: string): string {
    return this.toolExecutor.fs.writeFile(this.workerScratchpadPath(worker), content);
  }

  private bootstrapAgentScratchpad(spec: AgentSpec): void {
    const path =
      spec.role === "worker"
        ? this.workerScratchpadPath(spec.agentId)
        : this.plannerScratchpadPath(spec.agentId);
    if (this.toolExecutor.fs.getFile(path)) return;

    if (spec.role === "worker") {
      this.toolExecutor.fs.writeFile(
        path,
        [
          `# Worker Scratchpad (${spec.agentId})`,
          "",
          "- Execute assigned task only.",
          "- Do not decompose or spawn.",
          `- Parent: ${spec.parentId ?? this.rootName}`,
          `- Task: ${spec.assignedTask}`,
        ].join("\n")
      );
      return;
    }

    this.toolExecutor.fs.writeFile(
      path,
      [
        `# SubPlanner Scratchpad (${spec.agentId})`,
        "",
        "- Decompose delegated scope.",
        "- Spawn workers and sub planners when useful.",
        "- Aggregate child handoffs and bubble upward.",
        `- Depth: ${spec.depth}/${MAX_HIERARCHY_DEPTH}`,
        `- Task: ${spec.assignedTask}`,
      ].join("\n")
    );
  }

  private runtimeOf(agentId: string): AgentRuntime {
    const existing = this.runtimes.get(agentId);
    if (existing) return existing;
    const created = this.createRuntime(agentId, "none", "", {});
    this.runtimes.set(agentId, created);
    return created;
  }

  private inferHandoffStatus(agentId: string, diffCount: number, childCount: number): HandoffStatus {
    const rt = this.runtimeOf(agentId);
    if (rt.errors.length === 0) return "Success";
    if (rt.errors.length > 0 && (diffCount > 0 || childCount > 0)) return "PartialFailure";

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

  private shouldSpawnSubPlanner(task: string, depth: number): boolean {
    if (depth >= MAX_HIERARCHY_DEPTH - 1) return false;

    const files = task.match(/[\w\-/]+\.[a-zA-Z0-9_]+/g) ?? [];
    if (new Set(files).size >= 3) return true;

    const lower = task.toLowerCase();
    const hintWords = ["subsystem", "multi", "complex", "across", "pipeline"];
    return hintWords.some((word) => lower.includes(word));
  }

  private childHandoffs(parentId: string): Handoff[] {
    return this.handoffs.filter((handoff) => handoff.parent_id === parentId);
  }

  private mergeChildDiffs(childHandoffs: Handoff[]): Record<string, { before: string; after: string }> {
    const merged: Record<string, { before: string; after: string }> = {};

    for (const handoff of childHandoffs) {
      for (const [path, delta] of Object.entries(handoff.diff)) {
        if (!merged[path]) {
          merged[path] = { before: delta.before, after: delta.after };
          continue;
        }
        merged[path].after = delta.after;
      }
    }

    return merged;
  }

  private recordError(agentId: string, message: string): void {
    this.runtimeOf(agentId).errors.push(message);
  }

  private recordArtifact(agentId: string, path: string): void {
    this.runtimeOf(agentId).artifacts.push(path);
  }

  private async compressNarrative(
    agentId: string,
    role: AgentRole,
    depth: number,
    taskId: string,
    childHandoffs: Handoff[],
    finalText: string
  ): Promise<string> {
    const payload = {
      agent_id: agentId,
      role,
      depth,
      task_id: taskId,
      child_count: childHandoffs.length,
      child_status: childHandoffs.map((handoff) => handoff.status),
      child_narratives: childHandoffs.map((handoff) => handoff.narrative),
      child_diff_files: childHandoffs.map((handoff) => Object.keys(handoff.diff)),
      scratchpad:
        this.toolExecutor.fs.getFile(
          role === "worker" ? this.workerScratchpadPath(agentId) : this.plannerScratchpadPath(agentId)
        ) ?? "",
      final_text: finalText,
    };

    try {
      const response = await createMessage({
        apiKey: this.config.apiKey,
        model: this.config.model,
        system:
          "Write concise handoff narrative for parent planner. Include completed work, unresolved items, risk, and one next step. <= 12 lines.",
        messages: [{ role: "user", content: JSON.stringify(payload, null, 2) }],
        tools: [],
      });

      this.totalInputTokens += response.usage.input_tokens;
      this.totalOutputTokens += response.usage.output_tokens;
      this.runtimeOf(agentId).tokensUsed += response.usage.input_tokens + response.usage.output_tokens;

      const text = response.content
        .filter((block): block is { type: "text"; text: string } => block.type === "text")
        .map((block) => block.text)
        .join("\n")
        .trim();
      if (text) return text;
    } catch {
      // Fallback below.
    }

    if (role === "worker") {
      return [
        `Worker ${agentId} completed task ${taskId}.`,
        `Changed files: ${childHandoffs.length}.`,
        `Final output: ${(finalText || "(none)").slice(0, 220)}`,
      ].join("\n");
    }

    const head = childHandoffs.slice(0, 8).map((handoff) => `- ${handoff.agent_id}: ${handoff.status} (${Object.keys(handoff.diff).length} files)`);
    return [
      `${role} ${agentId} aggregated task ${taskId} at depth ${depth}.`,
      `Child handoffs: ${childHandoffs.length}`,
      ...(head.length > 0 ? head : ["- no child handoffs"]),
    ].join("\n");
  }

  private sendHandoff(handoff: Handoff): string {
    this.handoffs.push(handoff);
    this.runtimeOf(handoff.agent_id).handoffSubmitted = true;

    this.appendInbox(handoff.parent_id, {
      type: "handoff",
      from: handoff.agent_id,
      to: handoff.parent_id,
      content: handoff.narrative,
      handoff,
      timestamp: Date.now(),
    });

    return `Submitted handoff ${handoff.handoff_id} -> ${handoff.parent_id} (${handoff.status})`;
  }

  private async submitWorkerHandoff(agentId: string, input: Record<string, unknown>): Promise<string> {
    const spec = this.agents.get(agentId);
    if (!spec) return `Error: unknown agent ${agentId}`;

    const rt = this.runtimeOf(agentId);
    if (rt.handoffSubmitted) return `Handoff already submitted for task ${rt.taskId}`;

    const workspace = this.workspaces.get(agentId);
    if (!workspace) return `Error: workspace missing for ${agentId}`;

    const diff = workspace.diffAgainstBase(rt.baseSnapshot);
    const requested = input.status;
    const status: HandoffStatus =
      requested === "Success" || requested === "PartialFailure" || requested === "Failed" || requested === "Blocked"
        ? requested
        : this.inferHandoffStatus(agentId, Object.keys(diff).length, 0);

    const extraArtifacts = Array.isArray(input.artifacts)
      ? input.artifacts.filter((item): item is string => typeof item === "string")
      : [];

    const artifacts = this.dedupeKeepOrder([...rt.artifacts, ...extraArtifacts]);
    const taskId = typeof input.task_id === "string" && input.task_id.trim().length > 0 ? input.task_id.trim() : rt.taskId;

    const handoff: Handoff = {
      handoff_id: `h-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      agent_id: agentId,
      role: spec.role,
      parent_id: spec.parentId ?? this.rootName,
      task_id: taskId,
      depth: spec.depth,
      status,
      diff,
      narrative: "",
      artifacts,
      child_handoff_ids: [],
      workspace_path: rt.workspacePath,
      aggregated: false,
      metrics: {
        wall_time: (Date.now() - rt.startedAt) / 1000,
        tokens_used: rt.tokensUsed,
        attempts: rt.attempts,
        files_modified: Object.keys(diff).length,
        child_handoffs: 0,
      },
    };

    const narrativeInput = typeof input.narrative === "string" ? input.narrative.trim() : "";
    handoff.narrative =
      narrativeInput.length > 0
        ? narrativeInput
        : await this.compressNarrative(agentId, spec.role, spec.depth, handoff.task_id, [], rt.lastText);

    return this.sendHandoff(handoff);
  }

  private async submitAggregateHandoff(plannerId: string, input: Record<string, unknown>): Promise<string> {
    const spec = this.agents.get(plannerId);
    if (!spec) return `Error: unknown planner ${plannerId}`;
    if (!spec.parentId) return "Error: root planner does not submit aggregate upward";

    const rt = this.runtimeOf(plannerId);
    if (rt.handoffSubmitted) return `Aggregate handoff already submitted for task ${rt.taskId}`;

    const childHandoffs = this.childHandoffs(plannerId);
    const mergedDiff = this.mergeChildDiffs(childHandoffs);

    const requested = input.status;
    let status: HandoffStatus;
    if (requested === "Success" || requested === "PartialFailure" || requested === "Failed" || requested === "Blocked") {
      status = requested;
    } else if (childHandoffs.length > 0 && childHandoffs.every((handoff) => handoff.status === "Success")) {
      status = "Success";
    } else if (childHandoffs.some((handoff) => handoff.status === "Failed")) {
      status = "PartialFailure";
    } else {
      status = this.inferHandoffStatus(plannerId, Object.keys(mergedDiff).length, childHandoffs.length);
    }

    const extraArtifacts = Array.isArray(input.artifacts)
      ? input.artifacts.filter((item): item is string => typeof item === "string")
      : [];

    const artifacts = this.dedupeKeepOrder([
      ...rt.artifacts,
      ...extraArtifacts,
      ...childHandoffs.flatMap((handoff) => handoff.artifacts),
    ]);

    const taskId = typeof input.task_id === "string" && input.task_id.trim().length > 0 ? input.task_id.trim() : rt.taskId;

    const handoff: Handoff = {
      handoff_id: `h-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      agent_id: plannerId,
      role: spec.role,
      parent_id: spec.parentId,
      task_id: taskId,
      depth: spec.depth,
      status,
      diff: mergedDiff,
      narrative: "",
      artifacts,
      child_handoff_ids: childHandoffs.map((item) => item.handoff_id),
      workspace_path: "",
      aggregated: true,
      metrics: {
        wall_time: (Date.now() - rt.startedAt) / 1000,
        tokens_used: rt.tokensUsed,
        attempts: rt.attempts,
        files_modified: Object.keys(mergedDiff).length,
        child_handoffs: childHandoffs.length,
      },
    };

    const narrativeInput = typeof input.narrative === "string" ? input.narrative.trim() : "";
    handoff.narrative =
      narrativeInput.length > 0
        ? narrativeInput
        : await this.compressNarrative(plannerId, spec.role, spec.depth, handoff.task_id, childHandoffs, rt.lastText);

    return this.sendHandoff(handoff);
  }

  private cleanupWorkspace(workerId: string): void {
    const rt = this.runtimes.get(workerId);
    const workspace = this.workspaces.get(workerId);
    if (!rt || !workspace) return;
    workspace.cleanup();
    rt.workspaceCleaned = true;
  }

  private executeWorkerTool(workerId: string, block: ToolUseBlock): ToolResultBlock {
    const rt = this.runtimes.get(workerId);
    const workspace = this.workspaces.get(workerId);

    if (!rt || !workspace) {
      return {
        type: "tool_result",
        tool_use_id: block.id,
        content: `Error: runtime/workspace missing for ${workerId}`,
        is_error: true,
      };
    }

    try {
      if (block.name === "rewrite_scratchpad") {
        const content = String((block.input as Record<string, unknown>).content ?? "");
        const out = this.rewriteWorkerScratchpad(workerId, content);
        return { type: "tool_result", tool_use_id: block.id, content: out };
      }

      if (block.name === "submit_handoff") {
        return { type: "tool_result", tool_use_id: block.id, content: "submit_handoff handled asynchronously" };
      }

      if (block.name === "write_file") {
        const input = block.input as Record<string, unknown>;
        const path = String(input.path ?? input.file_path ?? "");
        const content = String(input.content ?? "");
        const out = workspace.writeFile(path, content);
        this.recordArtifact(workerId, path);
        return { type: "tool_result", tool_use_id: block.id, content: out };
      }

      if (block.name === "edit_file") {
        const input = block.input as Record<string, unknown>;
        const path = String(input.path ?? input.file_path ?? "");
        const oldText = String(input.old_text ?? input.old_string ?? "");
        const newText = String(input.new_text ?? input.new_string ?? "");
        const out = workspace.editFile(path, oldText, newText);
        this.recordArtifact(workerId, path);
        return { type: "tool_result", tool_use_id: block.id, content: out };
      }

      if (block.name === "read_file") {
        const input = block.input as Record<string, unknown>;
        const path = String(input.path ?? input.file_path ?? "");
        const limit = typeof input.limit === "number" ? input.limit : undefined;
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
      const message = err instanceof Error ? err.message : String(err);
      this.recordError(workerId, message);
      return { type: "tool_result", tool_use_id: block.id, content: `Error: ${message}`, is_error: true };
    }
  }

  private async runWorker(workerId: string): Promise<void> {
    const spec = this.agents.get(workerId);
    const rt = this.runtimes.get(workerId);
    if (!spec || !rt) return;

    const workerMessages: Message[] = [
      { role: "user", content: `<assignment>task_id=${spec.taskId}\n${spec.assignedTask}</assignment>` },
      { role: "user", content: `<workspace>${rt.workspacePath}</workspace>` },
      {
        role: "user",
        content: `<scratchpad>${this.toolExecutor.fs.getFile(this.workerScratchpadPath(workerId)) ?? "(empty)"}</scratchpad>`,
      },
    ];

    for (let turn = 0; turn < MAX_WORKER_TURNS; turn += 1) {
      const response = await createMessage({
        apiKey: this.config.apiKey,
        model: this.config.model,
        system: WORKER_SYSTEM(workerId, spec.parentId ?? this.rootName),
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
        if (!rt.handoffSubmitted) {
          await this.submitWorkerHandoff(workerId, { task_id: spec.taskId });
        }
        break;
      }

      const toolResults: ToolResultBlock[] = [];
      for (const block of response.content) {
        if (block.type !== "tool_use") continue;

        if (block.name === "submit_handoff") {
          const output = await this.submitWorkerHandoff(workerId, block.input as Record<string, unknown>);
          toolResults.push({ type: "tool_result", tool_use_id: block.id, content: output });
          continue;
        }

        toolResults.push(this.executeWorkerTool(workerId, block as ToolUseBlock));
      }

      workerMessages.push({ role: "user", content: toolResults });
      if (rt.handoffSubmitted) break;
    }

    if (!rt.handoffSubmitted) {
      await this.submitWorkerHandoff(workerId, { task_id: spec.taskId });
    }

    this.cleanupWorkspace(workerId);
    spec.status = "idle";
    const worker = this.workers.get(workerId);
    if (worker) worker.status = "idle";
  }

  private async spawnWorkerForPlanner(plannerId: string, input: Record<string, unknown>): Promise<string> {
    const planner = this.agents.get(plannerId);
    if (!planner) return `Error: planner ${plannerId} not found`;

    const task = String(input.task ?? "").trim();
    if (!task) return "Error: task is required";

    const depth = planner.depth + 1;
    if (depth > MAX_HIERARCHY_DEPTH) {
      return `Error: depth limit ${MAX_HIERARCHY_DEPTH} reached`;
    }

    const name =
      typeof input.name === "string" && input.name.trim().length > 0
        ? input.name.trim()
        : this.nextChildName(plannerId, "worker");

    const taskId =
      typeof input.task_id === "string" && input.task_id.trim().length > 0
        ? input.task_id.trim()
        : `task-${Date.now()}`;

    const existing = this.agents.get(name);
    if (existing && existing.status === "working") {
      return `Error: '${name}' is currently working`;
    }

    const baseSnapshot = this.toolExecutor.fs.snapshot();
    const workspace = new WorkerWorkspace(name, baseSnapshot);

    const spec: AgentSpec = {
      agentId: name,
      role: "worker",
      parentId: plannerId,
      depth,
      taskId,
      assignedTask: task,
      status: "working",
    };

    this.agents.set(name, spec);
    this.workspaces.set(name, workspace);
    this.runtimes.set(name, this.createRuntime(name, taskId, workspace.workspacePath, baseSnapshot));
    this.workers.set(name, {
      name,
      role: "worker",
      parentId: plannerId,
      depth,
      status: "working",
      taskId,
      task,
      workspacePath: workspace.workspacePath,
    });

    this.bootstrapAgentScratchpad(spec);
    await this.runWorker(name);
    return `Spawned worker '${name}' depth=${depth} task_id=${taskId}`;
  }

  private async spawnSubPlannerForPlanner(
    plannerId: string,
    input: Record<string, unknown>,
    runPlanner = true
  ): Promise<string> {
    const planner = this.agents.get(plannerId);
    if (!planner) return `Error: planner ${plannerId} not found`;

    const task = String(input.task ?? "").trim();
    if (!task) return "Error: task is required";

    const depth = planner.depth + 1;
    if (depth > MAX_HIERARCHY_DEPTH) {
      return `Error: depth limit ${MAX_HIERARCHY_DEPTH} reached`;
    }

    const name =
      typeof input.name === "string" && input.name.trim().length > 0
        ? input.name.trim()
        : this.nextChildName(plannerId, "sub_planner");

    const taskId =
      typeof input.task_id === "string" && input.task_id.trim().length > 0
        ? input.task_id.trim()
        : `task-${Date.now()}`;

    const existing = this.agents.get(name);
    if (existing && existing.status === "working") {
      return `Error: '${name}' is currently working`;
    }

    const spec: AgentSpec = {
      agentId: name,
      role: "sub_planner",
      parentId: plannerId,
      depth,
      taskId,
      assignedTask: task,
      status: "working",
    };

    this.agents.set(name, spec);
    this.runtimes.set(name, this.createRuntime(name, taskId, "", {}));
    this.workers.set(name, {
      name,
      role: "sub_planner",
      parentId: plannerId,
      depth,
      status: "working",
      taskId,
      task,
      workspacePath: "",
    });

    this.bootstrapAgentScratchpad(spec);
    if (runPlanner) {
      await this.runPlanner(name, false);
    } else {
      spec.status = "idle";
      const worker = this.workers.get(name);
      if (worker) worker.status = "idle";
    }
    return `Spawned sub_planner '${name}' depth=${depth} task_id=${taskId}`;
  }

  private async autoDelegate(plannerId: string, input: Record<string, unknown>): Promise<string> {
    const planner = this.agents.get(plannerId);
    if (!planner) return `Error: planner ${plannerId} not found`;
    const task = String(input.task ?? "").trim();
    if (!task) return "Error: task is required";

    if (this.shouldSpawnSubPlanner(task, planner.depth)) {
      return this.spawnSubPlannerForPlanner(plannerId, input);
    }
    return this.spawnWorkerForPlanner(plannerId, input);
  }

  private reviewHandoffsForParent(parentId: string, includeDiff: boolean): string {
    const selected = this.childHandoffs(parentId);
    if (selected.length === 0) return "No child handoffs found.";

    return JSON.stringify(
      selected.map((handoff) => {
        const base = {
          handoff_id: handoff.handoff_id,
          agent_id: handoff.agent_id,
          role: handoff.role,
          parent_id: handoff.parent_id,
          task_id: handoff.task_id,
          depth: handoff.depth,
          status: handoff.status,
          aggregated: handoff.aggregated,
          child_handoff_ids: handoff.child_handoff_ids,
          narrative: handoff.narrative,
          workspace_path: handoff.workspace_path,
          metrics: handoff.metrics,
        };
        return includeDiff ? { ...base, diff: handoff.diff } : base;
      }),
      null,
      2
    );
  }

  private depthInfo(plannerId: string): string {
    const spec = this.agents.get(plannerId);
    if (!spec) return "Error: planner not found";
    return JSON.stringify(
      {
        planner: plannerId,
        depth: spec.depth,
        depth_limit: MAX_HIERARCHY_DEPTH,
        can_spawn_sub_planner: spec.depth < MAX_HIERARCHY_DEPTH - 1,
      },
      null,
      2
    );
  }

  private listAgentsText(): string {
    const specs = Array.from(this.agents.values()).sort((a, b) => a.agentId.localeCompare(b.agentId));
    if (specs.length === 0) return "No agents.";
    return specs
      .map((spec) => {
        const inboxRaw = this.toolExecutor.fs.getFile(this.inboxPath(spec.agentId)) ?? "";
        const inboxCount = inboxRaw.trim() ? inboxRaw.trim().split(/\n+/).length : 0;
        return `- ${spec.agentId}: role=${spec.role} status=${spec.status} depth=${spec.depth} parent=${spec.parentId ?? "-"} task=${spec.taskId} inbox=${inboxCount}`;
      })
      .join("\n");
  }

  private treeViewText(): string {
    const byParent = new Map<string | null, AgentSpec[]>();
    for (const spec of this.agents.values()) {
      const arr = byParent.get(spec.parentId) ?? [];
      arr.push(spec);
      byParent.set(spec.parentId, arr);
    }
    for (const arr of byParent.values()) {
      arr.sort((a, b) => a.agentId.localeCompare(b.agentId));
    }

    const root = this.agents.get(this.rootName);
    if (!root) return "No root planner";

    const lines: string[] = [`${root.agentId} [${root.role}] d=${root.depth} status=${root.status}`];
    const walk = (parentId: string, prefix: string): void => {
      const children = byParent.get(parentId) ?? [];
      children.forEach((child, index) => {
        const isLast = index === children.length - 1;
        const branch = isLast ? "└── " : "├── ";
        lines.push(`${prefix}${branch}${child.agentId} [${child.role}] d=${child.depth} status=${child.status}`);
        walk(child.agentId, prefix + (isLast ? "    " : "│   "));
      });
    };

    walk(this.rootName, "");
    return lines.join("\n");
  }

  private plannerToolResult(plannerId: string, block: ToolUseBlock, output: string, isError = false): ToolResultBlock {
    this.emit("tool_result", {
      tool_use_id: block.id,
      name: block.name,
      planner: plannerId,
      content: output,
      is_error: isError,
    });

    return {
      type: "tool_result",
      tool_use_id: block.id,
      content: output,
      ...(isError ? { is_error: true } : {}),
    };
  }

  private async executePlannerTool(plannerId: string, block: ToolUseBlock): Promise<ToolResultBlock> {
    const input = block.input as Record<string, unknown>;

    try {
      if (block.name === "spawn_worker") {
        const output = await this.spawnWorkerForPlanner(plannerId, input);
        return this.plannerToolResult(plannerId, block, output, output.startsWith("Error:"));
      }

      if (block.name === "spawn_sub_planner") {
        const output = await this.spawnSubPlannerForPlanner(plannerId, input);
        return this.plannerToolResult(plannerId, block, output, output.startsWith("Error:"));
      }

      if (block.name === "auto_delegate") {
        const output = await this.autoDelegate(plannerId, input);
        return this.plannerToolResult(plannerId, block, output, output.startsWith("Error:"));
      }

      if (block.name === "review_handoff") {
        const output = this.reviewHandoffsForParent(plannerId, Boolean(input.include_diff));
        return this.plannerToolResult(plannerId, block, output);
      }

      if (block.name === "submit_aggregate_handoff" || block.name === "submit_handoff") {
        const output = await this.submitAggregateHandoff(plannerId, input);
        return this.plannerToolResult(plannerId, block, output, output.startsWith("Error:"));
      }

      if (block.name === "rewrite_scratchpad") {
        const content = String(input.content ?? "");
        const output = this.rewritePlannerScratchpad(plannerId, content);
        return this.plannerToolResult(plannerId, block, output);
      }

      if (block.name === "send_message") {
        const to = String(input.to ?? "").trim();
        const content = String(input.content ?? "");
        if (!to) return this.plannerToolResult(plannerId, block, "Error: missing to", true);
        this.appendInbox(to, {
          type: String(input.msg_type ?? "message"),
          from: plannerId,
          to,
          content,
          timestamp: Date.now(),
        });
        return this.plannerToolResult(plannerId, block, `Message sent to ${to}`);
      }

      if (block.name === "read_inbox") {
        const output = this.readAndDrainInbox(plannerId);
        return this.plannerToolResult(plannerId, block, output);
      }

      if (block.name === "list_agents") {
        const output = this.listAgentsText();
        return this.plannerToolResult(plannerId, block, output);
      }

      if (block.name === "tree_view") {
        const output = this.treeViewText();
        return this.plannerToolResult(plannerId, block, output);
      }

      if (block.name === "depth_info") {
        const output = this.depthInfo(plannerId);
        return this.plannerToolResult(plannerId, block, output);
      }

      if (block.name === "compression_ratios") {
        return this.plannerToolResult(
          plannerId,
          block,
          JSON.stringify({ worker: "100:1", sub_planner: "20:1", root: "10:1" }, null, 2)
        );
      }

      return this.plannerToolResult(plannerId, block, `Error: tool not allowed for planner: ${block.name}`, true);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.recordError(plannerId, message);
      return this.plannerToolResult(plannerId, block, `Error: ${message}`, true);
    }
  }

  private plannerToolsFor(plannerId: string): ToolDefinition[] {
    const spec = this.agents.get(plannerId);
    const canSpawnSub = Boolean(spec && spec.depth < MAX_HIERARCHY_DEPTH - 1);

    const tools: ToolDefinition[] = [
      {
        name: "spawn_worker",
        description: "Spawn worker for a leaf task.",
        input_schema: {
          type: "object",
          properties: {
            task: { type: "string" },
            name: { type: "string" },
            task_id: { type: "string" },
          },
          required: ["task"],
        },
      },
      {
        name: "auto_delegate",
        description: "Choose worker or sub planner by complexity heuristic.",
        input_schema: {
          type: "object",
          properties: {
            task: { type: "string" },
            task_id: { type: "string" },
          },
          required: ["task"],
        },
      },
      {
        name: "review_handoff",
        description: "Review direct child handoffs for this planner.",
        input_schema: {
          type: "object",
          properties: { include_diff: { type: "boolean" } },
        },
      },
      {
        name: "submit_aggregate_handoff",
        description: "Submit aggregate handoff for this subtree.",
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
        name: "submit_handoff",
        description: "Alias for submit_aggregate_handoff.",
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
        description: "Rewrite planner scratchpad.",
        input_schema: {
          type: "object",
          properties: { content: { type: "string" } },
          required: ["content"],
        },
      },
      {
        name: "send_message",
        description: "Send message to child inbox.",
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
        name: "list_agents",
        description: "List all known agents.",
        input_schema: { type: "object", properties: {} },
      },
      {
        name: "tree_view",
        description: "Show hierarchy tree.",
        input_schema: { type: "object", properties: {} },
      },
      {
        name: "depth_info",
        description: "Return planner depth and spawn capability.",
        input_schema: { type: "object", properties: {} },
      },
      {
        name: "compression_ratios",
        description: "Return role compression ratios.",
        input_schema: { type: "object", properties: {} },
      },
    ];

    if (canSpawnSub) {
      tools.splice(1, 0, {
        name: "spawn_sub_planner",
        description: "Spawn recursive sub planner for complex subtree.",
        input_schema: {
          type: "object",
          properties: {
            task: { type: "string" },
            name: { type: "string" },
            task_id: { type: "string" },
          },
          required: ["task"],
        },
      });
    }

    return tools;
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
        description: "Submit structured worker handoff upward.",
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

  private async runPlanner(plannerId: string, isRoot: boolean): Promise<string> {
    const spec = this.agents.get(plannerId);
    if (!spec) return `Error: planner ${plannerId} not found`;

    const rt = this.runtimeOf(plannerId);
    rt.taskId = spec.taskId;
    rt.startedAt = Date.now();

    const plannerMessages: Message[] = [
      {
        role: "user",
        content: `<assignment>task_id=${spec.taskId}\n${spec.assignedTask}</assignment>\nDelegate downward and aggregate upward.`,
      },
      {
        role: "user",
        content: `<depth>current=${spec.depth}, max=${MAX_HIERARCHY_DEPTH}</depth>`,
      },
      {
        role: "user",
        content: "<compression>worker=100:1, sub_planner=20:1, root=10:1</compression>",
      },
      {
        role: "user",
        content: `<scratchpad>${
          this.toolExecutor.fs.getFile(this.plannerScratchpadPath(plannerId)) ?? "(empty)"
        }</scratchpad>`,
      },
    ];

    let finalText = "";

    for (let turn = 0; turn < MAX_PLANNER_TURNS; turn += 1) {
      const inboxRaw = this.readAndDrainInbox(plannerId);
      if (inboxRaw !== "[]") {
        plannerMessages.push({
          role: "user",
          content: `<inbox>${inboxRaw}</inbox>`,
        });
      }

      const response = await createMessage({
        apiKey: this.config.apiKey,
        model: this.config.model,
        system: this.plannerSystem(plannerId),
        messages: plannerMessages,
        tools: this.plannerToolsFor(plannerId),
      });

      this.totalInputTokens += response.usage.input_tokens;
      this.totalOutputTokens += response.usage.output_tokens;
      rt.tokensUsed += response.usage.input_tokens + response.usage.output_tokens;
      rt.attempts += 1;
      rt.turns += 1;

      plannerMessages.push({ role: "assistant", content: response.content });

      if (response.stop_reason !== "tool_use") {
        finalText = this.extractText(response.content);
        rt.lastText = finalText;
        break;
      }

      const toolResults: ToolResultBlock[] = [];
      for (const block of response.content) {
        if (block.type !== "tool_use") continue;
        this.emit("tool_call", { planner: plannerId, name: block.name, input: block.input });
        toolResults.push(await this.executePlannerTool(plannerId, block as ToolUseBlock));
      }

      plannerMessages.push({ role: "user", content: toolResults });
      if (!isRoot && rt.handoffSubmitted) break;
    }

    if (!isRoot && !rt.handoffSubmitted) {
      await this.submitAggregateHandoff(plannerId, { task_id: spec.taskId });
    }

    spec.status = "idle";
    const worker = this.workers.get(plannerId);
    if (worker) worker.status = "idle";

    return finalText;
  }

  protected override async processToolCalls(content: ContentBlock[]): Promise<ToolResultBlock[]> {
    const results: ToolResultBlock[] = [];

    for (const block of content) {
      if (block.type !== "tool_use") continue;
      this.emit("tool_call", { name: block.name, input: block.input });
      results.push(await this.executePlannerTool(this.rootName, block as ToolUseBlock));
    }

    return results;
  }

  async run(userMessage: string): Promise<string> {
    this.aborted = false;

    const rootSpec = this.agents.get(this.rootName);
    if (!rootSpec) throw new Error("Root planner missing");

    const taskId = `root-${Date.now()}`;
    rootSpec.taskId = taskId;
    rootSpec.assignedTask = userMessage;
    rootSpec.status = "working";

    this.runtimes.set(this.rootName, this.createRuntime(this.rootName, taskId, "", {}));
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
      const rootRuntime = this.runtimeOf(this.rootName);
      rootRuntime.tokensUsed += response.usage.input_tokens + response.usage.output_tokens;
      rootRuntime.attempts += 1;
      rootRuntime.turns += 1;

      this.emit("llm_response", { stopReason: response.stop_reason });
      this.messages.push({ role: "assistant", content: response.content });
      this.emit("state_change");

      if (response.stop_reason !== "tool_use") {
        finalText = this.extractText(response.content);
        rootRuntime.lastText = finalText;
        break;
      }

      const toolResults = await this.processToolCalls(response.content);
      this.messages.push({ role: "user", content: toolResults });
      this.emit("state_change");
    }

    rootSpec.status = "idle";

    if (!finalText) {
      finalText = await this.runPlanner(this.rootName, true);
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }

  getTools(): ToolDefinition[] {
    return this.plannerToolsFor(this.rootName);
  }

  getSystemPrompt(): string {
    return ROOT_SYSTEM;
  }

  getState(): AgentState {
    const teammateRows = Array.from(this.workers.values()).map((worker) => ({
      name: worker.name,
      status: worker.status,
      currentTask:
        worker.role === "worker"
          ? `${worker.task} (${worker.workspacePath || "no-workspace"})`
          : `${worker.task} [sub_planner depth=${worker.depth}]`,
    }));

    return {
      ...super.getState(),
      teammates: [
        {
          name: this.rootName,
          status: this.agents.get(this.rootName)?.status ?? "idle",
          currentTask: this.agents.get(this.rootName)?.assignedTask,
        },
        ...teammateRows,
      ],
      handoffs: this.handoffs,
      scratchpads: Array.from(this.agents.values()).reduce<Record<string, string>>((acc, spec) => {
        const path =
          spec.role === "worker"
            ? this.workerScratchpadPath(spec.agentId)
            : this.plannerScratchpadPath(spec.agentId);
        acc[spec.agentId] = this.toolExecutor.fs.getFile(path) ?? "";
        return acc;
      }, {}),
      workspaces: Array.from(this.workers.values()).map((worker) => ({
        worker: worker.name,
        path: worker.workspacePath,
        cleaned: this.runtimes.get(worker.name)?.workspaceCleaned ?? false,
      })),
      hierarchy: this.treeViewText(),
      depthLimit: MAX_HIERARCHY_DEPTH,
    } as AgentState;
  }
}
