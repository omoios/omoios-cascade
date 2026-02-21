import {
  createMessage,
  type AgentConfig,
  type AgentState,
  type ContentBlock,
  type Message,
  type ToolDefinition,
  type ToolResultBlock,
  type ToolUseBlock,
} from "./shared";
import { ErrorTolerantAgent } from "./s18";

type ActivityEventType =
  | "llm_call"
  | "tool_call"
  | "file_write"
  | "file_edit"
  | "heartbeat"
  | "interrupt"
  | "killed"
  | "respawned";

type WatchdogMode = "zombie" | "tunnel_vision" | "token_burn";

interface ActivityEvent {
  timestamp: number;
  agent: string;
  type: ActivityEventType;
  details: Record<string, unknown>;
}

interface TrackedWorker {
  name: string;
  task: string;
  taskId: string;
  status: "idle" | "working" | "shutdown";
  lastHeartbeat: number;
  editCounts: Record<string, number>;
  llmCallsWithoutWrite: number;
  totalLlmCalls: number;
  respawns: number;
}

interface WatchdogReport {
  id: string;
  timestamp: number;
  mode: WatchdogMode;
  worker: string;
  action: "interrupt" | "kill_and_respawn";
  reason: string;
  metadata: Record<string, unknown>;
}

interface WatchdogFinding {
  mode: WatchdogMode;
  worker: string;
  action: "interrupt" | "kill_and_respawn";
  reason: string;
  metadata: Record<string, unknown>;
}

export class Watchdog {
  private readonly zombieMs: number;
  private readonly tunnelVisionEdits: number;
  private readonly tokenBurnCalls: number;
  private readonly cooldownMs: number;
  private readonly lastTriggered = new Map<string, number>();
  private readonly trackedWorkers = new Map<string, TrackedWorker & { scope: string }>();
  private readonly recoveryEvents: Array<{
    timestamp: number;
    agentId: string;
    failureType: WatchdogMode;
    action: "interrupt" | "killed" | "respawned";
  }> = [];

  constructor(config: {
    zombieMs?: number;
    tunnelVisionEdits?: number;
    tokenBurnCalls?: number;
    cooldownMs?: number;
  }) {
    this.zombieMs = Math.max(1, Math.floor(config.zombieMs ?? 60_000));
    this.tunnelVisionEdits = Math.max(1, Math.floor(config.tunnelVisionEdits ?? 20));
    this.tokenBurnCalls = Math.max(1, Math.floor(config.tokenBurnCalls ?? 50));
    this.cooldownMs = Math.max(500, Math.floor(config.cooldownMs ?? 15_000));
  }

  private ensureTracked(agentId: string): TrackedWorker & { scope: string } {
    const existing = this.trackedWorkers.get(agentId);
    if (existing) return existing;

    const created: TrackedWorker & { scope: string } = {
      name: agentId,
      task: "",
      taskId: "",
      status: "working",
      lastHeartbeat: Date.now(),
      editCounts: {},
      llmCallsWithoutWrite: 0,
      totalLlmCalls: 0,
      respawns: 0,
      scope: "",
    };
    this.trackedWorkers.set(agentId, created);
    return created;
  }

  registerAgent(agentId: string, scope = ""): string {
    const worker = this.ensureTracked(agentId);
    worker.scope = scope;
    worker.status = "working";
    worker.lastHeartbeat = Date.now();
    return `Registered ${agentId}`;
  }

  register_agent(agentId: string, scope = ""): string {
    return this.registerAgent(agentId, scope);
  }

  trackAgent(agentId: string, scope = ""): string {
    return this.registerAgent(agentId, scope);
  }

  heartbeat(agentId: string): string {
    const worker = this.ensureTracked(agentId);
    worker.lastHeartbeat = Date.now();
    if (worker.status === "shutdown") worker.status = "working";
    return `Heartbeat ${agentId}`;
  }

  touch(agentId: string): string {
    return this.heartbeat(agentId);
  }

  ping(agentId: string): string {
    return this.heartbeat(agentId);
  }

  recordActivity(agentId: string, input: Record<string, unknown>): string {
    const worker = this.ensureTracked(agentId);
    const action = String(input.action ?? input.type ?? "").toLowerCase();
    const filePath = String(input.file ?? input.path ?? "").trim();

    if (action.includes("edit") || action.includes("write")) {
      if (filePath) {
        worker.editCounts[filePath] = (worker.editCounts[filePath] ?? 0) + 1;
      }
      worker.llmCallsWithoutWrite = 0;
    }

    if (action.includes("llm") || typeof input.tokens === "number") {
      worker.totalLlmCalls += 1;
      worker.llmCallsWithoutWrite += 1;
    }

    if (action.includes("heartbeat")) {
      worker.lastHeartbeat = Date.now();
    }

    return `Activity recorded for ${agentId}`;
  }

