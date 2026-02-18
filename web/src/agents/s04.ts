/**
 * s04 - Context Isolation (Subagent)
 *
 * Spawns a child agent with fresh messages[] but shared VirtualFS.
 * Only the child's final text returns to the parent -- context stays clean.
 *
 *   Parent Agent (main loop)
 *   +----------------------------+
 *   | tool_use: task             |
 *   |   |                        |
 *   |   v                        |
 *   | spawnSubagent(prompt)      |
 *   |   +-- Child Agent ------+  |
 *   |   | messages = []       |  |  <-- fresh context
 *   |   | same VirtualFS      |  |  <-- shared files
 *   |   | while (tool_use)    |  |
 *   |   |   execute tools     |  |
 *   |   | return summary text |  |
 *   |   +--------------------+  |
 *   |   |                        |
 *   |   v                        |
 *   | tool_result: summary only  |
 *   +----------------------------+
 *
 * Mechanism: Subagent with fresh context, summary-only return
 * Tools: bash, read_file, write_file, edit_file, task (5 total)
 * LOC target: 130
 */

import {
  BaseAgent, ToolExecutor,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type ContentBlock, type ToolUseBlock,
  type ToolResultBlock, type AgentConfig, type AgentState, type Message,
} from "./shared";

const TASK_TOOL: ToolDefinition = {
  name: "task",
  description: "Spawn a subagent for a focused subtask with isolated context. Returns only its final summary.",
  input_schema: {
    type: "object",
    properties: {
      description: { type: "string", description: "Short task name (3-5 words)" },
      prompt: { type: "string", description: "Detailed instructions for the subagent" },
    },
    required: ["description", "prompt"],
  },
};

export class SubagentAgent extends BaseAgent {
  private subagentRecords: { name: string; messageCount: number }[] = [];

  constructor(config: AgentConfig) {
    super(config);
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, TASK_TOOL];
  }

  getSystemPrompt(): string {
    return [
      "You are a coding agent that can spawn focused subagents.",
      "Use the task tool for subtasks needing isolated exploration.",
      "Subagents return a summary. Keep the main context clean.",
    ].join("\n");
  }

  getState(): AgentState {
    return { ...super.getState(), subagentContexts: [...this.subagentRecords] };
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

      // -- INTERCEPT "task" tool for subagent spawn --
      const results: ToolResultBlock[] = [];
      for (const block of response.content) {
        if (block.type !== "tool_use") continue;
        this.emit("tool_call", { name: block.name, input: block.input });
        const result = block.name === "task"
          ? await this.spawnSubagent(block)
          : this.toolExecutor.execute(block);
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: result.content });
      }

      this.messages.push({ role: "user", content: results });
      this.emit("state_change");
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }

  /** Spawn a child with fresh messages but shared VirtualFS. */
  private async spawnSubagent(block: ToolUseBlock): Promise<ToolResultBlock> {
    const input = block.input as { description?: string; prompt?: string };
    const prompt = input.prompt ?? "";
    if (!prompt) {
      return { type: "tool_result", tool_use_id: block.id, content: "Error: prompt required", is_error: true };
    }

    try {
      const childExec = new ToolExecutor(this.toolExecutor.fs);
      const childMessages: Message[] = [{ role: "user", content: prompt }];
      let childText = "";

      // Child runs its own mini-loop with shared FS
      for (let i = 0; i < 5; i++) {
        const resp = await createMessage({
          apiKey: this.config.apiKey, model: this.config.model,
          system: "You are a focused subagent. Complete the task and summarize.",
          messages: childMessages, tools: [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL],
        });
        childMessages.push({ role: "assistant", content: resp.content });
        if (resp.stop_reason !== "tool_use") { childText = this.extractText(resp.content); break; }
        const childResults: ToolResultBlock[] = [];
        for (const b of resp.content) {
          if (b.type === "tool_use") childResults.push(childExec.execute(b));
        }
        childMessages.push({ role: "user", content: childResults });
      }

      this.subagentRecords.push({ name: input.description ?? "subtask", messageCount: childMessages.length });
      this.emit("state_change");
      return { type: "tool_result", tool_use_id: block.id, content: childText || "(no output)" };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { type: "tool_result", tool_use_id: block.id, content: `Subagent error: ${msg}`, is_error: true };
    }
  }
}
