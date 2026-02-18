"use client";

/**
 * StateInspector: main inspector panel that shows agent internal state.
 *
 * Layout:
 *   +---------------------------+-------------------+
 *   |                           |  State Inspector   |
 *   |  Simulator / Chat         |                    |
 *   |                           |  [Tab: Messages]   |
 *   |                           |  [Tab: State]      |
 *   |                           |  [Tab: Events]     |
 *   +---------------------------+-------------------+
 *
 * Renders version-specific panels based on the AgentState fields.
 */

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { AgentState, AgentEvent } from "@/agents/shared";
import { MessagesPanel } from "./panels/messages-panel";
import { StatePanel } from "./panels/state-panel";
import { EventsPanel } from "./panels/events-panel";

type Tab = "messages" | "state" | "events";

interface StateInspectorProps {
  state: AgentState;
  events: AgentEvent[];
  version: string;
  className?: string;
}

export function StateInspector({ state, events, version, className }: StateInspectorProps) {
  const [activeTab, setActiveTab] = useState<Tab>("state");

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "messages", label: "Messages", count: state.messages.length },
    { id: "state", label: "State" },
    { id: "events", label: "Events", count: events.length },
  ];

  return (
    <div className={cn("flex flex-col border-l border-[var(--color-border)] bg-[var(--color-bg)]", className)}>
      {/* Tab bar */}
      <div className="flex border-b border-[var(--color-border)]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors",
              activeTab === tab.id
                ? "border-b-2 border-zinc-900 text-zinc-900 dark:border-white dark:text-white"
                : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="rounded-full bg-zinc-200 px-1.5 text-[10px] tabular-nums dark:bg-zinc-700">
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-y-auto p-3">
        {activeTab === "messages" && <MessagesPanel messages={state.messages} />}
        {activeTab === "state" && <StatePanel state={state} version={version} />}
        {activeTab === "events" && <EventsPanel events={events} />}
      </div>

      {/* Footer stats */}
      <div className="flex items-center gap-4 border-t border-[var(--color-border)] px-3 py-1.5 text-[10px] tabular-nums text-zinc-500">
        <span>Loop: {state.loopIteration}</span>
        <span>In: {state.totalInputTokens.toLocaleString()} tok</span>
        <span>Out: {state.totalOutputTokens.toLocaleString()} tok</span>
        <span>Tools: {state.tools.join(", ")}</span>
      </div>
    </div>
  );
}
