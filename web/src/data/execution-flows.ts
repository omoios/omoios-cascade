import type { FlowNode, FlowEdge } from "@/types/agent-data";

export interface FlowDefinition {
  nodes: FlowNode[];
  edges: FlowEdge[];
}

const FLOW_WIDTH = 600;
const COL_CENTER = FLOW_WIDTH / 2;
const COL_LEFT = 140;
const COL_RIGHT = FLOW_WIDTH - 140;

export const EXECUTION_FLOWS: Record<string, FlowDefinition> = {
  s01: {
    nodes: [
      { id: "start", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "llm", label: "LLM Call", type: "process", x: COL_CENTER, y: 110 },
      { id: "tool_check", label: "tool_use?", type: "decision", x: COL_CENTER, y: 190 },
      { id: "bash", label: "Execute Bash", type: "subprocess", x: COL_LEFT, y: 280 },
      { id: "append", label: "Append Result", type: "process", x: COL_LEFT, y: 360 },
      { id: "end", label: "Output", type: "end", x: COL_RIGHT, y: 280 },
    ],
    edges: [
      { from: "start", to: "llm" },
      { from: "llm", to: "tool_check" },
      { from: "tool_check", to: "bash", label: "yes" },
      { from: "tool_check", to: "end", label: "no" },
      { from: "bash", to: "append" },
      { from: "append", to: "llm" },
    ],
  },
  s02: {
    nodes: [
      { id: "start", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "llm", label: "LLM Call", type: "process", x: COL_CENTER, y: 110 },
      { id: "tool_check", label: "tool_use?", type: "decision", x: COL_CENTER, y: 190 },
      { id: "dispatch", label: "Tool Dispatch", type: "process", x: COL_LEFT, y: 280 },
      { id: "exec", label: "bash / read / write / edit", type: "subprocess", x: COL_LEFT, y: 360 },
      { id: "append", label: "Append Result", type: "process", x: COL_LEFT, y: 440 },
      { id: "end", label: "Output", type: "end", x: COL_RIGHT, y: 280 },
    ],
    edges: [
      { from: "start", to: "llm" },
      { from: "llm", to: "tool_check" },
      { from: "tool_check", to: "dispatch", label: "yes" },
      { from: "tool_check", to: "end", label: "no" },
      { from: "dispatch", to: "exec" },
      { from: "exec", to: "append" },
      { from: "append", to: "llm" },
    ],
  },
  s03: {
    nodes: [
      { id: "start", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "todo", label: "Create Todos", type: "process", x: COL_CENTER, y: 100 },
      { id: "llm", label: "LLM Call", type: "process", x: COL_CENTER, y: 180 },
      { id: "tool_check", label: "tool_use?", type: "decision", x: COL_CENTER, y: 260 },
      { id: "exec", label: "Execute Tool", type: "subprocess", x: COL_LEFT, y: 340 },
      { id: "append", label: "Append Result", type: "process", x: COL_LEFT, y: 410 },
      { id: "end", label: "Output", type: "end", x: COL_RIGHT, y: 340 },
    ],
    edges: [
      { from: "start", to: "todo" },
      { from: "todo", to: "llm" },
      { from: "llm", to: "tool_check" },
      { from: "tool_check", to: "exec", label: "yes" },
      { from: "tool_check", to: "end", label: "no" },
      { from: "exec", to: "append" },
      { from: "append", to: "llm" },
    ],
  },
  s06: {
    nodes: [
      { id: "start", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "compress_check", label: "Over token\nlimit?", type: "decision", x: COL_CENTER, y: 110 },
      { id: "compress", label: "Compress Context", type: "subprocess", x: COL_RIGHT, y: 110 },
      { id: "llm", label: "LLM Call", type: "process", x: COL_CENTER, y: 200 },
      { id: "tool_check", label: "tool_use?", type: "decision", x: COL_CENTER, y: 280 },
      { id: "exec", label: "Execute Tool", type: "subprocess", x: COL_LEFT, y: 360 },
      { id: "append", label: "Append Result", type: "process", x: COL_LEFT, y: 430 },
      { id: "end", label: "Output", type: "end", x: COL_RIGHT, y: 360 },
    ],
    edges: [
      { from: "start", to: "compress_check" },
      { from: "compress_check", to: "compress", label: "yes" },
      { from: "compress_check", to: "llm", label: "no" },
      { from: "compress", to: "llm" },
      { from: "llm", to: "tool_check" },
      { from: "tool_check", to: "exec", label: "yes" },
      { from: "tool_check", to: "end", label: "no" },
      { from: "exec", to: "append" },
      { from: "append", to: "compress_check" },
    ],
  },
  s08: {
    nodes: [
      { id: "start", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "llm", label: "LLM Call", type: "process", x: COL_CENTER, y: 110 },
      { id: "tool_check", label: "tool_use?", type: "decision", x: COL_CENTER, y: 190 },
      { id: "bg_check", label: "Background?", type: "decision", x: COL_LEFT, y: 280 },
      { id: "bg_spawn", label: "Spawn Thread", type: "subprocess", x: 60, y: 370 },
      { id: "exec", label: "Execute Tool", type: "subprocess", x: COL_LEFT + 80, y: 370 },
      { id: "append", label: "Append Result", type: "process", x: COL_CENTER, y: 450 },
      { id: "notify", label: "Notification\nQueue", type: "process", x: 60, y: 450 },
      { id: "end", label: "Output", type: "end", x: COL_RIGHT, y: 280 },
    ],
    edges: [
      { from: "start", to: "llm" },
      { from: "llm", to: "tool_check" },
      { from: "tool_check", to: "bg_check", label: "yes" },
      { from: "tool_check", to: "end", label: "no" },
      { from: "bg_check", to: "bg_spawn", label: "bg" },
      { from: "bg_check", to: "exec", label: "fg" },
      { from: "bg_spawn", to: "notify" },
      { from: "exec", to: "append" },
      { from: "append", to: "llm" },
      { from: "notify", to: "llm" },
    ],
  },
  s11: {
    nodes: [
      { id: "start", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "inbox", label: "Check Inbox", type: "process", x: COL_CENTER, y: 100 },
      { id: "llm", label: "LLM Call", type: "process", x: COL_CENTER, y: 180 },
      { id: "tool_check", label: "tool_use?", type: "decision", x: COL_CENTER, y: 260 },
      { id: "exec", label: "Execute Tool", type: "subprocess", x: COL_LEFT, y: 340 },
      { id: "append", label: "Append Result", type: "process", x: COL_LEFT, y: 410 },
      { id: "end", label: "Output", type: "end", x: COL_RIGHT, y: 340 },
      { id: "idle", label: "Idle Cycle", type: "process", x: COL_RIGHT, y: 420 },
      { id: "poll", label: "Poll Tasks", type: "subprocess", x: COL_RIGHT, y: 500 },
    ],
    edges: [
      { from: "start", to: "inbox" },
      { from: "inbox", to: "llm" },
      { from: "llm", to: "tool_check" },
      { from: "tool_check", to: "exec", label: "yes" },
      { from: "tool_check", to: "end", label: "no" },
      { from: "exec", to: "append" },
      { from: "append", to: "llm" },
      { from: "end", to: "idle" },
      { from: "idle", to: "poll" },
      { from: "poll", to: "inbox" },
    ],
  },
};

export function getFlowForVersion(version: string): FlowDefinition | null {
  if (EXECUTION_FLOWS[version]) return EXECUTION_FLOWS[version];
  if (version === "s09" || version === "s10")
    return EXECUTION_FLOWS["s11"] ?? null;
  if (version === "s04" || version === "s05" || version === "s07")
    return EXECUTION_FLOWS["s03"] ?? null;
  return EXECUTION_FLOWS["s01"] ?? null;
}
