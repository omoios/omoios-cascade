"use client";

import { useState } from "react";
import { ArchDiagram } from "@/components/architecture/arch-diagram";
import { WhatsNew } from "@/components/diff/whats-new";
import { DesignDecisions } from "@/components/architecture/design-decisions";
import { DocRenderer } from "@/components/docs/doc-renderer";
import { SourceViewer } from "@/components/code/source-viewer";
import { AgentLoopSimulator } from "@/components/simulator/agent-loop-simulator";
import { ExecutionFlow } from "@/components/architecture/execution-flow";
import { StateInspector } from "@/components/inspector";
import { useAgentRunner } from "@/hooks/useAgentRunner";
import { Send, Square, PanelRightOpen, PanelRightClose } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Message, ContentBlock, ToolResultBlock } from "@/agents/shared";

interface VersionDetailClientProps {
  version: string;
  diff: {
    from: string;
    to: string;
    newClasses: string[];
    newFunctions: string[];
    newTools: string[];
    locDelta: number;
  } | null;
  source: string;
  filename: string;
}

type VersionId =
  | "s01" | "s02" | "s03" | "s04" | "s05"
  | "s06" | "s07" | "s08"
  | "s09" | "s10" | "s11";

export function VersionDetailClient({
  version,
  diff,
  source,
  filename,
}: VersionDetailClientProps) {
  const [apiKey, setApiKey] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("anthropic_api_key") || "";
    }
    return "";
  });
  const [showTryIt, setShowTryIt] = useState(false);
  const [showInspector, setShowInspector] = useState(true);
  const [input, setInput] = useState("");

  const { state, events, isRunning, error, sendMessage, abort, reset } =
    useAgentRunner(version as VersionId, apiKey);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || !apiKey || isRunning) return;
    if (apiKey) localStorage.setItem("anthropic_api_key", apiKey);
    sendMessage(input.trim());
    setInput("");
  }

  return (
    <>
      {/* Agent Loop Simulator */}
      <AgentLoopSimulator version={version} />

      {/* Execution Flow Diagram */}
      <ExecutionFlow version={version} />

      {/* Architecture Diagram */}
      <section>
        <h2 className="mb-4 text-xl font-semibold">Architecture</h2>
        <ArchDiagram version={version} />
      </section>

      {/* What's New */}
      {diff && <WhatsNew diff={diff} />}

      {/* Try It: live agent with inspector */}
      <section>
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">Try It Live</h2>
          <button
            onClick={() => setShowTryIt(!showTryIt)}
            className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            {showTryIt ? "Hide" : "Open"} Live Agent
          </button>
        </div>

        {showTryIt && (
          <div className="mt-4 overflow-hidden rounded-xl border border-[var(--color-border)]">
            {/* API key input */}
            {!apiKey && (
              <div className="border-b border-[var(--color-border)] p-3">
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Enter Anthropic API key (sk-ant-...)"
                  className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 font-mono text-xs outline-none focus:border-zinc-400"
                />
              </div>
            )}

            {/* Chat + Inspector layout */}
            <div className="flex">
              {/* Chat */}
              <div className="flex flex-1 flex-col">
                <div className="max-h-[300px] min-h-[150px] overflow-y-auto p-3">
                  {state.messages.length === 0 ? (
                    <div className="flex h-[150px] items-center justify-center text-sm text-zinc-500">
                      {apiKey ? `Run ${version} agent -- type a message` : "Enter API key above"}
                    </div>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {state.messages.map((msg, i) => (
                        <MiniChatMessage key={i} message={msg} />
                      ))}
                      {isRunning && (
                        <div className="flex items-center gap-2 text-xs text-zinc-500">
                          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
                          Running...
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {error && (
                  <div className="mx-3 mb-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
                    {error}
                  </div>
                )}

                <form onSubmit={handleSubmit} className="flex gap-2 border-t border-[var(--color-border)] p-2">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder={!apiKey ? "API key required" : "Type a message..."}
                    disabled={!apiKey || isRunning}
                    className="flex-1 rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1.5 text-xs outline-none focus:border-zinc-400 disabled:opacity-50"
                  />
                  {isRunning ? (
                    <button type="button" onClick={abort} className="rounded bg-red-500 p-1.5 text-white">
                      <Square size={14} />
                    </button>
                  ) : (
                    <button
                      type="submit"
                      disabled={!apiKey || !input.trim()}
                      className="rounded bg-zinc-900 p-1.5 text-white disabled:opacity-40 dark:bg-white dark:text-zinc-900"
                    >
                      <Send size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowInspector(!showInspector)}
                    className="rounded border border-[var(--color-border)] p-1.5 text-zinc-500 hover:text-zinc-700"
                  >
                    {showInspector ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
                  </button>
                </form>
              </div>

              {/* Inspector */}
              {showInspector && (
                <StateInspector
                  state={state}
                  events={events}
                  version={version}
                  className="hidden w-72 shrink-0 md:flex"
                />
              )}
            </div>
          </div>
        )}
      </section>

      {/* Design Decisions */}
      <DesignDecisions version={version} />

      {/* Tutorial Doc */}
      <DocRenderer version={version} />

      {/* Source Code */}
      <SourceViewer source={source} filename={filename} />
    </>
  );
}

function MiniChatMessage({ message }: { message: Message }) {
  const isUser = message.role === "user";

  if (typeof message.content === "string") {
    return (
      <div className={cn("rounded px-2 py-1.5 text-xs", isUser ? "bg-blue-50 dark:bg-blue-950" : "bg-zinc-50 dark:bg-zinc-900")}>
        <span className="font-semibold">{message.role}: </span>
        {message.content.slice(0, 200)}{message.content.length > 200 ? "..." : ""}
      </div>
    );
  }

  return (
    <div className={cn("rounded px-2 py-1.5 text-xs", isUser ? "bg-blue-50 dark:bg-blue-950" : "bg-zinc-50 dark:bg-zinc-900")}>
      {(message.content as (ContentBlock | ToolResultBlock)[]).map((block, j) => {
        if (block.type === "text") return <div key={j}>{block.text.slice(0, 150)}</div>;
        if (block.type === "tool_use") {
          return (
            <div key={j} className="mt-1 rounded bg-amber-50 px-1.5 py-0.5 font-mono text-[10px] dark:bg-amber-950">
              {block.name}({JSON.stringify(block.input).slice(0, 80)})
            </div>
          );
        }
        if (block.type === "tool_result") {
          return (
            <div key={j} className="mt-1 rounded bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] dark:bg-emerald-950">
              {block.content.slice(0, 100)}
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}