  record_activity(agentId: string, input: Record<string, unknown>): string {
    return this.recordActivity(agentId, input);
  }

  trackActivity(agentId: string, input: Record<string, unknown>): string {
    return this.recordActivity(agentId, input);
  }

  logActivity(agentId: string, input: Record<string, unknown>): string {
    return this.recordActivity(agentId, input);
  }

  private inCooldown(key: string, now: number): boolean {
    const last = this.lastTriggered.get(key);
    if (!last) return false;
    return now - last < this.cooldownMs;
  }

  private markTriggered(key: string, now: number): void {
    this.lastTriggered.set(key, now);
  }

  evaluate(workers: TrackedWorker[], now = Date.now()): WatchdogFinding[] {
    const findings: WatchdogFinding[] = [];

    for (const worker of workers) {
      if (worker.status !== "working") continue;

      const zombieDelta = now - worker.lastHeartbeat;
      const zombieKey = `${worker.name}:zombie`;
      if (zombieDelta > this.zombieMs && !this.inCooldown(zombieKey, now)) {
        findings.push({
          mode: "zombie",
          worker: worker.name,
          action: "kill_and_respawn",
          reason: `No heartbeat for ${Math.floor(zombieDelta / 1000)}s (> ${Math.floor(this.zombieMs / 1000)}s).`,
          metadata: {
            stale_ms: zombieDelta,
            threshold_ms: this.zombieMs,
          },
        });
        this.markTriggered(zombieKey, now);
        continue;
      }

      const maxEdit = Object.values(worker.editCounts).reduce((best, value) => Math.max(best, value), 0);
      const tunnelFile =
        Object.entries(worker.editCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "(unknown)";
      const tunnelKey = `${worker.name}:tunnel_vision`;
      if (maxEdit > this.tunnelVisionEdits && !this.inCooldown(tunnelKey, now)) {
        findings.push({
          mode: "tunnel_vision",
          worker: worker.name,
          action: "interrupt",
          reason: `Edited '${tunnelFile}' ${maxEdit} times (> ${this.tunnelVisionEdits}).`,
          metadata: {
            path: tunnelFile,
            edits: maxEdit,
            threshold_edits: this.tunnelVisionEdits,
          },
        });
        this.markTriggered(tunnelKey, now);
      }

      const burnKey = `${worker.name}:token_burn`;
      if (worker.llmCallsWithoutWrite > this.tokenBurnCalls && !this.inCooldown(burnKey, now)) {
        findings.push({
          mode: "token_burn",
          worker: worker.name,
          action: "interrupt",
          reason: `LLM calls without writes: ${worker.llmCallsWithoutWrite} (> ${this.tokenBurnCalls}).`,
          metadata: {
            llm_calls_without_write: worker.llmCallsWithoutWrite,
            threshold_calls: this.tokenBurnCalls,
            total_llm_calls: worker.totalLlmCalls,
          },
        });
        this.markTriggered(burnKey, now);
      }
    }

    return findings;
  }

  private asFindings(now = Date.now()): Array<{ agentId: string; failureType: WatchdogMode; action: string; reason: string }> {
    const workers = Array.from(this.trackedWorkers.values()).map<TrackedWorker>((worker) => ({
      name: worker.name,
      task: worker.task,
      taskId: worker.taskId,
      status: worker.status,
      lastHeartbeat: worker.lastHeartbeat,
      editCounts: worker.editCounts,
      llmCallsWithoutWrite: worker.llmCallsWithoutWrite,
      totalLlmCalls: worker.totalLlmCalls,
      respawns: worker.respawns,
    }));

    return this.evaluate(workers, now).map((finding) => ({
      agentId: finding.worker,
      failureType: finding.mode,
      action: finding.action,
      reason: finding.reason,
    }));
  }

  detectFailures(now = Date.now()): Array<{ agentId: string; failureType: WatchdogMode; action: string; reason: string }> {
    return this.asFindings(now);
  }

  checkFailures(now = Date.now()): Array<{ agentId: string; failureType: WatchdogMode; action: string; reason: string }> {
    return this.asFindings(now);
  }

  inspectFailures(now = Date.now()): Array<{ agentId: string; failureType: WatchdogMode; action: string; reason: string }> {
    return this.asFindings(now);
  }

  runDetection(now = Date.now()): Array<{ agentId: string; failureType: WatchdogMode; action: string; reason: string }> {
    return this.asFindings(now);
  }

  _checkFailures(now = Date.now()): Array<{ agentId: string; failureType: WatchdogMode; action: string; reason: string }> {
    return this.asFindings(now);
  }

  private recordRecovery(agentId: string, failureType: WatchdogMode, action: "interrupt" | "killed" | "respawned"): void {
    this.recoveryEvents.push({
      timestamp: Date.now(),
      agentId,
      failureType,
      action,
    });
  }

  killAndRespawn(payload: Record<string, unknown>): string {
    const agentId = String(payload.agentId ?? payload.agent_id ?? "").trim();
    if (!agentId) return "Error: missing agentId";

    const rawFailure = String(payload.failureType ?? payload.failure_type ?? "zombie").toLowerCase();
    const failureType: WatchdogMode = rawFailure.includes("token")
      ? "token_burn"
      : rawFailure.includes("tunnel")
        ? "tunnel_vision"
        : "zombie";

    const stale = this.ensureTracked(agentId);
    stale.status = "shutdown";
    stale.respawns += 1;
    this.recordRecovery(agentId, failureType, "killed");

    const respawnId = `${agentId}-r${stale.respawns}`;
    const respawned: TrackedWorker & { scope: string } = {
      ...stale,
      name: respawnId,
      status: "working",
      lastHeartbeat: Date.now(),
      editCounts: {},
      llmCallsWithoutWrite: 0,
      totalLlmCalls: 0,
    };
    this.trackedWorkers.set(respawnId, respawned);
    this.recordRecovery(respawnId, failureType, "respawned");

    return `Killed ${agentId}; respawned ${respawnId}`;
  }

  handleFailure(payload: Record<string, unknown>): string {
    const rawFailure = String(payload.failureType ?? payload.failure_type ?? "zombie").toLowerCase();
    const failureType: WatchdogMode = rawFailure.includes("token")
      ? "token_burn"
      : rawFailure.includes("tunnel")
        ? "tunnel_vision"
        : "zombie";

    const agentId = String(payload.agentId ?? payload.agent_id ?? "").trim();
    if (!agentId) return "Error: missing agentId";

    if (failureType === "zombie") {
      return this.killAndRespawn({ agentId, failureType });
    }

    this.recordRecovery(agentId, failureType, "interrupt");
    return `Interrupted ${agentId} for ${failureType}`;
  }

  applyRecovery(payload: Record<string, unknown>): string {
    return this.handleFailure(payload);
  }

  recoverFailure(payload: Record<string, unknown>): string {
    return this.handleFailure(payload);
  }

  snapshot() {
    return {
      zombie_ms: this.zombieMs,
      tunnel_vision_edits: this.tunnelVisionEdits,
      token_burn_calls: this.tokenBurnCalls,
      cooldown_ms: this.cooldownMs,
      tracked_workers: Array.from(this.trackedWorkers.values()).map((worker) => ({
        name: worker.name,
        status: worker.status,
        respawns: worker.respawns,
        max_path_edits: Object.values(worker.editCounts).reduce((best, value) => Math.max(best, value), 0),
      })),
      recovery_events: this.recoveryEvents.slice(-50),
    };
  }
}

export class FailureModesRecoveryAgent extends ErrorTolerantAgent {
  private readonly watchdog: Watchdog;
  private readonly activityLog: ActivityEvent[] = [];
  private readonly workerRegistry = new Map<string, TrackedWorker>();
  private readonly watchdogReports: WatchdogReport[] = [];

