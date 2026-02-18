"use client";

/**
 * Playground: real agent execution with state inspector.
 *
 * Layout:
 *   +-----------------------------------+------------------+
 *   | Chat / Agent Output               | State Inspector  |
 *   |                                   |                  |
 *   | [User] Create hello.py            | messages[]: 4    |
 *   | [Assistant] I'll create that...   | loop: 2          |
 *   | [Tool: bash] echo ...             | tokens: 1,247    |
 *   | [Result] File written             | tools: [bash]    |
 *   |                                   |                  |
 *   | [input box] [send]                |                  |
 *   +-----------------------------------+------------------+
 */

import { useState, useRef, useEffect } from "react";
import { useTranslations } from "@/lib/i18n";
import { useAgentRunner } from "@/hooks/useAgentRunner";
import { StateInspector } from "@/components/inspector";
import { Send, Square, RotateCcw, Eye, EyeOff, PanelRightOpen, PanelRightClose } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Message, ContentBlock, ToolResultBlock } from "@/agents/shared";

const VERSION_OPTIONS = [
  "s01", "s02", "s03", "s04", "s05",
  "s06", "s07", "s08",
  "s09", "s10", "s11",
] as const;

type VersionId = typeof VERSION_OPTIONS[number];

export default function PlaygroundPage() {
  const t = useTranslations("playground");

  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [version, setVersion] = useState<VersionId>("s01");
  const [input, setInput] = useState("");
  const [showInspector, setShowInspector] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { state, events, isRunning, error, sendMessage, abort, reset } =
    useAgentRunner(version, apiKey);

  useEffect(() => {
    const stored = localStorage.getItem("anthropic_api_key");
    if (stored) setApiKey(stored);
  }, []);

  useEffect(() => {
    if (apiKey) localStorage.setItem("anthropic_api_key", apiKey);
  }, [apiKey]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [state.messages.length]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || !apiKey || isRunning) return;
    sendMessage(input.trim());
    setInput("");
  }

  function handleVersionChange(v: VersionId) {
    setVersion(v);
    reset();
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      {/* Top bar: API key + version selector */}
      <div className="flex flex-wrap items-center gap-3 border-b border-[var(--color-border)] px-4 py-3">
        <div className="flex flex-1 items-center gap-2">
          <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
            <input
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-ant-..."
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1.5 pr-8 font-mono text-xs outline-none focus:border-zinc-400"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-400"
            >
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-1">
          {VERSION_OPTIONS.map((v) => (
            <button
              key={v}
              onClick={() => handleVersionChange(v)}
              className={cn(
                "rounded px-2 py-1 text-[10px] font-medium transition-colors",
                version === v
                  ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                  : "border border-[var(--color-border)] text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              )}
            >
              {v}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={reset}
            className="flex items-center gap-1 rounded-md border border-[var(--color-border)] px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            <RotateCcw size={12} />
            Reset
          </button>
          <button
            onClick={() => setShowInspector(!showInspector)}
            className="flex items-center gap-1 rounded-md border border-[var(--color-border)] px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            {showInspector ? <PanelRightClose size={12} /> : <PanelRightOpen size={12} />}
            Inspector
          </button>
        </div>
      </div>

      {/* Main content: chat + inspector */}
      <div className="flex flex-1 overflow-hidden">
        {/* Chat area */}
        <div className="flex flex-1 flex-col">
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto p-4"
          >
            {state.messages.length === 0 ? (
              <div className="flex h-full items-center justify-center">
                <div className="text-center">
                  <div className="text-lg font-semibold">{t("title")}</div>
                  <div className="mt-1 text-sm text-zinc-500">
                    {apiKey ? `Selected: ${version} -- type a message to start` : "Enter your API key to begin"}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mx-auto flex max-w-2xl flex-col gap-3">
                {state.messages.map((msg, i) => (
                  <ChatMessage key={i} message={msg} />
                ))}
                {isRunning && (
                  <div className="flex items-center gap-2 text-sm text-zinc-500">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                    Agent thinking...
                  </div>
                )}
              </div>
            )}
          </div>

          {error && (
            <div className="mx-4 mb-2 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
              {error}
            </div>
          )}

          {/* Input */}
          <form
            onSubmit={handleSubmit}
            className="flex gap-2 border-t border-[var(--color-border)] p-3"
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={!apiKey ? "Enter API key first..." : `Message ${version} agent...`}
              disabled={!apiKey || isRunning}
              className="flex-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm outline-none focus:border-zinc-400 disabled:opacity-50"
            />
            {isRunning ? (
              <button
                type="button"
                onClick={abort}
                className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-500 text-white hover:bg-red-600"
              >
                <Square size={16} />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!apiKey || !input.trim()}
                className="flex h-10 w-10 items-center justify-center rounded-lg bg-zinc-900 text-white hover:bg-zinc-700 disabled:opacity-40 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                <Send size={16} />
              </button>
            )}
          </form>
        </div>

        {/* State Inspector */}
        {showInspector && (
          <StateInspector
            state={state}
            events={events}
            version={version}
            className="hidden w-80 shrink-0 md:flex"
          />
        )}
      </div>
    </div>
  );
}

function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === "user";

  if (typeof message.content === "string") {
    return (
      <div className={cn("rounded-lg px-3 py-2 text-sm", isUser ? "bg-blue-50 dark:bg-blue-950" : "bg-zinc-50 dark:bg-zinc-900")}>
        <div className="mb-1 text-[10px] font-semibold uppercase text-zinc-500">{message.role}</div>
        <div className="whitespace-pre-wrap">{message.content}</div>
      </div>
    );
  }

  return (
    <div className={cn("rounded-lg px-3 py-2 text-sm", isUser ? "bg-blue-50 dark:bg-blue-950" : "bg-zinc-50 dark:bg-zinc-900")}>
      <div className="mb-1 text-[10px] font-semibold uppercase text-zinc-500">{message.role}</div>
      <div className="flex flex-col gap-1.5">
        {(message.content as (ContentBlock | ToolResultBlock)[]).map((block, j) => {
          if (block.type === "text") {
            return <div key={j} className="whitespace-pre-wrap">{block.text}</div>;
          }
          if (block.type === "tool_use") {
            return (
              <div key={j} className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 dark:border-amber-800 dark:bg-amber-950">
                <div className="font-mono text-xs font-semibold text-amber-700 dark:text-amber-300">
                  {block.name}
                </div>
                <pre className="mt-1 whitespace-pre-wrap font-mono text-xs text-amber-600 dark:text-amber-400">
                  {JSON.stringify(block.input, null, 2)}
                </pre>
              </div>
            );
          }
          if (block.type === "tool_result") {
            return (
              <div key={j} className={cn(
                "rounded border px-2 py-1.5",
                block.is_error
                  ? "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950"
                  : "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950"
              )}>
                <pre className={cn(
                  "whitespace-pre-wrap font-mono text-xs",
                  block.is_error ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"
                )}>
                  {block.content}
                </pre>
              </div>
            );
          }
          return null;
        })}
      </div>
    </div>
  );
}
