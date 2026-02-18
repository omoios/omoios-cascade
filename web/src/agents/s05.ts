/**
 * s05 - Knowledge Loading (Skills)
 *
 * Two-layer injection: metadata in system prompt, body in tool_result.
 * SKILL.md files with YAML frontmatter provide domain knowledge.
 *
 *   Layer 1 (always present, cheap):
 *   +--------------------------------------+
 *   | System prompt:                       |
 *   | "Skills available:                   |
 *   |  - pdf: PDF processing guidance      |
 *   |  - api: REST API patterns"           |
 *   +--------------------------------------+
 *            ~100 tokens/skill
 *
 *   Layer 2 (on demand via load_skill):
 *   +--------------------------------------+
 *   | tool_result:                         |
 *   | <skill-loaded name="pdf">            |
 *   |   Full SKILL.md body with            |
 *   |   detailed instructions...           |
 *   | </skill-loaded>                      |
 *   +--------------------------------------+
 *            ~2000 tokens (preserves prompt cache)
 *
 * Mechanism: SkillLoader + two-layer injection
 * Tools: bash, read_file, write_file, edit_file, load_skill (5 total)
 * LOC target: 150
 */

import {
  BaseAgent, ToolExecutor,
  BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
  createMessage,
  type ToolDefinition, type AgentConfig, type AgentState,
} from "./shared";

interface SkillEntry {
  name: string;
  description: string;
  body: string;
}

class SkillLoader {
  private skills: Map<string, SkillEntry> = new Map();

  constructor(private executor: ToolExecutor) {
    this.scanSkills();
  }

  private scanSkills(): void {
    const allFiles = this.executor.fs.listFiles();
    const skillFiles = allFiles.filter(
      (f) => f.startsWith("skills/") && f.endsWith("/SKILL.md")
    );
    for (const path of skillFiles) {
      const content = this.executor.fs.getFile(path);
      if (!content) continue;
      const parsed = this.parseFrontmatter(content);
      if (parsed) this.skills.set(parsed.name, parsed);
    }
  }

  private parseFrontmatter(raw: string): SkillEntry | null {
    const match = raw.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/);
    if (!match) return null;
    const [, frontmatter, body] = match;
    const meta: Record<string, string> = {};
    for (const line of frontmatter.trim().split("\n")) {
      const colonIdx = line.indexOf(":");
      if (colonIdx === -1) continue;
      meta[line.slice(0, colonIdx).trim()] = line.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, "");
    }
    if (!meta.name || !meta.description) return null;
    return { name: meta.name, description: meta.description, body: body.trim() };
  }

  getDescriptions(): string {
    if (this.skills.size === 0) return "(no skills available)";
    const lines: string[] = [];
    for (const [name, skill] of this.skills) {
      lines.push(`- ${name}: ${skill.description}`);
    }
    return lines.join("\n");
  }

  getContent(name: string): string | null {
    const skill = this.skills.get(name);
    if (!skill) return null;
    return [
      `<skill-loaded name="${skill.name}">`,
      `# Skill: ${skill.name}`,
      "",
      skill.body,
      `</skill-loaded>`,
      "",
      "Follow the instructions in the skill above.",
    ].join("\n");
  }

  listNames(): string[] {
    return Array.from(this.skills.keys());
  }
}

const LOAD_SKILL_TOOL: ToolDefinition = {
  name: "load_skill",
  description: "Load a skill to gain specialized knowledge. Use when a task matches a skill description.",
  input_schema: {
    type: "object",
    properties: {
      skill: { type: "string", description: "Name of the skill to load" },
    },
    required: ["skill"],
  },
};

export class SkillsAgent extends BaseAgent {
  private skillLoader: SkillLoader;

  constructor(config: AgentConfig) {
    super(config);
    this.skillLoader = new SkillLoader(this.toolExecutor);
    this.toolExecutor.registerTool("load_skill", (input) => {
      const name = String(input.skill ?? "");
      const content = this.skillLoader.getContent(name);
      if (content === null) {
        const available = this.skillLoader.listNames().join(", ") || "none";
        return `Error: Unknown skill '${name}'. Available: ${available}`;
      }
      return content;
    });
  }

  getTools(): ToolDefinition[] {
    return [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, LOAD_SKILL_TOOL];
  }

  getSystemPrompt(): string {
    return [
      "You are a coding agent with skill-based knowledge loading.",
      "",
      "Skills available (invoke with load_skill when task matches):",
      this.skillLoader.getDescriptions(),
      "",
      "Use load_skill IMMEDIATELY when a task matches a skill description.",
      "Prefer tools over prose. Act, don't just explain.",
    ].join("\n");
  }

  getState(): AgentState {
    return {
      ...super.getState(),
      systemPromptParts: [
        { label: "base", content: "Coding agent with skill loading." },
        { label: "skills_metadata", content: this.skillLoader.getDescriptions() },
      ],
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

      // Layer 1: skill descriptions are in getSystemPrompt() already
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

      // Layer 2: load_skill injects body via tool_result (preserves cache)
      const toolResults = await this.processToolCalls(response.content);
      this.messages.push({ role: "user", content: toolResults });
      this.emit("state_change");
    }

    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }
}
