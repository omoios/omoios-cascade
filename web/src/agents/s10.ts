/**
 * s10 - Team Protocols
 *
 * Combined Shutdown Protocol + Plan Approval. Builds on s09's team
 * infrastructure, adding request_id-correlated shutdown and plan
 * approval workflows.
 *
 *   SHUTDOWN FSM                    PLAN APPROVAL FSM
 *   =============                   ==================
 *
 *   Lead:                           Teammate submits:
 *   shutdown_request(target)        plan_approval(from, plan)
 *     |-> request_id = uuid           |-> request_id = uuid
 *     |-> status = "pending"          |-> status = "pending"
 *     v                               v
 *   [pending] ----response--->      [pending] ----lead reviews--->
 *     / \                             / \
 *    v   v                           v   v
 *   [approved]  [rejected]         [approved]  [rejected + feedback]
 *
 * Mechanism: Shutdown + Plan approval protocols with request_id correlation
 * Tools: bash, read_file, write_file, edit_file,
 *        spawn_teammate, list_teammates,
 *        send_message, read_inbox, broadcast,
 *        shutdown_request, shutdown_response, plan_approval (12 total)
 * LOC target: 230
 */

import {
  BaseAgent,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type AgentConfig, type AgentState,
  type TeammateInfo, type InboxMessage,
} from "./shared";

import {
  TeammateManager, MessageBus,
  type MsgType, type StoredMsg,
} from "./s09";

interface ShutdownRec { id: string; target: string; status: "pending" | "approved" | "rejected"; }
interface PlanRec { id: string; from: string; status: "pending" | "approved" | "rejected"; plan?: string; }

export class TeamProtocolsAgent extends BaseAgent {
  private roster: TeammateManager;
  private bus: MessageBus;
  private shutdowns: ShutdownRec[] = [];
  private plans: PlanRec[] = [];
  private idSeq = 0;

  constructor(config: AgentConfig) {
    super(config);
    this.roster = new TeammateManager(this.toolExecutor.fs);
    this.bus = new MessageBus(this.toolExecutor.fs);
    this.registerAll();
  }

  private nextId(): string { return `req_${++this.idSeq}`; }

  private registerAll(): void {
    this.toolExecutor.registerTool("spawn_teammate", (i) => {
      return this.roster.spawn(i.name as string, i.role as string);
    });
    this.toolExecutor.registerTool("list_teammates", () => {
      const l = this.roster.list();
      return l.length === 0 ? "No teammates." : l.map((t) => `- ${t.name} [${t.status}]`).join("\n");
    });
    this.toolExecutor.registerTool("send_message", (i) => {
      return this.bus.send("lead", i.to as string, i.content as string, (i.type as MsgType) ?? "message");
    });
    this.toolExecutor.registerTool("read_inbox", (i) => {
      const msgs = this.bus.read(i.name as string);
      return msgs.length === 0 ? "Inbox empty." : JSON.stringify(msgs, null, 2);
    });
    this.toolExecutor.registerTool("broadcast", (i) => {
      const names = Array.from(this.roster.teammates.keys());
      return this.bus.broadcast("lead", names, i.content as string);
    });

    this.toolExecutor.registerTool("shutdown_request", (i) => {
      const target = i.target as string;
      if (!this.roster.teammates.has(target)) return `Error: '${target}' not found`;
      const id = this.nextId();
      this.shutdowns.push({ id, target, status: "pending" });
      this.bus.send("lead", target, "Please shut down gracefully.", "shutdown_request", id);
      return JSON.stringify({ requestId: id, target, status: "pending" });
    });
    this.toolExecutor.registerTool("shutdown_response", (i) => {
      const id = i.request_id as string;
      const approve = i.approve as boolean;
      const rec = this.shutdowns.find((r) => r.id === id);
      if (!rec) return `Error: No request '${id}'`;
      rec.status = approve ? "approved" : "rejected";
      if (approve) {
        this.roster.setStatus(rec.target, "shutdown");
      }
      return JSON.stringify({ requestId: id, status: rec.status });
    });

    this.toolExecutor.registerTool("plan_approval", (i) => {
      const approve = i.approve as boolean | undefined;
      if (approve === undefined) {
        const id = this.nextId();
        this.plans.push({ id, from: i.from as string, status: "pending", plan: i.plan as string });
        return JSON.stringify({ requestId: id, status: "pending" });
      }
      const id = i.request_id as string;
      const rec = this.plans.find((r) => r.id === id);
      if (!rec) return `Error: No plan '${id}'`;
      rec.status = approve ? "approved" : "rejected";
      this.bus.send("lead", rec.from,
        approve ? "Plan approved." : `Plan rejected: ${i.feedback ?? ""}`,
        "plan_approval_response", id);
      return JSON.stringify({ requestId: id, status: rec.status });
    });
  }

  getTools(): ToolDefinition[] {
    return [
      BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
      { name: "spawn_teammate", description: "Create a named teammate.",
        input_schema: { type: "object", properties: { name: { type: "string" }, role: { type: "string" } }, required: ["name", "role"] } },
      { name: "list_teammates", description: "Show team roster.",
        input_schema: { type: "object", properties: {} } },
      { name: "send_message", description: "Send a message to a teammate.",
        input_schema: { type: "object", properties: { to: { type: "string" }, content: { type: "string" }, type: { type: "string" } }, required: ["to", "content"] } },
      { name: "read_inbox", description: "Read a teammate's inbox.",
        input_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] } },
      { name: "broadcast", description: "Send to all teammates.",
        input_schema: { type: "object", properties: { content: { type: "string" } }, required: ["content"] } },
      { name: "shutdown_request", description: "Send shutdown request with tracked request_id.",
        input_schema: { type: "object", properties: { target: { type: "string" } }, required: ["target"] } },
      { name: "shutdown_response", description: "Approve or reject a shutdown request by request_id.",
        input_schema: { type: "object", properties: { request_id: { type: "string" }, approve: { type: "boolean" } }, required: ["request_id", "approve"] } },
      { name: "plan_approval", description: "Submit or review a plan. Omit approve to submit; provide approve to review.",
        input_schema: { type: "object", properties: {
          from: { type: "string" }, plan: { type: "string" },
          request_id: { type: "string" }, approve: { type: "boolean" }, feedback: { type: "string" },
        }, required: ["from"] } },
    ];
  }

  getSystemPrompt(): string {
    return [
      "You are a Team Lead with shutdown and plan approval protocols.",
      "- shutdown_request: send tracked shutdown to a teammate",
      "- shutdown_response: approve/reject using request_id",
      "- plan_approval: submit (with plan) or review (with request_id + approve)",
      "Protocol states: pending -> approved | rejected.",
    ].join("\n");
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      teammates: this.roster.list(),
      protocolState: {
        shutdownRequests: this.shutdowns.map((r) => ({ ...r })),
        planApprovals: this.plans.map((r) => ({ id: r.id, from: r.from, status: r.status })),
      },
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
