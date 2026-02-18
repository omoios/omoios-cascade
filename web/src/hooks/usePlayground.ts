"use client";

import { useState, useCallback, useRef } from "react";
import { VirtualFS } from "@/lib/virtual-fs";
import { parseSSEStream } from "@/lib/anthropic-stream";
import { getPlaygroundConfig } from "@/data/playground-configs";
import type { SimStep } from "@/types/agent-data";

interface Message {
  role: "user" | "assistant";
  content: string | ContentBlock[];
}

interface ContentBlock {
  type: "text" | "tool_use" | "tool_result";
  text?: string;
  id?: string;
  name?: string;
  input?: Record<string, string>;
  tool_use_id?: string;
  content?: string;
}

export function usePlayground(version: string, apiKey: string) {
  const [steps, setSteps] = useState<SimStep[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fsRef = useRef(new VirtualFS());
  const messagesRef = useRef<Message[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const addStep = useCallback((step: SimStep) => {
    setSteps((prev) => [...prev, step]);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setIsRunning(false);
  }, []);

  const reset = useCallback(() => {
    stop();
    setSteps([]);
    setError(null);
    messagesRef.current = [];
    fsRef.current = new VirtualFS();
  }, [stop]);

  const sendMessage = useCallback(
    async (userMessage: string) => {
      if (!apiKey || isRunning) return;

      setIsRunning(true);
      setError(null);

      addStep({
        type: "user_message",
        content: userMessage,
        annotation: "User input",
      });

      messagesRef.current.push({ role: "user", content: userMessage });

      const config = getPlaygroundConfig(version);
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        let loopCount = 0;
        const maxLoops = 10;

        while (loopCount < maxLoops) {
          loopCount++;

          const response = await fetch("https://api.anthropic.com/v1/messages", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "x-api-key": apiKey,
              "anthropic-version": "2023-06-01",
              "anthropic-dangerous-direct-browser-access": "true",
            },
            body: JSON.stringify({
              model: config.model,
              max_tokens: 4096,
              system: config.systemPrompt,
              messages: messagesRef.current,
              tools: config.tools,
              stream: true,
            }),
            signal: controller.signal,
          });

          if (!response.ok) {
            const errText = await response.text();
            throw new Error(`API error ${response.status}: ${errText}`);
          }

          const reader = response.body?.getReader();
          if (!reader) throw new Error("No response body");

          let currentText = "";
          let currentToolUseId = "";
          let currentToolName = "";
          let currentToolJson = "";
          let stopReason = "";
          const toolCalls: {
            id: string;
            name: string;
            input: Record<string, string>;
          }[] = [];

          for await (const event of parseSSEStream(reader)) {
            if (controller.signal.aborted) break;

            switch (event.type) {
              case "content_block_start":
                if (event.content_block?.type === "tool_use") {
                  currentToolUseId = event.content_block.id || "";
                  currentToolName = event.content_block.name || "";
                  currentToolJson = "";
                }
                break;

              case "content_block_delta":
                if (event.delta?.text) {
                  currentText += event.delta.text;
                  setSteps((prev) => {
                    const last = prev[prev.length - 1];
                    if (last?.type === "assistant_text") {
                      return [
                        ...prev.slice(0, -1),
                        { ...last, content: currentText },
                      ];
                    }
                    return [
                      ...prev,
                      {
                        type: "assistant_text" as const,
                        content: currentText,
                        annotation: "Streaming response",
                      },
                    ];
                  });
                }
                if (event.delta?.partial_json) {
                  currentToolJson += event.delta.partial_json;
                }
                break;

              case "content_block_stop":
                if (currentToolName) {
                  let parsedInput: Record<string, string> = {};
                  try {
                    parsedInput = JSON.parse(currentToolJson);
                  } catch {
                    parsedInput = { raw: currentToolJson };
                  }
                  toolCalls.push({
                    id: currentToolUseId,
                    name: currentToolName,
                    input: parsedInput,
                  });
                  addStep({
                    type: "tool_call",
                    content: JSON.stringify(parsedInput, null, 2),
                    toolName: currentToolName,
                    annotation: `Calling ${currentToolName}`,
                  });
                  currentToolName = "";
                  currentToolJson = "";
                  currentToolUseId = "";
                }
                break;

              case "message_delta":
                if (event.delta?.stop_reason) {
                  stopReason = event.delta.stop_reason;
                }
                break;
            }
          }

          const contentBlocks: ContentBlock[] = [];
          if (currentText) {
            contentBlocks.push({ type: "text", text: currentText });
          }
          for (const tc of toolCalls) {
            contentBlocks.push({
              type: "tool_use",
              id: tc.id,
              name: tc.name,
              input: tc.input,
            });
          }
          messagesRef.current.push({
            role: "assistant",
            content: contentBlocks,
          });
          currentText = "";

          if (stopReason !== "tool_use" || toolCalls.length === 0) {
            break;
          }

          const toolResults: ContentBlock[] = [];
          for (const tc of toolCalls) {
            const result = fsRef.current.executeTool(tc.name, tc.input);
            addStep({
              type: "tool_result",
              content: result || "(empty)",
              toolName: tc.name,
              annotation: `Result from ${tc.name}`,
            });
            toolResults.push({
              type: "tool_result",
              tool_use_id: tc.id,
              content: result,
            });
          }
          messagesRef.current.push({
            role: "user",
            content: toolResults,
          });
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return;
        const msg = err instanceof Error ? err.message : "Unknown error";
        setError(msg);
        addStep({
          type: "system_event",
          content: `Error: ${msg}`,
          annotation: "API call failed",
        });
      } finally {
        setIsRunning(false);
        abortRef.current = null;
      }
    },
    [apiKey, version, isRunning, addStep]
  );

  return {
    steps,
    isRunning,
    error,
    files: fsRef.current.listFiles(),
    sendMessage,
    stop,
    reset,
  };
}
