/**
 * Core types for the TypeScript agent implementations.
 *
 * These types model the Anthropic Messages API and the internal
 * state that agents expose to the state inspector.
 *
 * Message flow:
 *
 *   User ──> messages[] ──> API ──> response
 *                                      │
 *                            stop_reason == "tool_use"?
 *                           /                          \
 *                         yes                           no
 *                          │                             │
 *                    execute tools                    return
 *                    append results
 *                    loop back ──────────────> messages[]
 */

// -- Anthropic API types (subset) --

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export type ContentBlock = TextBlock | ToolUseBlock;

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: string;
  is_error?: boolean;
}

export interface Message {
  role: "user" | "assistant";
  content: string | ContentBlock[] | ToolResultBlock[];
}

export interface ToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface APIResponse {
  id: string;
  role: "assistant";
  content: ContentBlock[];
  stop_reason: "end_turn" | "tool_use" | "max_tokens";
  usage: { input_tokens: number; output_tokens: number };
}

// -- Agent state types --

export interface TodoItem {
  id: string;
  text: string;
  done: boolean;
}

export interface TaskItem {
  id: string;
  subject: string;
  status: "pending" | "in_progress" | "completed";
  blockedBy: string[];
}

export interface TeammateInfo {
  name: string;
  status: "idle" | "working" | "shutdown";
  currentTask?: string;
}

export interface InboxMessage {
  type: "message" | "broadcast" | "shutdown_request" | "shutdown_response" | "plan_approval_response";
  from: string;
  content: string;
  timestamp: number;
}

export interface CompressionInfo {
  totalTokens: number;
  threshold: number;
  compressionCount: number;
  layers: {
    name: string;
    triggered: boolean;
    tokensBefore?: number;
    tokensAfter?: number;
  }[];
}

/**
 * AgentState is the union of all observable state that the
 * state inspector can display. Each session uses a subset.
 *
 *   s01-s02: messages, tools, loopIteration, stopReason
 *   s03:     + todos
 *   s04:     + subagentContexts
 *   s05:     + systemPromptParts
 *   s06:     + compression
 *   s07:     + tasks
 *   s08:     + backgroundThreads
 *   s09:     + teammates + inbox
 *   s10:     + protocolState (shutdownRequests + planApprovals)
 *   s11:     + idleCycle
 */
export interface AgentState {
  messages: Message[];
  tools: string[];
  loopIteration: number;
  stopReason: string | null;
  totalInputTokens: number;
  totalOutputTokens: number;

  // s03: Todo management
  todos?: TodoItem[];

  // s04: Subagent contexts
  subagentContexts?: { name: string; messageCount: number }[];

  // s05: System prompt assembly
  systemPromptParts?: { label: string; content: string }[];

  // s06: Compression
  compression?: CompressionInfo;

  // s07: Task management
  tasks?: TaskItem[];

  // s08: Background threads
  backgroundThreads?: { id: string; command: string; status: "running" | "done" }[];

  // s09: Team roster
  teammates?: TeammateInfo[];

  // s09: Inbox
  inbox?: InboxMessage[];

  // s10: Protocol state
  protocolState?: {
    shutdownRequests: { id: string; target: string; status: "pending" | "approved" | "rejected" }[];
    planApprovals: { id: string; from: string; status: "pending" | "approved" | "rejected" }[];
  };

  // s11: Idle cycle
  idleCycle?: {
    isIdle: boolean;
    pollCount: number;
    lastPollTime: number;
    claimedTask?: string;
  };
}

// -- Event system --

export type AgentEventType =
  | "state_change"
  | "llm_request"
  | "llm_response"
  | "tool_call"
  | "tool_result"
  | "error"
  | "done";

export interface AgentEvent {
  type: AgentEventType;
  timestamp: number;
  data: unknown;
}

export type AgentEventHandler = (event: AgentEvent) => void;

// -- Agent configuration --

export interface AgentConfig {
  apiKey: string;
  model?: string;
  maxIterations?: number;
  systemPrompt?: string;
  onEvent?: AgentEventHandler;
}
