"use client";

/**
 * StatePanel: version-specific state visualization.
 *
 * Renders different sections based on which AgentState fields
 * are populated, giving each version its unique inspector view:
 *
 *   s01-s02: tools list + loop counter
 *   s03:     + todo checklist
 *   s04:     + subagent context tree
 *   s05:     + system prompt assembly
 *   s06:     + token gauge bar
 *   s07:     + task dependency graph
 *   s08:     + background thread timeline
 *   s09:     + team roster + inbox viewer
 *   s10:     + shutdown protocol FSM + plan approval FSM
 *   s11:     + idle cycle indicator
 */

import type { AgentState } from "@/agents/shared";
import { cn } from "@/lib/utils";

interface StatePanelProps {
  state: AgentState;
  version: string;
}

export function StatePanel({ state, version }: StatePanelProps) {
  return (
    <div className="flex flex-col gap-3">
      {/* Always shown: tools and loop info */}
      <Section title="Agent Loop">
        <div className="flex flex-col gap-1 text-[11px]">
          <Row label="iteration" value={state.loopIteration} />
          <Row label="stop_reason" value={state.stopReason || "—"} />
          <Row label="messages" value={state.messages.length} />
          <Row label="input_tokens" value={state.totalInputTokens.toLocaleString()} />
          <Row label="output_tokens" value={state.totalOutputTokens.toLocaleString()} />
        </div>
      </Section>

      <Section title="Tools">
        <div className="flex flex-wrap gap-1">
          {state.tools.map((t) => (
            <span
              key={t}
              className="rounded bg-zinc-200 px-1.5 py-0.5 font-mono text-[10px] dark:bg-zinc-700"
            >
              {t}
            </span>
          ))}
        </div>
      </Section>

      {/* s03: Todo list */}
      {state.todos && (
        <Section title="TodoManager" highlight="planning">
          {state.todos.length === 0 ? (
            <div className="text-[10px] text-zinc-500">No todos</div>
          ) : (
            <div className="flex flex-col gap-0.5">
              {state.todos.map((todo) => (
                <div key={todo.id} className="flex items-center gap-1.5 text-[11px]">
                  <span className={cn("font-mono", todo.done ? "text-emerald-500" : "text-zinc-400")}>
                    {todo.done ? "[x]" : "[ ]"}
                  </span>
                  <span className={cn(todo.done && "line-through text-zinc-400")}>{todo.text}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* s04: Subagent contexts */}
      {state.subagentContexts && (
        <Section title="Subagent Contexts" highlight="planning">
          {state.subagentContexts.length === 0 ? (
            <div className="text-[10px] text-zinc-500">No subagents spawned</div>
          ) : (
            <div className="flex flex-col gap-0.5">
              {state.subagentContexts.map((ctx) => (
                <div key={ctx.name} className="flex items-center justify-between text-[11px]">
                  <span className="font-mono">{ctx.name}</span>
                  <span className="text-zinc-500">{ctx.messageCount} msgs</span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* s05: System prompt parts */}
      {state.systemPromptParts && (
        <Section title="System Prompt Assembly" highlight="planning">
          <div className="flex flex-col gap-1">
            {state.systemPromptParts.map((part, i) => (
              <div key={i} className="rounded border border-[var(--color-border)] p-1.5">
                <div className="text-[10px] font-semibold text-purple-600 dark:text-purple-400">
                  {part.label}
                </div>
                <pre className="mt-0.5 whitespace-pre-wrap font-mono text-[9px] text-zinc-600 dark:text-zinc-400">
                  {part.content.slice(0, 100)}{part.content.length > 100 ? "..." : ""}
                </pre>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* s06: Compression */}
      {state.compression && (
        <Section title="Context Compression" highlight="memory">
          <div className="flex flex-col gap-2">
            {/* Token gauge */}
            <div>
              <div className="mb-1 flex items-center justify-between text-[10px]">
                <span>Tokens: {state.compression.totalTokens.toLocaleString()}</span>
                <span className="text-zinc-500">
                  Threshold: {state.compression.threshold.toLocaleString()}
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    state.compression.totalTokens > state.compression.threshold
                      ? "bg-red-500"
                      : state.compression.totalTokens > state.compression.threshold * 0.8
                        ? "bg-amber-500"
                        : "bg-emerald-500"
                  )}
                  style={{
                    width: `${Math.min(100, (state.compression.totalTokens / state.compression.threshold) * 100)}%`,
                  }}
                />
              </div>
            </div>
            {/* Compression layers */}
            <div className="flex flex-col gap-0.5">
              {state.compression.layers.map((layer) => (
                <div key={layer.name} className="flex items-center justify-between text-[10px]">
                  <span className="font-mono">{layer.name}</span>
                  <span className={cn(layer.triggered ? "text-amber-500" : "text-zinc-400")}>
                    {layer.triggered ? "triggered" : "standby"}
                  </span>
                </div>
              ))}
            </div>
            <div className="text-[10px] text-zinc-500">
              Compressions: {state.compression.compressionCount}
            </div>
          </div>
        </Section>
      )}

      {/* s07: Tasks */}
      {state.tasks && (
        <Section title="Task Board" highlight="planning">
          {state.tasks.length === 0 ? (
            <div className="text-[10px] text-zinc-500">No tasks</div>
          ) : (
            <div className="flex flex-col gap-1">
              {state.tasks.map((task) => (
                <div key={task.id} className="flex flex-col gap-0.5 rounded border border-[var(--color-border)] p-1.5">
                  <div className="flex items-center gap-2 text-[11px]">
                    <span
                      className={cn(
                        "h-2 w-2 shrink-0 rounded-full",
                        task.status === "completed" ? "bg-emerald-500" :
                        task.status === "in_progress" ? "bg-blue-500" : "bg-zinc-300"
                      )}
                    />
                    <span className="flex-1 truncate font-mono">{task.subject}</span>
                    <span className="shrink-0 text-[10px] text-zinc-500">{task.status}</span>
                  </div>
                  {task.labels && task.labels.length > 0 && (
                    <div className="flex flex-wrap gap-1 pl-3.5">
                      {task.labels.map((label) => (
                        <span
                          key={label}
                          className="rounded bg-blue-100 px-1.5 py-0.5 text-[9px] font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* s08: Background threads */}
      {state.backgroundThreads && (
        <Section title="Background Threads" highlight="concurrency">
          {state.backgroundThreads.length === 0 ? (
            <div className="text-[10px] text-zinc-500">No background tasks</div>
          ) : (
            <div className="flex flex-col gap-1">
              {state.backgroundThreads.map((thread) => (
                <div key={thread.id} className="flex items-center gap-2 text-[11px]">
                  <span
                    className={cn(
                      "h-2 w-2 shrink-0 rounded-full",
                      thread.status === "running" ? "animate-pulse bg-blue-500" : "bg-emerald-500"
                    )}
                  />
                  <span className="flex-1 truncate font-mono text-[10px]">{thread.command}</span>
                  <span className="text-[10px] text-zinc-500">{thread.status}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* s09: Team roster */}
      {state.teammates && (
        <Section title="Team Roster" highlight="collaboration">
          {state.teammates.length === 0 ? (
            <div className="text-[10px] text-zinc-500">No teammates</div>
          ) : (
            <div className="flex flex-col gap-1">
              {state.teammates.map((tm) => (
                <div key={tm.name} className="flex items-center gap-2 text-[11px]">
                  <span
                    className={cn(
                      "h-2 w-2 shrink-0 rounded-full",
                      tm.status === "working" ? "animate-pulse bg-blue-500" :
                      tm.status === "idle" ? "bg-amber-500" : "bg-zinc-300"
                    )}
                  />
                  <span className="font-mono">{tm.name}</span>
                  <span className="text-[10px] text-zinc-500">{tm.status}</span>
                  {tm.currentTask && (
                    <span className="truncate text-[10px] text-zinc-400">({tm.currentTask})</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* s10: Inbox */}
      {state.inbox && (
        <Section title="Inbox" highlight="collaboration">
          {state.inbox.length === 0 ? (
            <div className="text-[10px] text-zinc-500">No messages</div>
          ) : (
            <div className="flex flex-col gap-1">
              {state.inbox.slice(-5).map((msg, i) => (
                <div key={i} className="rounded border border-[var(--color-border)] p-1.5 text-[10px]">
                  <div className="flex items-center gap-1">
                    <span className="font-semibold">{msg.from}</span>
                    <span className="rounded bg-zinc-200 px-1 text-[9px] dark:bg-zinc-700">
                      {msg.type}
                    </span>
                  </div>
                  <div className="mt-0.5 text-zinc-600 dark:text-zinc-400">
                    {msg.content.slice(0, 80)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* s10: Protocol state */}
      {state.protocolState && (
        <Section title="Protocol State" highlight="collaboration">
          <div className="flex flex-col gap-2">
            <div>
              <div className="text-[10px] font-semibold">Shutdown Requests</div>
              {state.protocolState.shutdownRequests.length === 0 ? (
                <div className="text-[10px] text-zinc-500">None</div>
              ) : (
                state.protocolState.shutdownRequests.map((req) => (
                  <div key={req.id} className="flex items-center gap-2 text-[10px]">
                    <span className="font-mono">{req.target}</span>
                    <StatusBadge status={req.status} />
                  </div>
                ))
              )}
            </div>
            <div>
              <div className="text-[10px] font-semibold">Plan Approvals</div>
              {state.protocolState.planApprovals.length === 0 ? (
                <div className="text-[10px] text-zinc-500">None</div>
              ) : (
                state.protocolState.planApprovals.map((req) => (
                  <div key={req.id} className="flex items-center gap-2 text-[10px]">
                    <span className="font-mono">{req.from}</span>
                    <StatusBadge status={req.status} />
                  </div>
                ))
              )}
            </div>
          </div>
        </Section>
      )}

      {/* s11: Idle cycle */}
      {state.idleCycle && (
        <Section title="Idle Cycle" highlight="collaboration">
          <div className="flex flex-col gap-1 text-[11px]">
            <Row
              label="status"
              value={state.idleCycle.isIdle ? "IDLE" : "ACTIVE"}
              highlight={state.idleCycle.isIdle}
            />
            <Row label="poll_count" value={state.idleCycle.pollCount} />
            {state.idleCycle.claimedTask && (
              <Row label="claimed_task" value={state.idleCycle.claimedTask} />
            )}
          </div>
        </Section>
      )}

      {/* Version indicator */}
      <div className="mt-2 text-center text-[10px] text-zinc-400">
        Inspector: {version}
      </div>
    </div>
  );
}

// -- Shared sub-components --

const HIGHLIGHT_COLORS: Record<string, string> = {
  tools: "border-l-blue-500",
  planning: "border-l-emerald-500",
  memory: "border-l-purple-500",
  concurrency: "border-l-amber-500",
  collaboration: "border-l-red-500",
};

function Section({
  title,
  highlight,
  children,
}: {
  title: string;
  highlight?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded border border-[var(--color-border)] p-2",
        highlight && `border-l-2 ${HIGHLIGHT_COLORS[highlight] || ""}`
      )}
    >
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="font-mono text-zinc-500">{label}</span>
      <span
        className={cn(
          "font-mono",
          highlight ? "font-semibold text-amber-500" : ""
        )}
      >
        {String(value)}
      </span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "approved" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300" :
    status === "rejected" ? "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300" :
    "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300";

  return (
    <span className={cn("rounded px-1 py-0.5 text-[9px] font-medium", color)}>
      {status}
    </span>
  );
}
