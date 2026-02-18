export const VERSION_ORDER = [
  "v0_mini", "v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8a", "v8b", "v8c", "v9"
] as const;

// Only show these in the learning path (skip v0_mini)
export const LEARNING_PATH = [
  "v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8a", "v8b", "v8c", "v9"
] as const;

export type VersionId = typeof LEARNING_PATH[number];

export const VERSION_META: Record<string, {
  title: string;
  subtitle: string;
  coreAddition: string;
  keyInsight: string;
  layer: "tools" | "planning" | "memory" | "concurrency" | "collaboration";
  prevVersion: string | null;
}> = {
  v0: { title: "Bash Agent", subtitle: "Bash is All You Need", coreAddition: "Single-tool agent loop", keyInsight: "One tool (bash) is enough to be useful", layer: "tools", prevVersion: null },
  v1: { title: "Basic Agent", subtitle: "The Model IS the Agent", coreAddition: "Multi-tool + dispatcher", keyInsight: "4 tools beat 1: read, write, edit, bash", layer: "tools", prevVersion: "v0" },
  v2: { title: "Todo Agent", subtitle: "Make Plans Visible", coreAddition: "TodoManager for planning", keyInsight: "Visible plans improve task completion", layer: "planning", prevVersion: "v1" },
  v3: { title: "Subagent", subtitle: "Divide and Conquer", coreAddition: "Agent registry + Task tool", keyInsight: "Context isolation prevents confusion", layer: "planning", prevVersion: "v2" },
  v4: { title: "Skills Agent", subtitle: "Knowledge Externalization", coreAddition: "SkillLoader + dynamic injection", keyInsight: "Skills inject via tool_result, not system prompt", layer: "planning", prevVersion: "v3" },
  v5: { title: "Compression Agent", subtitle: "Strategic Forgetting", coreAddition: "3-layer context compression", keyInsight: "Forgetting old results enables infinite work", layer: "memory", prevVersion: "v4" },
  v6: { title: "Tasks Agent", subtitle: "Shared Task Board", coreAddition: "TaskManager with CRUD + deps", keyInsight: "File-based persistence outlives process memory", layer: "planning", prevVersion: "v5" },
  v7: { title: "Background Agent", subtitle: "Fire and Forget", coreAddition: "BackgroundManager + notifications", keyInsight: "Non-blocking execution via threads + queue", layer: "concurrency", prevVersion: "v6" },
  v8a: { title: "Team Foundation", subtitle: "From Commands to Collaboration", coreAddition: "TeammateManager + team identity", keyInsight: "Persistent teammates vs one-shot subagents", layer: "collaboration", prevVersion: "v7" },
  v8b: { title: "Team Messaging", subtitle: "Inbox-Based Communication", coreAddition: "File-based inbox + 5 message types", keyInsight: "Async JSONL inboxes decouple communication", layer: "collaboration", prevVersion: "v8a" },
  v8c: { title: "Team Coordination", subtitle: "Shared Board + Protocol", coreAddition: "Shutdown protocol + plan approval", keyInsight: "Dependency graph prevents duplicate work", layer: "collaboration", prevVersion: "v8b" },
  v9: { title: "Autonomous Agent", subtitle: "Teammates That Think", coreAddition: "Idle cycle + auto-claiming", keyInsight: "Polling + timeout makes teammates autonomous", layer: "collaboration", prevVersion: "v8c" },
};

export const LAYERS = [
  { id: "tools" as const, label: "Tools & Execution", color: "#3B82F6", versions: ["v0", "v1"] },
  { id: "planning" as const, label: "Planning & Coordination", color: "#10B981", versions: ["v2", "v3", "v4", "v6"] },
  { id: "memory" as const, label: "Memory Management", color: "#8B5CF6", versions: ["v5"] },
  { id: "concurrency" as const, label: "Concurrency", color: "#F59E0B", versions: ["v7"] },
  { id: "collaboration" as const, label: "Collaboration", color: "#EF4444", versions: ["v8a", "v8b", "v8c", "v9"] },
] as const;
