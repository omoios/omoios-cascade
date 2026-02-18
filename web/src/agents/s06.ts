/**
 * s06 - Context Compression
 *
 * Three-layer compression pipeline runs before each LLM call.
 * The agent can forget strategically and keep working forever.
 *
 *   beforeLLMCall():
 *   +-----------------------------------------------+
 *   | Layer 1: Micro-compact (silent, every turn)   |
 *   |   Replace old tool results with placeholders  |
 *   |   Keep last 3 results intact                  |
 *   |   Skip if savings < threshold                 |
 *   +--------------------|--------------------------+
 *                        v
 *   +-----------------------------------------------+
 *   | Layer 2: Auto-compact (when tokens > 40000)   |
 *   |   Summarize entire history                    |
 *   |   Replace all messages with [summary, ack]    |
 *   +--------------------|--------------------------+
 *                        v
 *   +-----------------------------------------------+
 *   | Layer 3: Manual compact (user calls compress) |
 *   |   Force auto-compact via tool call            |
 *   +-----------------------------------------------+
 *
 * Mechanism: 3-layer compression pipeline
 * Tools: bash, read_file, write_file, edit_file, compress (5 total)
 * LOC target: 180
 */

import {
  BaseAgent, ToolExecutor,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type ToolUseBlock, type ToolResultBlock,
  type ContentBlock, type AgentConfig, type AgentState,
  type CompressionInfo, type Message,
} from "./shared";

const COMPACTABLE = new Set(["bash", "read_file", "write_file", "edit_file"]);
const KEEP_RECENT = 3;
const MIN_SAVINGS = 5000;
const AUTO_THRESHOLD = 50000;

function estimateTokens(text: string): number { return Math.ceil(text.length / 4); }

function msgStr(msg: Message): string {
  return typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content);
}

function totalTokens(msgs: Message[]): number {
  return msgs.reduce((s, m) => s + estimateTokens(msgStr(m)), 0);
}

const COMPRESS_TOOL: ToolDefinition = {
  name: "compress",
  description: "Force context compression. Use when the conversation is getting long.",
  input_schema: { type: "object", properties: {}, required: [] },
};

export class CompressionAgent extends BaseAgent {
  private compressionCount = 0;
  private layers: CompressionInfo["layers"] = [];

  constructor(config: AgentConfig, toolExecutor?: ToolExecutor) {
    super(config, toolExecutor);
    this.toolExecutor.registerTool("compress", () => {
      this.autoCompact();
      return "Context compressed.";
    });
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, COMPRESS_TOOL];
  }

  getSystemPrompt(): string {
    return "You are a coding agent with context compression. " +
      "Use tools to accomplish tasks. Use compress if the conversation grows long. " +
      "Loop: think -> act with tools -> report results.";
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      compression: {
        totalTokens: totalTokens(this.messages),
        threshold: AUTO_THRESHOLD,
        compressionCount: this.compressionCount,
        layers: this.layers.length > 0 ? this.layers : [
          { name: "micro-compact", triggered: false },
          { name: "auto-compact", triggered: false },
          { name: "manual-compact", triggered: false },
        ],
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

      // -- COMPRESSION PIPELINE: runs before each LLM call --
      this.layers = [];
      const before = totalTokens(this.messages);
      this.microCompact();
      const afterMicro = totalTokens(this.messages);
      this.layers.push({
        name: "micro-compact", triggered: afterMicro < before,
        tokensBefore: before, tokensAfter: afterMicro,
      });
      if (afterMicro > AUTO_THRESHOLD) {
        this.autoCompact();
        this.layers.push({
          name: "auto-compact", triggered: true,
          tokensBefore: afterMicro, tokensAfter: totalTokens(this.messages),
        });
      } else {
        this.layers.push({ name: "auto-compact", triggered: false });
      }
      this.layers.push({ name: "manual-compact", triggered: false });
      this.emit("state_change");

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

  /** Layer 1: Replace old large tool results with compact placeholders. */
  private microCompact(): void {
    type Entry = { msgIdx: number; blockIdx: number; toolName: string };
    const indices: Entry[] = [];
    for (let i = 0; i < this.messages.length; i++) {
      const msg = this.messages[i];
      if (msg.role !== "user" || typeof msg.content === "string") continue;
      const blocks = msg.content as ToolResultBlock[];
      for (let j = 0; j < blocks.length; j++) {
        if (blocks[j].type !== "tool_result") continue;
        const name = this.findToolName(blocks[j].tool_use_id);
        if (COMPACTABLE.has(name)) indices.push({ msgIdx: i, blockIdx: j, toolName: name });
      }
    }
    const toCompact = indices.length > KEEP_RECENT ? indices.slice(0, -KEEP_RECENT) : [];
    let savings = 0;
    const clearable: Entry[] = [];
    for (const e of toCompact) {
      const t = estimateTokens((this.messages[e.msgIdx].content as ToolResultBlock[])[e.blockIdx].content);
      if (t > 200) { savings += t; clearable.push(e); }
    }
    if (savings >= MIN_SAVINGS) {
      for (const e of clearable) {
        const blocks = this.messages[e.msgIdx].content as ToolResultBlock[];
        blocks[e.blockIdx] = { ...blocks[e.blockIdx], content: `[Previous: used ${e.toolName}]` };
      }
    }
  }

  /** Layer 2: Summarize conversation and replace all messages. */
  private autoCompact(): void {
    this.compressionCount++;
    const lines: string[] = [];
    for (const msg of this.messages) {
      if (typeof msg.content === "string") {
        lines.push(`[${msg.role}] ${msg.content.slice(0, 300)}`);
      } else {
        for (const block of msg.content) {
          if (block.type === "text" && "text" in block) {
            lines.push(`[${msg.role}] ${(block as { type: "text"; text: string }).text.slice(0, 300)}`);
          } else if (block.type === "tool_use") {
            lines.push(`[tool_use] ${(block as ToolUseBlock).name}`);
          } else if (block.type === "tool_result") {
            lines.push(`[result] ${(block as ToolResultBlock).content.slice(0, 100)}`);
          }
        }
      }
    }
    const summary = lines.join("\n").slice(0, 4000);
    this.messages = [
      { role: "user", content: `[Conversation compressed]\n\n${summary}` },
      { role: "assistant", content: "Understood. Continuing with compressed context." },
    ];
  }

  private findToolName(toolUseId: string): string {
    for (const msg of this.messages) {
      if (msg.role !== "assistant" || typeof msg.content === "string") continue;
      for (const block of msg.content as ContentBlock[]) {
        if (block.type === "tool_use" && block.id === toolUseId) return block.name;
      }
    }
    return "";
  }
}
