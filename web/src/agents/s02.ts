/**
 * s02 - Multi-Tool Dispatch
 *
 * The loop stays the same. Only the tool array changes.
 * A dispatch map routes tool_use blocks to the right handler.
 *
 *   Tool dispatch map:
 *   +-------------------------------------------+
 *   | "bash"       -> ToolExecutor.fs.bash()    |
 *   | "read_file"  -> ToolExecutor.fs.readFile()|
 *   | "write_file" -> ToolExecutor.fs.writeFile()|
 *   | "edit_file"  -> ToolExecutor.fs.editFile()|
 *   +-------------------------------------------+
 *         |
 *         v
 *   Same while loop as s01, just more tools in the array.
 *
 * Mechanism: Tool dispatch map {name: handler}
 * Tools: bash, read_file, write_file, edit_file (4 total)
 * LOC target: 90
 */

import {
  BaseAgent,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type AgentConfig,
} from "./shared";

export class MultiToolAgent extends BaseAgent {
  constructor(config: AgentConfig) {
    super(config);
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL];
  }

  getSystemPrompt(): string {
    return [
      "You are a coding agent with file operation tools.",
      "",
      "Loop: think briefly -> use tools -> report results.",
      "",
      "Rules:",
      "- Prefer tools over prose. Act, don't just explain.",
      "- Use read_file to examine code, not bash cat.",
      "- Use edit_file for surgical changes, write_file for new files.",
      "- After finishing, summarize what changed.",
    ].join("\n");
  }

  async run(userMessage: string): Promise<string> {
    this.aborted = false;
    this.messages.push({ role: "user", content: userMessage });
    this.emit("state_change");

    let finalText = "";

    // -- THE LOOP: identical to s01, only tools[] changed --
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

      // The dispatch happens inside processToolCalls -> ToolExecutor.execute
      // ToolExecutor has a switch(name) that routes to the correct handler
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
