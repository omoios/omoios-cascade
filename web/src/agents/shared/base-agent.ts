/**
 * BaseAgent: utility infrastructure for all session agents.
 *
 * Provides helpers that every agent uses:
 *   - Event emission (onEvent callbacks)
 *   - API client wrapper (createMessage)
 *   - Tool execution (ToolExecutor)
 *   - State tracking (messages, tokens, iterations)
 *   - Abort / reset lifecycle
 *
 * The run() method is a DEFAULT implementation. Each sXX.ts
 * session agent OVERRIDES run() with its own explicit while loop
 * to show the mechanism being taught in that session.
 *
 *   BaseAgent provides:
 *   +------------------------------------------+
 *   | emit()          - fire events to UI       |
 *   | getState()      - snapshot for inspector  |
 *   | extractText()   - parse text from blocks  |
 *   | processToolCalls() - dispatch tools       |
 *   | abort() / reset()  - lifecycle control    |
 *   +------------------------------------------+
 *
 *   Each sXX.ts provides:
 *   +------------------------------------------+
 *   | run()           - explicit while loop     |
 *   | getTools()      - tools for this session  |
 *   | getSystemPrompt() - prompt for session    |
 *   +------------------------------------------+
 */

import type {
  Message,
  ContentBlock,
  ToolUseBlock,
  ToolResultBlock,
  ToolDefinition,
  APIResponse,
  AgentState,
  AgentEvent,
  AgentEventHandler,
  AgentConfig,
} from "./types";
import { createMessage } from "./api-client";
import { ToolExecutor } from "./tool-executor";

export abstract class BaseAgent {
  protected messages: Message[] = [];
  protected config: AgentConfig;
  protected toolExecutor: ToolExecutor;
  protected loopIteration = 0;
  protected totalInputTokens = 0;
  protected totalOutputTokens = 0;
  protected aborted = false;

  constructor(config: AgentConfig, toolExecutor?: ToolExecutor) {
    this.config = {
      model: "claude-sonnet-4-20250514",
      maxIterations: 10,
      ...config,
    };
    this.toolExecutor = toolExecutor || new ToolExecutor();
  }

  /** Each version defines its available tools. */
  abstract getTools(): ToolDefinition[];

  /** Each version defines its system prompt. */
  abstract getSystemPrompt(): string;

  /** Build the current observable state for the inspector. */
  getState(): AgentState {
    return {
      messages: [...this.messages],
      tools: this.getTools().map((t) => t.name),
      loopIteration: this.loopIteration,
      stopReason: null,
      totalInputTokens: this.totalInputTokens,
      totalOutputTokens: this.totalOutputTokens,
    };
  }

  /** Emit an event to the subscriber. */
  protected emit(type: AgentEvent["type"], data?: unknown): void {
    this.config.onEvent?.({
      type,
      timestamp: Date.now(),
      data: data ?? this.getState(),
    });
  }

  /** Abort a running agent loop. */
  abort(): void {
    this.aborted = true;
  }

  /** Reset agent state for a new conversation. */
  reset(): void {
    this.messages = [];
    this.loopIteration = 0;
    this.totalInputTokens = 0;
    this.totalOutputTokens = 0;
    this.aborted = false;
    this.emit("state_change");
  }

  /**
   * Default agent loop. Each sXX.ts session OVERRIDES this with an
   * explicit while loop that shows the session's mechanism inline.
   * This default is kept for backwards compatibility and testing.
   */
  async run(userMessage: string): Promise<string> {
    this.aborted = false;
    this.messages.push({ role: "user", content: userMessage });
    this.emit("state_change");

    let finalText = "";

    while (this.loopIteration < (this.config.maxIterations || 10)) {
      if (this.aborted) break;

      this.loopIteration++;

      // Pre-request hook (for compression, skill loading, etc.)
      await this.beforeLLMCall();

      this.emit("llm_request", {
        messages: this.messages.length,
        tools: this.getTools().length,
        iteration: this.loopIteration,
      });

      const response = await createMessage({
        apiKey: this.config.apiKey,
        model: this.config.model,
        system: this.getSystemPrompt(),
        messages: this.messages,
        tools: this.getTools(),
      });

      this.totalInputTokens += response.usage.input_tokens;
      this.totalOutputTokens += response.usage.output_tokens;

      this.emit("llm_response", {
        stopReason: response.stop_reason,
        contentBlocks: response.content.length,
        usage: response.usage,
      });

      // Add assistant message
      this.messages.push({ role: "assistant", content: response.content });
      this.emit("state_change");

      // If no tool use, we're done
      if (response.stop_reason !== "tool_use") {
        finalText = this.extractText(response.content);
        break;
      }

      // Process tool calls
      const toolResults = await this.processToolCalls(response.content);
      this.messages.push({ role: "user", content: toolResults });
      this.emit("state_change");

      // Post-tool hook (for state updates, etc.)
      await this.afterToolExecution(toolResults);
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }

  /**
   * Process all tool_use blocks in a response.
   * Can be overridden for custom tool handling (e.g., subagent spawning).
   */
  protected async processToolCalls(content: ContentBlock[]): Promise<ToolResultBlock[]> {
    const results: ToolResultBlock[] = [];

    for (const block of content) {
      if (block.type === "tool_use") {
        this.emit("tool_call", { name: block.name, input: block.input });

        const result = this.executeTool(block);
        results.push(result);

        this.emit("tool_result", {
          tool_use_id: block.id,
          name: block.name,
          content: result.content,
          is_error: result.is_error,
        });
      }
    }

    return results;
  }

  /**
   * Execute a single tool. Override to add custom tools.
   */
  protected executeTool(block: ToolUseBlock): ToolResultBlock {
    return this.toolExecutor.execute(block);
  }

  /** Hook: called before each LLM request. */
  protected async beforeLLMCall(): Promise<void> {
    // Override in subclasses (e.g., s06 compression)
  }

  /** Hook: called after tool execution in each iteration. */
  protected async afterToolExecution(_results: ToolResultBlock[]): Promise<void> {
    // Override in subclasses (e.g., s03 todo updates)
  }

  /** Extract plain text from content blocks. */
  protected extractText(content: ContentBlock[]): string {
    return content
      .filter((b): b is { type: "text"; text: string } => b.type === "text")
      .map((b) => b.text)
      .join("");
  }
}
