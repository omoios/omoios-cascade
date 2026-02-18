/**
 * s01 - The Agent Loop
 *
 * The entire agent is a while loop. That is the core insight.
 *
 *   User message
 *       |
 *       v
 *   +-----------------------------+
 *   | while (not done)            |
 *   |   response = LLM([bash])   |
 *   |   if stop_reason==tool_use: |
 *   |     execute bash command    |
 *   |     append result           |
 *   |   else:                     |
 *   |     return text response    |
 *   +-----------------------------+
 *
 * Mechanism: while stop_reason == "tool_use" loop
 * Tools: bash (1 total)
 * LOC target: 70
 */

import {
  BaseAgent, BASH_TOOL,
  createMessage, type ToolDefinition, type AgentConfig,
} from "./shared";

export class AgentLoopAgent extends BaseAgent {
  constructor(config: AgentConfig) {
    super(config);
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL];
  }

  getSystemPrompt(): string {
    return [
      "You are a CLI agent. Solve problems using bash commands.",
      "Prefer tools over prose. Act first, explain briefly after.",
    ].join("\n");
  }

  async run(userMessage: string): Promise<string> {
    this.aborted = false;
    this.messages.push({ role: "user", content: userMessage });
    this.emit("state_change");

    let finalText = "";

    // -- THE LOOP: this is the entire agent --
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
