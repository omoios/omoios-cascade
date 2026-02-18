/**
 * Anthropic API client for browser-side agent execution.
 *
 * Uses the Messages API with streaming SSE. Requires the
 * `anthropic-dangerous-direct-browser-access` header for
 * direct browser calls (no proxy needed).
 *
 *   Browser ──POST──> api.anthropic.com/v1/messages
 *              │
 *              ├── anthropic-dangerous-direct-browser-access: true
 *              ├── x-api-key: <user key>
 *              └── anthropic-version: 2023-06-01
 */

import type { Message, ToolDefinition, APIResponse, ContentBlock } from "./types";

const API_URL = "https://api.anthropic.com/v1/messages";
const API_VERSION = "2023-06-01";
const DEFAULT_MODEL = "claude-sonnet-4-20250514";
const MAX_TOKENS = 4096;

export interface CreateMessageParams {
  apiKey: string;
  model?: string;
  system?: string;
  messages: Message[];
  tools?: ToolDefinition[];
  maxTokens?: number;
}

/**
 * Non-streaming API call. Returns the full response at once.
 * Simpler for educational use -- students see one request/response cycle.
 */
export async function createMessage(params: CreateMessageParams): Promise<APIResponse> {
  const body: Record<string, unknown> = {
    model: params.model || DEFAULT_MODEL,
    max_tokens: params.maxTokens || MAX_TOKENS,
    messages: params.messages,
  };

  if (params.system) {
    body.system = params.system;
  }

  if (params.tools && params.tools.length > 0) {
    body.tools = params.tools;
  }

  const response = await fetch(API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": params.apiKey,
      "anthropic-version": API_VERSION,
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`API error ${response.status}: ${errorBody}`);
  }

  return response.json();
}

/**
 * Streaming API call. Yields content blocks as they arrive.
 * Used for real-time playground experience.
 */
export async function* streamMessage(
  params: CreateMessageParams
): AsyncGenerator<StreamEvent> {
  const body: Record<string, unknown> = {
    model: params.model || DEFAULT_MODEL,
    max_tokens: params.maxTokens || MAX_TOKENS,
    messages: params.messages,
    stream: true,
  };

  if (params.system) {
    body.system = params.system;
  }

  if (params.tools && params.tools.length > 0) {
    body.tools = params.tools;
  }

  const response = await fetch(API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": params.apiKey,
      "anthropic-version": API_VERSION,
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`API error ${response.status}: ${errorBody}`);
  }

  if (!response.body) {
    throw new Error("No response body for streaming");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // Accumulated state for building the final response
  let currentBlocks: ContentBlock[] = [];
  let currentBlockIndex = -1;
  let stopReason: string | null = null;
  let inputTokens = 0;
  let outputTokens = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;

        try {
          const event = JSON.parse(data);
          const streamEvent = processSSEEvent(
            event,
            currentBlocks,
            currentBlockIndex,
            stopReason,
            inputTokens,
            outputTokens
          );

          if (streamEvent) {
            // Update local tracking state
            if (event.type === "content_block_start") {
              currentBlockIndex = event.index;
              currentBlocks[currentBlockIndex] = event.content_block;
            } else if (event.type === "content_block_delta") {
              const block = currentBlocks[event.index];
              if (block?.type === "text" && event.delta?.type === "text_delta") {
                block.text += event.delta.text;
              } else if (block?.type === "tool_use" && event.delta?.type === "input_json_delta") {
                // Tool input arrives as JSON string fragments
                if (!("_partialInput" in block)) {
                  (block as unknown as Record<string, unknown>)._partialInput = "";
                }
                (block as unknown as Record<string, unknown>)._partialInput =
                  ((block as unknown as Record<string, unknown>)._partialInput as string) + event.delta.partial_json;
              }
            } else if (event.type === "content_block_stop") {
              const block = currentBlocks[event.index];
              if (block?.type === "tool_use" && "_partialInput" in block) {
                try {
                  block.input = JSON.parse((block as unknown as Record<string, unknown>)._partialInput as string);
                } catch {
                  block.input = {};
                }
                delete (block as unknown as Record<string, unknown>)._partialInput;
              }
            } else if (event.type === "message_delta") {
              stopReason = event.delta?.stop_reason || null;
              outputTokens += event.usage?.output_tokens || 0;
            } else if (event.type === "message_start") {
              inputTokens = event.message?.usage?.input_tokens || 0;
            }

            yield streamEvent;
          }
        } catch {
          // Skip malformed JSON
        }
      }
    }
  }

  // Yield final assembled response
  yield {
    type: "message_complete",
    response: {
      id: "",
      role: "assistant" as const,
      content: currentBlocks,
      stop_reason: (stopReason || "end_turn") as APIResponse["stop_reason"],
      usage: { input_tokens: inputTokens, output_tokens: outputTokens },
    },
  };
}

// -- Stream event types --

export type StreamEvent =
  | { type: "text_delta"; text: string }
  | { type: "tool_use_start"; id: string; name: string }
  | { type: "tool_input_delta"; partial_json: string }
  | { type: "content_block_stop"; index: number }
  | { type: "message_complete"; response: APIResponse }
  | { type: "usage_update"; inputTokens: number; outputTokens: number };

function processSSEEvent(
  event: Record<string, unknown>,
  _blocks: ContentBlock[],
  _blockIndex: number,
  _stopReason: string | null,
  inputTokens: number,
  outputTokens: number
): StreamEvent | null {
  switch (event.type) {
    case "content_block_start": {
      const block = event.content_block as ContentBlock;
      if (block.type === "tool_use") {
        return { type: "tool_use_start", id: block.id, name: block.name };
      }
      return null;
    }

    case "content_block_delta": {
      const delta = event.delta as Record<string, unknown>;
      if (delta.type === "text_delta") {
        return { type: "text_delta", text: delta.text as string };
      }
      if (delta.type === "input_json_delta") {
        return { type: "tool_input_delta", partial_json: delta.partial_json as string };
      }
      return null;
    }

    case "content_block_stop": {
      return { type: "content_block_stop", index: event.index as number };
    }

    case "message_start": {
      const msg = event.message as Record<string, unknown>;
      const usage = msg?.usage as Record<string, number>;
      if (usage) {
        return {
          type: "usage_update",
          inputTokens: usage.input_tokens || 0,
          outputTokens: 0,
        };
      }
      return null;
    }

    case "message_delta": {
      const usage = event.usage as Record<string, number>;
      return {
        type: "usage_update",
        inputTokens,
        outputTokens: outputTokens + (usage?.output_tokens || 0),
      };
    }

    default:
      return null;
  }
}
