import {
  BaseAgent,
  BASH_TOOL,
  READ_FILE_TOOL,
  WRITE_FILE_TOOL,
  EDIT_FILE_TOOL,
  createMessage,
  type AgentConfig,
  type AgentState,
  type ToolDefinition,
  type ContentBlock,
  type ToolResultBlock,
} from "./shared";

interface Teammate {
  name: string;
  role: string;
  status: "idle" | "working" | "shutdown";
}

interface BoardTask {
  id: string;
  subject: string;
  status: "pending" | "in_progress" | "completed";
  owner: string;
  blockedBy: string[];
}

interface Handoff {
  agent_id: string;
  task_id: string;
  status: "Success" | "PartialFailure" | "Failed" | "Blocked";
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

interface RuntimeState {
  taskId: string;
  startTime: number;
  attempts: number;
  tokensUsed: number;
  diff: Record<string, { before: string; after: string }>;
  artifacts: string[];
  submitted: boolean;
  turns: number;
  summaryCount: number;
  lastReflectionTurn: number;
  lastScratchpadRewriteTurn: number;
}

const CONTEXT_CAPACITY_MESSAGES = 50;
const CONTEXT_THRESHOLD = Math.floor(CONTEXT_CAPACITY_MESSAGES * 0.8);
const SELF_REFLECTION_EVERY = 10;
const SCRATCHPAD_REWRITE_EVERY = 6;

export class ScratchpadRewritingAgent extends BaseAgent {
  private teammates: Map<string, Teammate> = new Map();
  private tasks: BoardTask[] = [];
  private taskSeq = 0;
  private handoffs: Handoff[] = [];
  private runtime: RuntimeState;
  private agentName: string;
  private leadName: string;

  constructor(config: AgentConfig & { agentName?: string; leadName?: string }) {
    super(config);
    this.agentName = config.agentName ?? "worker-1";
    this.leadName = config.leadName ?? "lead";
    this.runtime = this.newRuntime();
    this.registerAll();
    this.rewriteScratchpad(
      `# Scratchpad for ${this.agentName}\n\n- role: worker\n- status: initialized\n- next: wait for task\n`
    );
  }

  private newRuntime(taskId = "none"): RuntimeState {
    return {
      taskId,
      startTime: Date.now(),
      attempts: 0,
      tokensUsed: 0,
      diff: {},
      artifacts: [],
      submitted: false,
      turns: 0,
      summaryCount: 0,
      lastReflectionTurn: 0,
      lastScratchpadRewriteTurn: 0,
    };
  }

  private scratchpadPath(name = this.agentName): string {
    return `.scratchpad/${name}.md`;
  }

  private readScratchpad(name = this.agentName): string {
    return this.toolExecutor.fs.getFile(this.scratchpadPath(name)) ?? "";
  }

  private rewriteScratchpad(content: string, name = this.agentName): string {
    const out = this.toolExecutor.fs.writeFile(this.scratchpadPath(name), content);
    return out;
  }

  private inboxPath(name: string): string {
    return `.team/inbox/${name}.jsonl`;
  }

  private appendInbox(to: string, msg: Record<string, unknown>): void {
    const p = this.inboxPath(to);
    const prev = this.toolExecutor.fs.getFile(p) ?? "";
    this.toolExecutor.fs.writeFile(p, prev + JSON.stringify(msg) + "\n");
  }

  private trackDiff(path: string, before: string, after: string): void {
    if (this.runtime.diff[path]) {
      this.runtime.diff[path] = { before: this.runtime.diff[path].before, after };
    } else {
      this.runtime.diff[path] = { before, after };
    }
  }

  private trackedWrite(path: string, content: string): string {
    const before = this.toolExecutor.fs.getFile(path) ?? "";
    const out = this.toolExecutor.fs.writeFile(path, content);
    const after = this.toolExecutor.fs.getFile(path) ?? "";
    this.trackDiff(path, before, after);
    this.runtime.artifacts.push(path);
    return out;
  }

  private trackedEdit(path: string, oldText: string, newText: string): string {
    const before = this.toolExecutor.fs.getFile(path);
    const out = this.toolExecutor.fs.editFile(path, oldText, newText);
    const after = this.toolExecutor.fs.getFile(path);
    if (before !== undefined && after !== undefined && !out.startsWith("Error:")) {
      this.trackDiff(path, before, after);
      this.runtime.artifacts.push(path);
    }
    return out;
  }

