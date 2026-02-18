/**
 * s11 - Autonomous Agent
 *
 * When no direct work remains, the agent enters an idle loop that
 * polls the task board for unclaimed tasks and auto-claims them.
 * Builds on s10's protocol infrastructure.
 *
 *   AUTONOMOUS LIFECYCLE
 *   =====================
 *
 *   +-------+
 *   | start | --> WORK phase (tool_use loop)
 *   +---+---+     |  no more tool calls
 *       v         v
 *   +--------+  poll each cycle:
 *   | IDLE   |---> scan board for unclaimed tasks
 *   +---+----+     found? -> claim -> resume WORK
 *       |          maxIdleCycles? -> stop
 *       v
 *   [shutdown]
 *
 *   Task scanning: status=="pending" AND owner=="" AND blockedBy==[]
 *
 * Mechanism: Idle cycle + auto-claim + identity re-injection
 * Tools: bash, read_file, write_file, edit_file,
 *        spawn_teammate, list_teammates,
 *        send_message, read_inbox, broadcast,
 *        create_task, list_tasks, idle, claim_task (13 total)
 * LOC target: 250
 */

import {
  BaseAgent,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type AgentConfig, type AgentState,
  type TeammateInfo, type TaskItem,
} from "./shared";

interface Teammate { name: string; role: string; status: "idle" | "working" | "shutdown"; }
interface BoardTask { id: string; subject: string; status: "pending" | "in_progress" | "completed"; owner: string; blockedBy: string[]; }

export class AutonomousAgent extends BaseAgent {
  private teammates: Map<string, Teammate> = new Map();
  private tasks: BoardTask[] = [];
  private taskSeq = 0;
  private isIdle = false;
  private pollCount = 0;
  private lastPollTime = 0;
  private claimedTask: string | undefined;
  private maxIdleCycles: number;
  private agentName: string;

  constructor(config: AgentConfig & { maxIdleCycles?: number; agentName?: string }) {
    super(config);
    this.maxIdleCycles = config.maxIdleCycles ?? 5;
    this.agentName = config.agentName ?? "autonomous";
    this.registerAll();
  }

  private inboxPath(n: string): string { return `.team/inbox/${n}.jsonl`; }

  private appendInbox(to: string, msg: Record<string, unknown>): void {
    const p = this.inboxPath(to);
    const prev = this.toolExecutor.fs.getFile(p) ?? "";
    this.toolExecutor.fs.writeFile(p, prev + JSON.stringify(msg) + "\n");
  }

  private registerAll(): void {
    this.toolExecutor.registerTool("spawn_teammate", (i) => {
      const n = i.name as string;
      if (this.teammates.has(n)) return `Error: '${n}' exists`;
      this.teammates.set(n, { name: n, role: i.role as string, status: "idle" });
      return JSON.stringify({ name: n, status: "idle" });
    });
    this.toolExecutor.registerTool("list_teammates", () => {
      if (this.teammates.size === 0) return "No teammates.";
      return Array.from(this.teammates.values()).map((t) => `- ${t.name} [${t.status}]`).join("\n");
    });
    this.toolExecutor.registerTool("send_message", (i) => {
      this.appendInbox(i.to as string, { type: "message", from: this.agentName, to: i.to, content: i.content, timestamp: Date.now() });
      return `Message sent to ${i.to}`;
    });
    this.toolExecutor.registerTool("read_inbox", (i) => {
      const p = this.inboxPath(i.name as string);
      const raw = this.toolExecutor.fs.getFile(p);
      if (!raw || !raw.trim()) return "Inbox empty.";
      this.toolExecutor.fs.writeFile(p, "");
      return raw.trim();
    });
    this.toolExecutor.registerTool("broadcast", (i) => {
      let c = 0;
      for (const n of Array.from(this.teammates.keys())) {
        if (n !== this.agentName) {
          this.appendInbox(n, { type: "broadcast", from: this.agentName, to: n, content: i.content, timestamp: Date.now() });
          c++;
        }
      }
      return `Broadcast sent to ${c} teammates`;
    });
    this.toolExecutor.registerTool("create_task", (i) => {
      const t: BoardTask = { id: String(++this.taskSeq), subject: i.subject as string, status: "pending", owner: "", blockedBy: [] };
      this.tasks.push(t);
      return JSON.stringify({ id: t.id, subject: t.subject, status: t.status });
    });
    this.toolExecutor.registerTool("list_tasks", () => {
      if (this.tasks.length === 0) return "No tasks.";
      return this.tasks.map((t) => {
        const icon = t.status === "completed" ? "[x]" : t.status === "in_progress" ? "[>]" : "[ ]";
        return `#${t.id} ${icon} ${t.subject}${t.owner ? ` @${t.owner}` : ""}`;
      }).join("\n");
    });
    this.toolExecutor.registerTool("idle", () => {
      this.isIdle = true; this.pollCount = 0; this.claimedTask = undefined;
      return "Entering idle state. Will poll for unclaimed tasks.";
    });
    this.toolExecutor.registerTool("claim_task", (i) => {
      const id = i.task_id as string;
      const t = this.tasks.find((x) => x.id === id);
      if (!t) return `Error: Task #${id} not found`;
      if (t.status !== "pending" || t.owner || t.blockedBy.length > 0) return `Error: Task #${id} unavailable`;
      t.status = "in_progress"; t.owner = this.agentName; this.claimedTask = id; this.isIdle = false;
      return JSON.stringify({ id: t.id, subject: t.subject, status: "in_progress", owner: this.agentName });
    });
  }

