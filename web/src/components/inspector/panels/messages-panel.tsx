"use client";

import type { Message, ContentBlock, ToolResultBlock } from "@/agents/shared";
import { cn } from "@/lib/utils";

interface MessagesPanelProps {
  messages: Message[];
}

export function MessagesPanel({ messages }: MessagesPanelProps) {
  if (messages.length === 0) {
    return <div className="text-xs text-zinc-500">No messages yet</div>;
  }

  return (
    <div className="flex flex-col gap-2">
      {messages.map((msg, i) => (
        <MessageItem key={i} index={i} message={msg} />
      ))}
    </div>
  );
}

function MessageItem({ index, message }: { index: number; message: Message }) {
  const isUser = message.role === "user";

  return (
    <div className="rounded border border-[var(--color-border)] text-xs">
      {/* Header */}
      <div
        className={cn(
          "flex items-center gap-2 px-2 py-1 font-mono text-[10px]",
          isUser
            ? "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
            : "bg-zinc-50 text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
        )}
      >
        <span className="font-semibold">[{index}]</span>
        <span>{message.role}</span>
      </div>

      {/* Content */}
      <div className="px-2 py-1.5">
        {typeof message.content === "string" ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-[11px]">
            {truncate(message.content, 200)}
          </pre>
        ) : (
          <div className="flex flex-col gap-1">
            {(message.content as (ContentBlock | ToolResultBlock)[]).map((block, j) => (
              <BlockItem key={j} block={block} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function BlockItem({ block }: { block: ContentBlock | ToolResultBlock }) {
  if (block.type === "text") {
    return (
      <pre className="whitespace-pre-wrap break-words font-mono text-[11px]">
        {truncate(block.text, 150)}
      </pre>
    );
  }

  if (block.type === "tool_use") {
    return (
      <div className="rounded bg-amber-50 px-1.5 py-1 dark:bg-amber-950">
        <span className="font-mono text-[10px] font-semibold text-amber-700 dark:text-amber-300">
          tool_use: {block.name}
        </span>
        <pre className="mt-0.5 whitespace-pre-wrap break-words font-mono text-[10px] text-amber-600 dark:text-amber-400">
          {truncate(JSON.stringify(block.input, null, 2), 100)}
        </pre>
      </div>
    );
  }

  if (block.type === "tool_result") {
    return (
      <div className="rounded bg-emerald-50 px-1.5 py-1 dark:bg-emerald-950">
        <span className="font-mono text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">
          tool_result{block.is_error ? " (error)" : ""}
        </span>
        <pre className="mt-0.5 whitespace-pre-wrap break-words font-mono text-[10px] text-emerald-600 dark:text-emerald-400">
          {truncate(block.content, 100)}
        </pre>
      </div>
    );
  }

  return null;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "...";
}