  private registerAll(): void {
    this.toolExecutor.registerTool("spawn_teammate", (i) => {
      const name = String(i.name);
      if (this.teammates.has(name)) return `Error: '${name}' exists`;
      this.teammates.set(name, { name, role: String(i.role), status: "idle" });
      this.rewriteScratchpad(`# Scratchpad for ${name}\n\n- role: ${String(i.role)}\n- status: spawned\n`, name);
      return JSON.stringify({ name, status: "idle" });
    });

    this.toolExecutor.registerTool("list_teammates", () => {
      if (this.teammates.size === 0) return "No teammates.";
      return Array.from(this.teammates.values())
        .map((t) => `- ${t.name} [${t.status}]`)
        .join("\n");
    });

    this.toolExecutor.registerTool("send_message", (i) => {
      this.appendInbox(String(i.to), {
        type: "message",
        from: this.agentName,
        to: String(i.to),
        content: String(i.content ?? ""),
        timestamp: Date.now(),
      });
      return `Message sent to ${String(i.to)}`;
    });

    this.toolExecutor.registerTool("read_inbox", (i) => {
      const p = this.inboxPath(String(i.name));
      const raw = this.toolExecutor.fs.getFile(p);
      if (!raw || !raw.trim()) return "Inbox empty.";
      this.toolExecutor.fs.writeFile(p, "");
      return raw.trim();
    });

    this.toolExecutor.registerTool("broadcast", (i) => {
      let count = 0;
      for (const n of Array.from(this.teammates.keys())) {
        if (n !== this.agentName) {
          this.appendInbox(n, {
            type: "broadcast",
            from: this.agentName,
            to: n,
            content: String(i.content ?? ""),
            timestamp: Date.now(),
          });
          count++;
        }
      }
      return `Broadcast sent to ${count} teammates`;
    });

    this.toolExecutor.registerTool("create_task", (i) => {
      const t: BoardTask = {
        id: String(++this.taskSeq),
        subject: String(i.subject),
        status: "pending",
        owner: "",
        blockedBy: [],
      };
      this.tasks.push(t);
      return JSON.stringify({ id: t.id, subject: t.subject, status: t.status });
    });

    this.toolExecutor.registerTool("list_tasks", () => {
      if (this.tasks.length === 0) return "No tasks.";
      return this.tasks
        .map((t) => `#${t.id} ${t.status} ${t.subject}${t.owner ? ` @${t.owner}` : ""}`)
        .join("\n");
    });

    this.toolExecutor.registerTool("claim_task", (i) => {
      const id = String(i.task_id);
      const task = this.tasks.find((t) => t.id === id);
      if (!task) return `Error: Task #${id} not found`;
      if (task.status !== "pending" || task.owner || task.blockedBy.length > 0) {
        return `Error: Task #${id} unavailable`;
      }
      task.status = "in_progress";
      task.owner = this.agentName;
      this.runtime = this.newRuntime(task.id);
      return JSON.stringify({ id: task.id, status: task.status, owner: task.owner });
    });

    this.toolExecutor.registerTool("write_file", (i) =>
      this.trackedWrite(String(i.path ?? i.file_path), String(i.content ?? ""))
    );

    this.toolExecutor.registerTool("edit_file", (i) =>
      this.trackedEdit(
        String(i.path ?? i.file_path),
        String(i.old_text ?? i.old_string ?? ""),
        String(i.new_text ?? i.new_string ?? "")
      )
    );

    this.toolExecutor.registerTool("read_scratchpad", (i) => {
      const who = i.agent_name ? String(i.agent_name) : this.agentName;
      const content = this.readScratchpad(who);
      return content || "(scratchpad empty)";
    });

    this.toolExecutor.registerTool("rewrite_scratchpad", (i) => {
      const who = i.agent_name ? String(i.agent_name) : this.agentName;
      const content = String(i.content ?? "");
      return this.rewriteScratchpad(content, who);
    });
  }

  private maybeInjectReflection(): void {
    const turns = this.runtime.turns;
    if (turns <= 0 || turns % SELF_REFLECTION_EVERY !== 0) return;
    if (this.runtime.lastReflectionTurn === turns) return;

    this.messages.push({
      role: "user",
      content: "<self_reflection>Are you making progress or going in circles?</self_reflection>",
    });
    this.messages.push({
      role: "assistant",
      content: "I will reassess and pivot if current strategy is not converging.",
    });
    this.runtime.lastReflectionTurn = turns;
  }

  private buildScratchpad(reason: "periodic" | "summary"): string {
    const touched = Object.keys(this.runtime.diff);
    return [
      `# Scratchpad for ${this.agentName}`,
      "",
      "## Current Goal",
      `Task ${this.runtime.taskId}`,
      "",
      "## Progress",
      `- attempts: ${this.runtime.attempts}`,
      `- turns: ${this.runtime.turns}`,
      `- files touched: ${touched.length > 0 ? touched.join(", ") : "none"}`,
      `- summary_count: ${this.runtime.summaryCount}`,
      "",
      "## Risks",
      touched.length === 0 ? "- no code changes yet" : "- ensure touched files still match intent",
      "",
      "## Next Action",
      reason === "summary"
        ? "- Continue from compressed summary and verify role alignment"
        : "- Continue execution and submit handoff when done",
      "",
      "## Constraint",
      "- Scratchpad is rewritten in full; old state is replaced.",
    ].join("\n");
  }