  private scanUnclaimed(): BoardTask | null {
    return this.tasks.find((t) => t.status === "pending" && !t.owner && t.blockedBy.length === 0) ?? null;
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

    if (this.isIdle && !this.aborted) {
      for (let i = 0; i < this.maxIdleCycles; i++) {
        this.pollCount = i + 1;
        this.lastPollTime = Date.now();
        this.emit("state_change");

        const unclaimed = this.scanUnclaimed();
        if (unclaimed) {
          unclaimed.status = "in_progress";
          unclaimed.owner = this.agentName;
          this.claimedTask = unclaimed.id;
          this.isIdle = false;
          this.emit("state_change");

          this.messages.push({ role: "user", content: `Auto-claimed task #${unclaimed.id}: ${unclaimed.subject}. Work on it.` });
          while (this.loopIteration < (this.config.maxIterations || 10) * 2) {
            if (this.aborted) break;
            this.loopIteration++;
            const resp = await createMessage({
              apiKey: this.config.apiKey, model: this.config.model,
              system: this.getSystemPrompt(), messages: this.messages, tools: this.getTools(),
            });
            this.totalInputTokens += resp.usage.input_tokens;
            this.totalOutputTokens += resp.usage.output_tokens;
            this.messages.push({ role: "assistant", content: resp.content });
            this.emit("state_change");
            if (resp.stop_reason !== "tool_use") {
              finalText += "\n\n[Auto-claimed #" + unclaimed.id + "]\n" + this.extractText(resp.content);
              break;
            }
            const tr = await this.processToolCalls(resp.content);
            this.messages.push({ role: "user", content: tr });
            this.emit("state_change");
          }
          break;
        }
      }
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }

  getTools(): ToolDefinition[] {
    return [
      BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
      { name: "spawn_teammate", description: "Create a named teammate.",
        input_schema: { type: "object", properties: { name: { type: "string" }, role: { type: "string" } }, required: ["name", "role"] } },
      { name: "list_teammates", description: "Show team roster.",
        input_schema: { type: "object", properties: {} } },
      { name: "send_message", description: "Send a message to a teammate.",
        input_schema: { type: "object", properties: { to: { type: "string" }, content: { type: "string" } }, required: ["to", "content"] } },
      { name: "read_inbox", description: "Read a teammate's inbox.",
        input_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] } },
      { name: "broadcast", description: "Broadcast to all teammates.",
        input_schema: { type: "object", properties: { content: { type: "string" } }, required: ["content"] } },
      { name: "create_task", description: "Create a task on the shared board.",
        input_schema: { type: "object", properties: { subject: { type: "string" } }, required: ["subject"] } },
      { name: "list_tasks", description: "List all tasks.",
        input_schema: { type: "object", properties: {} } },
      { name: "idle", description: "Enter idle state. Polls board for unclaimed work.",
        input_schema: { type: "object", properties: {} } },
      { name: "claim_task", description: "Claim a pending task from the board.",
        input_schema: { type: "object", properties: { task_id: { type: "string" } }, required: ["task_id"] } },
    ];
  }

  getSystemPrompt(): string {
    return [
      "You are an autonomous agent that persists and picks up work.",
      "After finishing current work, call 'idle' to enter idle state.",
      "The system polls the task board for unclaimed tasks automatically.",
      "Use claim_task manually, or create_task to add items.",
    ].join("\n");
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      teammates: Array.from(this.teammates.values()).map((t) => ({ name: t.name, status: t.status, currentTask: t.role })),
      tasks: this.tasks.map((t) => ({ id: t.id, subject: t.subject, status: t.status, blockedBy: t.blockedBy })),
      idleCycle: { isIdle: this.isIdle, pollCount: this.pollCount, lastPollTime: this.lastPollTime, claimedTask: this.claimedTask },
    };
  }
}
