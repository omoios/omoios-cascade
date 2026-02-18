export const VERSION_ORDER = [
  "s00_mini", "s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10", "s11"
] as const;

// Only show these in the learning path (skip s00_mini)
export const LEARNING_PATH = [
  "s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10", "s11"
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
  s01: { title: "Bash Agent", subtitle: "Bash is All You Need", coreAddition: "Single-tool agent loop", keyInsight: "One tool (bash) is enough to be useful", layer: "tools", prevVersion: null },
  s02: { title: "Basic Agent", subtitle: "The Model IS the Agent", coreAddition: "Multi-tool + dispatcher", keyInsight: "4 tools beat 1: read, write, edit, bash", layer: "tools", prevVersion: "s01" },
  s03: { title: "Todo Agent", subtitle: "Make Plans Visible", coreAddition: "TodoManager for planning", keyInsight: "Visible plans improve task completion", layer: "planning", prevVersion: "s02" },
  s04: { title: "Subagent", subtitle: "Divide and Conquer", coreAddition: "Agent registry + Task tool", keyInsight: "Context isolation prevents confusion", layer: "planning", prevVersion: "s03" },
  s05: { title: "Skills Agent", subtitle: "Knowledge Externalization", coreAddition: "SkillLoader + dynamic injection", keyInsight: "Skills inject via tool_result, not system prompt", layer: "planning", prevVersion: "s04" },
  s06: { title: "Compression Agent", subtitle: "Strategic Forgetting", coreAddition: "3-layer context compression", keyInsight: "Forgetting old results enables infinite work", layer: "memory", prevVersion: "s05" },
  s07: { title: "Tasks Agent", subtitle: "Shared Task Board", coreAddition: "TaskManager with CRUD + deps", keyInsight: "File-based persistence outlives process memory", layer: "planning", prevVersion: "s06" },
  s08: { title: "Background Agent", subtitle: "Fire and Forget", coreAddition: "BackgroundManager + notifications", keyInsight: "Non-blocking execution via threads + queue", layer: "concurrency", prevVersion: "s07" },
  s09: { title: "Team Messaging", subtitle: "From Commands to Collaboration", coreAddition: "TeammateManager + MessageBus + JSONL inbox", keyInsight: "Persistent teammates + async JSONL inboxes decouple communication", layer: "collaboration", prevVersion: "s08" },
  s10: { title: "Team Protocols", subtitle: "Coordinated Lifecycle Control", coreAddition: "Shutdown + plan approval protocols with request_id correlation", keyInsight: "Request-response protocols enable coordinated team operations", layer: "collaboration", prevVersion: "s09" },
  s11: { title: "Autonomous Agent", subtitle: "Teammates That Think", coreAddition: "Idle cycle + auto-claiming", keyInsight: "Polling + timeout makes teammates autonomous", layer: "collaboration", prevVersion: "s10" },
};

export const LAYERS = [
  { id: "tools" as const, label: "Tools & Execution", color: "#3B82F6", versions: ["s01", "s02"] },
  { id: "planning" as const, label: "Planning & Coordination", color: "#10B981", versions: ["s03", "s04", "s05", "s07"] },
  { id: "memory" as const, label: "Memory Management", color: "#8B5CF6", versions: ["s06"] },
  { id: "concurrency" as const, label: "Concurrency", color: "#F59E0B", versions: ["s08"] },
  { id: "collaboration" as const, label: "Collaboration", color: "#EF4444", versions: ["s09", "s10", "s11"] },
] as const;