  private maybeRewriteScratchpad(): void {
    const turns = this.runtime.turns;
    if (turns <= 0 || turns % SCRATCHPAD_REWRITE_EVERY !== 0) return;
    if (this.runtime.lastScratchpadRewriteTurn === turns) return;
    this.rewriteScratchpad(this.buildScratchpad("periodic"));
    this.runtime.lastScratchpadRewriteTurn = turns;
  }

  private async summarizeAndReset(): Promise<void> {
    const serialized = JSON.stringify(this.messages).slice(0, 60000);
    const response = await createMessage({
      apiKey: this.config.apiKey,
      model: this.config.model,
      system:
        "Compress conversation for continuity. Include completed work, active task, risks, and next action.",
      messages: [{ role: "user", content: serialized }],
      tools: [],
    });

    this.totalInputTokens += response.usage.input_tokens;
    this.totalOutputTokens += response.usage.output_tokens;
    this.runtime.tokensUsed += response.usage.input_tokens + response.usage.output_tokens;
    this.runtime.summaryCount += 1;

    const summary = response.content
      .filter((b): b is { type: "text"; text: string } => b.type === "text")
      .map((b) => b.text)
      .join("\n")
      .trim();

    this.messages = [
      {
        role: "user",
        content: `<identity>You are '${this.agentName}', role: worker. Continue your assigned task.</identity>`,
      },
      { role: "assistant", content: "Identity restored after summarization." },
      {
        role: "user",
        content:
          "<alignment>Role reminder: execute assigned work, maintain scratchpad freshness, and avoid drift.</alignment>",
      },
      { role: "user", content: `<summary>${summary}</summary>` },
    ];

    this.rewriteScratchpad(this.buildScratchpad("summary"));
    this.runtime.lastScratchpadRewriteTurn = this.runtime.turns;
  }

  private inferStatus(): Handoff["status"] {
    const files = Object.keys(this.runtime.diff).length;
    if (files > 0) return "Success";
    return this.runtime.attempts > 0 ? "PartialFailure" : "Blocked";
  }

  private async composeNarrative(status: Handoff["status"]): Promise<string> {
    const payload = {
      agent_id: this.agentName,
      task_id: this.runtime.taskId,
      status,
      files: Object.keys(this.runtime.diff),
      artifacts: this.runtime.artifacts,
      attempts: this.runtime.attempts,
      scratchpad: this.readScratchpad(),
    };

    const response = await createMessage({
      apiKey: this.config.apiKey,
      model: this.config.model,
      system:
        "Write concise handoff narrative using scratchpad context. Include changed files, risks, and next action.",
      messages: [{ role: "user", content: JSON.stringify(payload) }],
      tools: [],
    });

    this.totalInputTokens += response.usage.input_tokens;
    this.totalOutputTokens += response.usage.output_tokens;
    this.runtime.tokensUsed += response.usage.input_tokens + response.usage.output_tokens;

    const narrative = response.content
      .filter((b): b is { type: "text"; text: string } => b.type === "text")
      .map((b) => b.text)
      .join("\n")
      .trim();

    return narrative || `Task ${this.runtime.taskId} completed with status ${status}.`;
  }

  private async submitHandoff(input: Record<string, unknown>): Promise<string> {
    if (this.runtime.submitted) {
      return `Handoff already submitted for task ${this.runtime.taskId}`;
    }

    const status =
      (input.status as Handoff["status"] | undefined) ?? this.inferStatus();
    const narrative =
      typeof input.narrative === "string" && input.narrative.trim().length > 0
        ? input.narrative
        : await this.composeNarrative(status);

    const extraArtifacts = Array.isArray(input.artifacts)
      ? input.artifacts.filter((a): a is string => typeof a === "string")
      : [];
    const artifacts = Array.from(new Set([...this.runtime.artifacts, ...extraArtifacts]));

    const handoff: Handoff = {
      agent_id: this.agentName,
      task_id: String(input.task_id ?? this.runtime.taskId),
      status,
      diff: { ...this.runtime.diff },
      narrative,
      artifacts,
      metrics: {
        wall_time: (Date.now() - this.runtime.startTime) / 1000,
        tokens_used: this.runtime.tokensUsed,
        attempts: this.runtime.attempts,
        files_modified: Object.keys(this.runtime.diff).length,
      },
    };

    this.handoffs.push(handoff);
    this.runtime.submitted = true;

    this.appendInbox(this.leadName, {
      type: "handoff",
      from: this.agentName,
      to: this.leadName,
      content: handoff.narrative,
      handoff,
      timestamp: Date.now(),
    });

    return `Submitted handoff for task ${handoff.task_id} (${handoff.status})`;
  }