  constructor(
    config: AgentConfig & {
      plannerName?: string;
      errorBudget?: number;
      zombieMs?: number;
      tunnelVisionEdits?: number;
      tokenBurnCalls?: number;
      watchdogCooldownMs?: number;
    }
  ) {
    super(config);
    this.watchdog = new Watchdog({
      zombieMs: config.zombieMs,
      tunnelVisionEdits: config.tunnelVisionEdits,
      tokenBurnCalls: config.tokenBurnCalls,
      cooldownMs: config.watchdogCooldownMs,
    });
  }

  override getSystemPrompt(): string {
    return [
      super.getSystemPrompt(),
      "Failure-mode watchdog policy:",
      "- Zombie worker (>60s no heartbeat): kill and respawn with same task.",
      "- Tunnel vision (>20 edits same path): interrupt and force strategy change.",
      "- Token burn (>50 LLM calls without writes): interrupt and request partial handoff.",
      "- Watchdog monitors independently and reports every action.",
    ].join("\n");
  }

  override getTools(): ToolDefinition[] {
    return [
      ...super.getTools(),
      {
        name: "log_activity",
        description: "Append one activity event for an agent (JSONL-backed).",
        input_schema: {
          type: "object",
          properties: {
            agent: { type: "string" },
            event: {
              type: "string",
              enum: ["llm_call", "tool_call", "file_write", "file_edit", "heartbeat", "interrupt", "killed", "respawned"],
            },
            details: { type: "object" },
          },
          required: ["agent", "event"],
        },
      },
      {
        name: "watchdog_tick",
        description: "Run watchdog scan now and execute recovery actions.",
        input_schema: {
          type: "object",
          properties: {
            now_ms: { type: "integer" },
          },
        },
      },
      {
        name: "list_watchdog_reports",
        description: "List recent watchdog detections and actions.",
        input_schema: {
          type: "object",
          properties: {
            limit: { type: "integer" },
          },
        },
      },
      {
        name: "list_activity_log",
        description: "List activity events with optional agent filter.",
        input_schema: {
          type: "object",
          properties: {
            agent: { type: "string" },
            limit: { type: "integer" },
          },
        },
      },
    ];
  }

