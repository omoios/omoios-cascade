export const VERSION_ORDER = [
  "s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10", "s11"
] as const;

export const LEARNING_PATH = VERSION_ORDER;

export type VersionId = typeof LEARNING_PATH[number];

export const VERSION_META: Record<string, {
  title: string;
  subtitle: string;
  coreAddition: string;
  keyInsight: string;
  layer: "tools" | "planning" | "memory" | "concurrency" | "collaboration";
  prevVersion: string | null;
}> = {
  s01: { title: "The Agent Loop", subtitle: "Bash is All You Need", coreAddition: "Single-tool agent loop", keyInsight: "The entire agent is a while loop + one tool", layer: "tools", prevVersion: null },
  s02: { title: "Tools", subtitle: "The Loop Didn't Change", coreAddition: "Tool dispatch map", keyInsight: "Adding tools means adding handlers, the loop stays the same", layer: "tools", prevVersion: "s01" },
  s03: { title: "TodoWrite", subtitle: "Plan Before You Act", coreAddition: "TodoManager + nag reminder", keyInsight: "Visible plans improve task completion and accountability", layer: "planning", prevVersion: "s02" },
  s04: { title: "Subagents", subtitle: "Fresh Context via Task Tool", coreAddition: "Subagent spawn with isolated messages[]", keyInsight: "Process isolation = context isolation", layer: "planning", prevVersion: "s03" },
  s05: { title: "Skills", subtitle: "SKILL.md + tool_result Injection", coreAddition: "SkillLoader + two-layer injection", keyInsight: "Skills inject via tool_result, not system prompt", layer: "planning", prevVersion: "s04" },
  s06: { title: "Compact", subtitle: "Strategic Forgetting", coreAddition: "micro-compact + auto-compact + archival", keyInsight: "Forgetting old context enables infinite-length sessions", layer: "memory", prevVersion: "s05" },
  s07: { title: "Tasks", subtitle: "Persistent CRUD with Dependencies", coreAddition: "TaskManager with file-based state + dependency graph", keyInsight: "File-based state survives context compression", layer: "planning", prevVersion: "s06" },
  s08: { title: "Background Tasks", subtitle: "Fire and Forget", coreAddition: "BackgroundManager + notification queue", keyInsight: "Non-blocking daemon threads + notification queue", layer: "concurrency", prevVersion: "s07" },
  s09: { title: "Agent Teams", subtitle: "Teammates + Mailboxes", coreAddition: "TeammateManager + file-based mailbox", keyInsight: "Persistent teammates with async mailbox inboxes", layer: "collaboration", prevVersion: "s08" },
  s10: { title: "Team Protocols", subtitle: "Shutdown + Plan Approval", coreAddition: "request_id correlation for two protocols", keyInsight: "Same request-response pattern, two applications", layer: "collaboration", prevVersion: "s09" },
  s11: { title: "Autonomous Agents", subtitle: "Idle Cycle + Auto-Claim", coreAddition: "Task board polling + timeout-based self-governance", keyInsight: "Polling + timeout makes teammates self-organizing", layer: "collaboration", prevVersion: "s10" },
};

export const LAYERS = [
  { id: "tools" as const, label: "Tools & Execution", color: "#3B82F6", versions: ["s01", "s02"] },
  { id: "planning" as const, label: "Planning & Coordination", color: "#10B981", versions: ["s03", "s04", "s05", "s07"] },
  { id: "memory" as const, label: "Memory Management", color: "#8B5CF6", versions: ["s06"] },
  { id: "concurrency" as const, label: "Concurrency", color: "#F59E0B", versions: ["s08"] },
  { id: "collaboration" as const, label: "Collaboration", color: "#EF4444", versions: ["s09", "s10", "s11"] },
] as const;
