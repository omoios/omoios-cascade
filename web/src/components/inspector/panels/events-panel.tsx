"use client";

import type { AgentEvent } from "@/agents/shared";
import { cn } from "@/lib/utils";

interface EventsPanelProps {
  events: AgentEvent[];
}

const EVENT_COLORS: Record<string, string> = {
  state_change: "text-zinc-500",
  llm_request: "text-blue-600 dark:text-blue-400",
  llm_response: "text-blue-600 dark:text-blue-400",
  tool_call: "text-amber-600 dark:text-amber-400",
  tool_result: "text-emerald-600 dark:text-emerald-400",
  error: "text-red-600 dark:text-red-400",
  done: "text-purple-600 dark:text-purple-400",
};

export function EventsPanel({ events }: EventsPanelProps) {
  if (events.length === 0) {
    return <div className="text-xs text-zinc-500">No events yet</div>;
  }

  return (
    <div className="flex flex-col gap-0.5">
      {events.map((event, i) => (
        <div
          key={i}
          className="flex items-start gap-2 rounded px-1.5 py-0.5 font-mono text-[10px] hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <span className="shrink-0 tabular-nums text-zinc-400">
            {formatTime(event.timestamp)}
          </span>
          <span className={cn("shrink-0 font-semibold", EVENT_COLORS[event.type] || "text-zinc-500")}>
            {event.type}
          </span>
          <span className="truncate text-zinc-600 dark:text-zinc-400">
            {summarizeEvent(event)}
          </span>
        </div>
      ))}
    </div>
  );
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  return `${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}.${d.getMilliseconds().toString().padStart(3, "0")}`;
}

function summarizeEvent(event: AgentEvent): string {
  if (!event.data) return "";

  const data = event.data as Record<string, unknown>;

  switch (event.type) {
    case "llm_request":
      return `msgs=${data.messages} tools=${data.tools} iter=${data.iteration}`;
    case "llm_response":
      return `stop=${data.stopReason} blocks=${data.contentBlocks}`;
    case "tool_call":
      return `${data.name}(${JSON.stringify(data.input).slice(0, 60)})`;
    case "tool_result":
      return `${data.name}: ${String(data.content).slice(0, 60)}`;
    case "error":
      return String(data);
    case "done":
      return `${data.iterations} iterations`;
    default:
      return "";
  }
}