  private toActivityPath(agent: string): string {
    return `.activity/${agent}.jsonl`;
  }

  private toWorkerTask(value: unknown): string {
    const raw = String(value ?? "").trim();
    const idx = raw.lastIndexOf(" (");
    return idx > 0 ? raw.slice(0, idx) : raw;
  }

  private getWorker(name: string): TrackedWorker {
    const existing = this.workerRegistry.get(name);
    if (existing) return existing;

    const created: TrackedWorker = {
      name,
      task: "",
      taskId: "",
      status: "idle",
      lastHeartbeat: Date.now(),
      editCounts: {},
      llmCallsWithoutWrite: 0,
      totalLlmCalls: 0,
      respawns: 0,
    };
    this.workerRegistry.set(name, created);
    return created;
  }

  private appendActivity(agent: string, type: ActivityEventType, details: Record<string, unknown> = {}): void {
    const timestamp = Date.now();
    const event: ActivityEvent = { timestamp, agent, type, details };
    this.activityLog.push(event);

    const path = this.toActivityPath(agent);
    const prev = this.toolExecutor.fs.getFile(path) ?? "";
    this.toolExecutor.fs.writeFile(path, `${prev}${JSON.stringify(event)}\n`);

    if (agent.startsWith("worker")) {
      const worker = this.getWorker(agent);
      worker.lastHeartbeat = timestamp;
      if (type === "llm_call") {
        worker.totalLlmCalls += 1;
        worker.llmCallsWithoutWrite += 1;
      }
      if (type === "file_write" || type === "file_edit") {
        const pathValue = String(details.path ?? "(unknown)");
        worker.editCounts[pathValue] = (worker.editCounts[pathValue] ?? 0) + 1;
        worker.llmCallsWithoutWrite = 0;
      }
      if (type === "killed") {
        worker.status = "shutdown";
      }
      if (type === "respawned") {
        worker.status = "working";
      }
    }
  }

  private syncWorkersFromState(): void {
    const state = super.getState() as AgentState & { teammates?: Array<Record<string, unknown>> };
    const teammates = Array.isArray(state.teammates) ? state.teammates : [];

    for (const teammate of teammates) {
      const name = String(teammate.name ?? "");
      if (!name.startsWith("worker")) continue;
      const worker = this.getWorker(name);
      const status = teammate.status;
      if (status === "idle" || status === "working" || status === "shutdown") {
        worker.status = status;
      }

      const maybeTask = this.toWorkerTask(teammate.currentTask);
      if (maybeTask) worker.task = maybeTask;
    }
  }

  private parseSpawnResult(output: string): { name: string; taskId: string } | null {
    const match = output.match(/Spawned '([^']+)' with task_id=([^\s]+)/);
    if (!match) return null;
    return { name: match[1], taskId: match[2] };
  }

  private listActivityLog(input: Record<string, unknown>): string {
    const agent = typeof input.agent === "string" ? input.agent : undefined;
    const rawLimit = Number(input.limit ?? 200);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.floor(rawLimit) : 200;

    const selected = this.activityLog.filter((event) => !agent || event.agent === agent);
    return JSON.stringify(selected.slice(-limit), null, 2);
  }

