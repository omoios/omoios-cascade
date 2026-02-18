/**
 * s09 - Team Messaging
 *
 * Combined Team Foundation + Messaging. TeammateManager creates persistent
 * named agents with identity. MessageBus provides file-based JSONL inboxes
 * per teammate with 5 message types and read-and-drain semantics.
 *
 *   MESSAGE ROUTING
 *   ===============
 *
 *   Team Lead                     .team/inbox/
 *   +-----------+                 +-----------------+
 *   | send_msg  |  point-to-point | alice.jsonl     |
 *   |           +---------------->| {"from":"lead"} |
 *   +-----------+                 +-----------------+
 *   | broadcast |  to all         | bob.jsonl       |
 *   |           +---------------->| {"from":"lead"} |
 *   +-----------+                 +-----------------+
 *
 *   read_inbox() drains: returns all messages, then clears the file.
 *
 *   Message types:
 *   message | broadcast | shutdown_request |
 *   shutdown_response | plan_approval_response
 *
 * Mechanism: TeammateManager + MessageBus + JSONL inbox
 * Tools: bash, read_file, write_file, edit_file,
 *        spawn_teammate, list_teammates,
 *        send_message, read_inbox, broadcast (9 total)
 * LOC target: 200
 */

import {
  BaseAgent,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type AgentConfig, type AgentState,
  type TeammateInfo, type InboxMessage,
} from "./shared";

export type MsgType = "message" | "broadcast" | "shutdown_request" | "shutdown_response" | "plan_approval_response";

export interface Teammate {
  name: string;
  role: string;
  status: "idle" | "working" | "shutdown";
}

export interface StoredMsg {
  type: MsgType;
  from: string;
  to: string;
  content: string;
  timestamp: number;
  requestId?: string;
}

export class TeammateManager {
  teammates: Map<string, Teammate> = new Map();
  private fs: { writeFile: (p: string, c: string) => string };

  constructor(fs: { writeFile: (p: string, c: string) => string }) {
    this.fs = fs;
  }

  spawn(name: string, role: string): string {
    if (this.teammates.has(name)) return `Error: '${name}' already exists`;
    this.teammates.set(name, { name, role, status: "idle" });
    this.persistConfig();
    return JSON.stringify({ name, role, status: "idle" });
  }

  list(): TeammateInfo[] {
    return Array.from(this.teammates.values()).map((t) => ({
      name: t.name, status: t.status, currentTask: t.role,
    }));
  }

  setStatus(name: string, status: Teammate["status"]): void {
    const t = this.teammates.get(name);
    if (t) { t.status = status; this.persistConfig(); }
  }

  persistConfig(): void {
    this.fs.writeFile(".team/config.json",
      JSON.stringify({ members: Array.from(this.teammates.values()) }, null, 2));
  }
}

export class MessageBus {
  constructor(private fs: {
    writeFile: (p: string, c: string) => string;
    getFile: (p: string) => string | undefined;
  }) {}

  private path(name: string): string { return `.team/inbox/${name}.jsonl`; }

  send(from: string, to: string, content: string, type: MsgType = "message", requestId?: string): string {
    const p = this.path(to);
    const existing = this.fs.getFile(p) ?? "";
    const msg: StoredMsg = { type, from, to, content, timestamp: Date.now() };
    if (requestId) msg.requestId = requestId;
    this.fs.writeFile(p, existing + JSON.stringify(msg) + "\n");
    return `Message sent to ${to}`;
  }

  broadcast(from: string, names: string[], content: string): string {
    let n = 0;
    for (const name of names) {
      if (name !== from) { this.send(from, name, content, "broadcast"); n++; }
    }
    return `Broadcast sent to ${n} teammates`;
  }

  read(name: string): InboxMessage[] {
    const raw = this.fs.getFile(this.path(name));
    if (!raw || !raw.trim()) return [];
    this.fs.writeFile(this.path(name), "");
    return raw.trim().split("\n").filter(Boolean).map((line) => {
      const m = JSON.parse(line) as StoredMsg;
      return { type: m.type, from: m.from, content: m.content, timestamp: m.timestamp };
    });
  }
}

const SPAWN_TOOL: ToolDefinition = { name: "spawn_teammate", description: "Create a named teammate with a role.",
  input_schema: { type: "object", properties: { name: { type: "string" }, role: { type: "string" } }, required: ["name", "role"] } };
const LIST_TOOL: ToolDefinition = { name: "list_teammates", description: "Show team roster.",
  input_schema: { type: "object", properties: {} } };
const SEND_TOOL: ToolDefinition = { name: "send_message", description: "Send a message to a teammate's inbox.",
  input_schema: { type: "object", properties: {
    to: { type: "string" }, content: { type: "string" },
    type: { type: "string", enum: ["message", "shutdown_request", "shutdown_response", "plan_approval_response"] },
  }, required: ["to", "content"] } };
const READ_TOOL: ToolDefinition = { name: "read_inbox", description: "Read and drain all messages from a teammate's inbox.",
  input_schema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] } };
const BCAST_TOOL: ToolDefinition = { name: "broadcast", description: "Send the same message to all teammates.",
  input_schema: { type: "object", properties: { content: { type: "string" } }, required: ["content"] } };

export class TeamMessagingAgent extends BaseAgent {
  protected roster: TeammateManager;
  protected inbox: MessageBus;

  constructor(config: AgentConfig) {
    super(config);
    this.roster = new TeammateManager(this.toolExecutor.fs);
    this.inbox = new MessageBus(this.toolExecutor.fs);

    this.toolExecutor.registerTool("spawn_teammate", (i) =>
      this.roster.spawn(i.name as string, i.role as string));
    this.toolExecutor.registerTool("list_teammates", () => {
      const r = this.roster.list();
      return r.length === 0 ? "No teammates." : r.map((t) => `- ${t.name} [${t.status}]`).join("\n");
    });
    this.toolExecutor.registerTool("send_message", (i) =>
      this.inbox.send("lead", i.to as string, i.content as string, (i.type as MsgType) ?? "message"));
    this.toolExecutor.registerTool("read_inbox", (i) => {
      const msgs = this.inbox.read(i.name as string);
      return msgs.length === 0 ? "Inbox empty." : JSON.stringify(msgs, null, 2);
    });
    this.toolExecutor.registerTool("broadcast", (i) => {
      const names = Array.from(this.roster.teammates.keys());
      return this.inbox.broadcast("lead", names, i.content as string);
    });
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
      SPAWN_TOOL, LIST_TOOL, SEND_TOOL, READ_TOOL, BCAST_TOOL];
  }

  getSystemPrompt(): string {
    return [
      "You are a Team Lead with messaging capabilities.",
      "- spawn_teammate / list_teammates: manage the roster",
      "- send_message: point-to-point DM to a teammate",
      "- broadcast: send to all teammates at once",
      "- read_inbox: drain a teammate's incoming messages",
    ].join("\n");
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      teammates: this.roster.list(),
      inbox: [],
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