  protected override async processToolCalls(
    content: ContentBlock[]
  ): Promise<ToolResultBlock[]> {
    const results: ToolResultBlock[] = [];

    for (const block of content) {
      if (block.type !== "tool_use") continue;
      this.emit("tool_call", { name: block.name, input: block.input });

      let result: ToolResultBlock;
      if (block.name === "submit_handoff") {
        try {
          const output = await this.submitHandoff(block.input);
          result = { type: "tool_result", tool_use_id: block.id, content: output };
        } catch (err) {
          result = {
            type: "tool_result",
            tool_use_id: block.id,
            content: `Error: ${err instanceof Error ? err.message : String(err)}`,
            is_error: true,
          };
        }
      } else {
        result = this.executeTool(block);
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
    this.messages.push({
      role: "user",
      content: `<scratchpad>${this.readScratchpad() || "(empty scratchpad)"}</scratchpad>`,
    });
    this.emit("state_change");

    let finalText = "";

    while (this.loopIteration < (this.config.maxIterations || 10)) {
      if (this.aborted) break;
      this.loopIteration += 1;

      this.maybeInjectReflection();
      this.maybeRewriteScratchpad();

      if (this.messages.length > CONTEXT_THRESHOLD) {
        await this.summarizeAndReset();
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
      this.runtime.tokensUsed += response.usage.input_tokens + response.usage.output_tokens;
      this.runtime.attempts += 1;
      this.runtime.turns += 1;
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

    if (!this.runtime.submitted) {
      await this.submitHandoff({ status: this.inferStatus() });
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }

  getTools(): ToolDefinition[] {
    return [
      BASH_TOOL,
      READ_FILE_TOOL,
      WRITE_FILE_TOOL,
      EDIT_FILE_TOOL,
      {
        name: "spawn_teammate",
        description: "Create a named teammate.",
        input_schema: {
          type: "object",
          properties: { name: { type: "string" }, role: { type: "string" } },
          required: ["name", "role"],
        },
      },
      {
        name: "list_teammates",
        description: "Show team roster.",
        input_schema: { type: "object", properties: {} },
      },
      {
        name: "send_message",
        description: "Send a message to a teammate.",
        input_schema: {
          type: "object",
          properties: { to: { type: "string" }, content: { type: "string" } },
          required: ["to", "content"],
        },
      },
      {
        name: "read_inbox",
        description: "Read a teammate inbox.",
        input_schema: {
          type: "object",
          properties: { name: { type: "string" } },
          required: ["name"],
        },
      },
      {
        name: "broadcast",
        description: "Broadcast to all teammates.",
        input_schema: {
          type: "object",
          properties: { content: { type: "string" } },
          required: ["content"],
        },
      },
      {
        name: "create_task",
        description: "Create a task on shared board.",
        input_schema: {
          type: "object",
          properties: { subject: { type: "string" } },
          required: ["subject"],
        },
      },
      {
        name: "list_tasks",
        description: "List board tasks.",
        input_schema: { type: "object", properties: {} },
      },
      {
        name: "claim_task",
        description: "Claim pending task.",
        input_schema: {
          type: "object",
          properties: { task_id: { type: "string" } },
          required: ["task_id"],
        },
      },
      {
        name: "submit_handoff",
        description: "Submit structured handoff to lead.",
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
        name: "read_scratchpad",
        description: "Read file-based scratchpad.",
        input_schema: {
          type: "object",
          properties: { agent_name: { type: "string" } },
        },
      },
      {
        name: "rewrite_scratchpad",
        description: "Rewrite scratchpad by full replacement.",
        input_schema: {
          type: "object",
          properties: {
            agent_name: { type: "string" },
            content: { type: "string" },
          },
          required: ["content"],
        },
      },
    ];
  }

  getSystemPrompt(): string {
    return [
      "You are a scratchpad-rewriting worker harness demo.",
      "Maintain scratchpad freshness by rewriting, not appending.",
      "At high context usage, summarize and continue with role alignment.",
      "Use submit_handoff when done.",
    ].join("\n");
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      teammates: Array.from(this.teammates.values()).map((t) => ({
        name: t.name,
        status: t.status,
        currentTask: t.role,
      })),
      tasks: this.tasks.map((t) => ({
        id: t.id,
        subject: t.subject,
        status: t.status,
        blockedBy: t.blockedBy,
      })),
      handoffs: this.handoffs,
      scratchpads: {
        [this.agentName]: this.readScratchpad(this.agentName),
      },
      runtime: {
        turns: this.runtime.turns,
        summaryCount: this.runtime.summaryCount,
      },
    } as AgentState;
  }
}