  private listWatchdogReports(input: Record<string, unknown>): string {
    const rawLimit = Number(input.limit ?? 100);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.floor(rawLimit) : 100;
    return JSON.stringify(this.watchdogReports.slice(-limit), null, 2);
  }

  private async respawnWorker(stale: TrackedWorker): Promise<string> {
    stale.status = "shutdown";
    this.appendActivity(stale.name, "killed", { reason: "watchdog:zombie" });

    const nextRespawn = stale.respawns + 1;
    const respawnName = `${stale.name}-r${nextRespawn}`;
    const respawnTaskId = `${stale.taskId || "task"}-r${nextRespawn}`;

    const synthetic: ToolUseBlock = {
      type: "tool_use",
      id: `watchdog-respawn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: "spawn_worker",
      input: {
        name: respawnName,
        task: stale.task || "Recover interrupted worker task",
        task_id: respawnTaskId,
      },
    };

    const results = await super.processToolCalls([synthetic]);
    const output = results[0]?.content ?? "";

    const next = this.getWorker(respawnName);
    next.task = stale.task;
    next.taskId = respawnTaskId;
    next.status = output.startsWith("Error:") ? "shutdown" : "working";
    next.respawns = nextRespawn;
    next.lastHeartbeat = Date.now();

    stale.respawns = nextRespawn;
    this.appendActivity(respawnName, "respawned", {
      previous_worker: stale.name,
      task_id: respawnTaskId,
      spawn_result: output,
    });

    return output.startsWith("Error:")
      ? `Respawn failed for ${stale.name}: ${output}`
      : `Respawned as ${respawnName} (${respawnTaskId})`;
  }

  private async runWatchdogTick(now = Date.now()): Promise<string> {
    this.syncWorkersFromState();
    const workers = Array.from(this.workerRegistry.values());
    const findings = this.watchdog.evaluate(workers, now);

    if (findings.length === 0) return "Watchdog: no failure modes detected.";

    const outputs: string[] = [];

    for (const finding of findings) {
      const report: WatchdogReport = {
        id: `wd-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        timestamp: now,
        mode: finding.mode,
        worker: finding.worker,
        action: finding.action,
        reason: finding.reason,
        metadata: finding.metadata,
      };
      this.watchdogReports.push(report);

      if (finding.action === "interrupt") {
        const worker = this.getWorker(finding.worker);
        this.appendActivity(worker.name, "interrupt", {
          mode: finding.mode,
          reason: finding.reason,
        });
        outputs.push(`Interrupt ${worker.name}: ${finding.reason}`);
        continue;
      }

      const stale = this.getWorker(finding.worker);
      const respawnOut = await this.respawnWorker(stale);
      outputs.push(`Kill+respawn ${finding.worker}: ${respawnOut}`);
    }

    return outputs.join("\n");
  }

  protected override async processToolCalls(content: ContentBlock[]): Promise<ToolResultBlock[]> {
    const results: ToolResultBlock[] = [];

    for (const block of content) {
      if (block.type !== "tool_use") continue;
      const input = block.input as Record<string, unknown>;
      this.appendActivity("planner", "tool_call", { tool: block.name });

      if (block.name === "log_activity") {
        this.emit("tool_call", { name: block.name, input });
        const agent = String(input.agent ?? "").trim();
        const event = String(input.event ?? "").trim() as ActivityEventType;
        if (!agent) {
          const result: ToolResultBlock = {
            type: "tool_result",
            tool_use_id: block.id,
            content: "Error: missing agent",
            is_error: true,
          };
          results.push(result);
          this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: result.content, is_error: true });
          continue;
        }

        const allowed: ActivityEventType[] = [
          "llm_call",
          "tool_call",
          "file_write",
          "file_edit",
          "heartbeat",
          "interrupt",
          "killed",
          "respawned",
        ];
        if (!allowed.includes(event)) {
          const result: ToolResultBlock = {
            type: "tool_result",
            tool_use_id: block.id,
            content: `Error: unsupported event '${event}'`,
            is_error: true,
          };
          results.push(result);
          this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: result.content, is_error: true });
          continue;
        }

        const details =
          input.details && typeof input.details === "object"
            ? (input.details as Record<string, unknown>)
            : {};
        this.appendActivity(agent, event, details);

        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: `Activity logged for ${agent}: ${event}`,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: result.content, is_error: false });
        continue;
      }

      if (block.name === "watchdog_tick") {
        this.emit("tool_call", { name: block.name, input });
        const nowInput = Number(input.now_ms);
        const now = Number.isFinite(nowInput) && nowInput > 0 ? Math.floor(nowInput) : Date.now();
        const output = await this.runWatchdogTick(now);
        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: output,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: output, is_error: false });
        continue;
      }

      if (block.name === "list_watchdog_reports") {
        this.emit("tool_call", { name: block.name, input });
        const output = this.listWatchdogReports(input);
        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: output,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: output, is_error: false });
        continue;
      }

      if (block.name === "list_activity_log") {
        this.emit("tool_call", { name: block.name, input });
        const output = this.listActivityLog(input);
        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: output,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: output, is_error: false });
        continue;
      }

      const delegated = await super.processToolCalls([block]);
      const delegatedResult = delegated[0] ?? {
        type: "tool_result" as const,
        tool_use_id: block.id,
        content: "",
      };
      results.push(delegatedResult);

      if (block.name === "spawn_worker" && !delegatedResult.content.startsWith("Error:")) {
        const parsed = this.parseSpawnResult(delegatedResult.content);
        const explicitName = typeof input.name === "string" ? input.name.trim() : "";
        const workerName = parsed?.name ?? explicitName;
        if (workerName) {
          const worker = this.getWorker(workerName);
          worker.task = String(input.task ?? worker.task ?? "").trim();
          worker.taskId = parsed?.taskId ?? String(input.task_id ?? worker.taskId ?? "").trim();
          worker.status = "working";
          worker.lastHeartbeat = Date.now();
          this.appendActivity(workerName, "heartbeat", { source: "spawn_worker" });
        }
      }

      this.syncWorkersFromState();
    }

    const autoWatchdogOutput = await this.runWatchdogTick();
    if (autoWatchdogOutput !== "Watchdog: no failure modes detected.") {
      this.messages.push({
        role: "assistant",
        content: [{ type: "text", text: `Watchdog action:\n${autoWatchdogOutput}` }],
      });
      this.emit("state_change");
    }

    return results;
  }

  override async run(userMessage: string): Promise<string> {
    this.aborted = false;
    this.messages.push({ role: "user", content: userMessage });
    this.emit("state_change");

    let finalText = "";

    while (this.loopIteration < (this.config.maxIterations || 10)) {
      if (this.aborted) break;
      this.loopIteration += 1;

      let response: Awaited<ReturnType<typeof createMessage>> | null = null;

      this.appendActivity("planner", "llm_call", { iteration: this.loopIteration });

      try {
        response = await createMessage({
          apiKey: this.config.apiKey,
          model: this.config.model,
          system: this.getSystemPrompt(),
          messages: this.messages,
          tools: this.getTools(),
        });
      } catch (error) {
        const fallback: Message = {
          role: "assistant",
          content: [{ type: "text", text: `LLM call failed: ${error instanceof Error ? error.message : String(error)}` }],
        };
        this.messages.push(fallback);
        this.emit("state_change");
        await this.runWatchdogTick();
        continue;
      }

      this.totalInputTokens += response.usage.input_tokens;
      this.totalOutputTokens += response.usage.output_tokens;
      this.emit("llm_response", { stopReason: response.stop_reason });

      this.messages.push({ role: "assistant", content: response.content });
      this.emit("state_change");

      if (response.stop_reason !== "tool_use") {
        finalText = this.extractText(response.content);
        await this.runWatchdogTick();
        break;
      }

      const toolResults = await this.processToolCalls(response.content);
      this.messages.push({ role: "user", content: toolResults });
      this.emit("state_change");
    }

    if (!finalText && this.watchdogReports.length > 0) {
      finalText = `Completed with watchdog activity: ${this.watchdogReports.length} report(s).`;
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }

  override getState(): AgentState {
    return {
      ...super.getState(),
      watchdog: this.watchdog.snapshot(),
      watchdogReports: this.watchdogReports,
      activityLog: this.activityLog,
      trackedWorkers: Array.from(this.workerRegistry.values()).map((worker) => ({
        ...worker,
        max_path_edits: Object.values(worker.editCounts).reduce((best, value) => Math.max(best, value), 0),
      })),
    } as AgentState;
  }
}

export { FailureModesRecoveryAgent as FailureModesAgent };
export { FailureModesRecoveryAgent as WatchdogRecoveryAgent };
export default FailureModesRecoveryAgent;
