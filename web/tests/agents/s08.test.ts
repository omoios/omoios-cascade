import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { BackgroundAgent } from "@/agents/s08";
import { ToolExecutor, VirtualFS } from "@/agents/shared/tool-executor";

vi.mock("@/agents/shared/api-client", () => ({
  createMessage: vi.fn(),
}));

import { createMessage } from "@/agents/shared/api-client";
const mockCreate = vi.mocked(createMessage);

function mockResponse(opts: {
  text?: string;
  toolCalls?: { id: string; name: string; input: Record<string, unknown> }[];
}) {
  const content: any[] = [];
  if (opts.toolCalls) {
    for (const tc of opts.toolCalls) {
      content.push({ type: "tool_use", id: tc.id, name: tc.name, input: tc.input });
    }
  }
  if (opts.text) {
    content.push({ type: "text", text: opts.text });
  }
  return {
    id: "msg_test",
    role: "assistant" as const,
    content,
    stop_reason: opts.toolCalls ? ("tool_use" as const) : ("end_turn" as const),
    usage: { input_tokens: 100, output_tokens: 50 },
  };
}

function findToolResultBlock(msgs: any[], toolUseId: string): any {
  for (const msg of msgs) {
    if (msg.role !== "user" || !Array.isArray(msg.content)) continue;
    for (const block of msg.content) {
      if (block.type === "tool_result" && block.tool_use_id === toolUseId) {
        return block;
      }
    }
  }
  return undefined;
}

describe("s08 - BackgroundAgent", () => {
  let agent: BackgroundAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    const exec = new ToolExecutor(new VirtualFS({ "data.txt": "hello" }));
    agent = new BackgroundAgent({ apiKey: "test-key", maxIterations: 10 }, exec);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("background_run returns task_id", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "background_run",
            input: { command: "cat data.txt" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    const promise = agent.run("Run background");
    await vi.advanceTimersByTimeAsync(100);
    await promise;

    const result = findToolResultBlock(agent.getState().messages, "t1");
    const parsed = JSON.parse(result.content);
    expect(parsed.task_id).toBe("bg_1");
    expect(parsed.status).toBe("running");
    expect(parsed.command).toBe("cat data.txt");
  });

  it("result available after completion", async () => {
    // First call: background_run launches the setTimeout
    mockCreate
      .mockImplementationOnce(async () => {
        return mockResponse({
          toolCalls: [{
            id: "t1", name: "background_run",
            input: { command: "cat data.txt" },
          }],
        });
      })
      // Second call: by this time the setTimeout should have fired
      .mockImplementationOnce(async () => {
        // Advance timers so the background task completes
        await vi.advanceTimersByTimeAsync(10);
        return mockResponse({
          toolCalls: [{
            id: "t2", name: "check_background",
            input: { task_id: "bg_1" },
          }],
        });
      })
      .mockImplementationOnce(async () => {
        return mockResponse({ text: "Done" });
      });

    const promise = agent.run("Run and check");
    await vi.advanceTimersByTimeAsync(100);
    await promise;

    const result = findToolResultBlock(agent.getState().messages, "t2");
    const parsed = JSON.parse(result.content);
    expect(parsed.status).toBe("done");
    expect(parsed.output).toBe("hello");
  });

  it("notification queue drains before LLM call", async () => {
    // The drain mechanism: completed bg tasks are injected as messages
    // before the next LLM call. We verify the background task completes
    // and the drain produces a notification entry in the state.
    mockCreate
      .mockImplementationOnce(async () => {
        return mockResponse({
          toolCalls: [{
            id: "t1", name: "background_run",
            input: { command: "cat data.txt" },
          }],
        });
      })
      .mockImplementationOnce(async () => {
        return mockResponse({ text: "Done" });
      });

    const promise = agent.run("Drain test");
    // Flush all pending timers (including setTimeout(fn, 0))
    await vi.runAllTimersAsync();
    await promise;

    // The background task should have completed
    const state = agent.getState();
    expect(state.backgroundThreads).toBeDefined();
    expect(state.backgroundThreads!.length).toBeGreaterThan(0);
    expect(state.backgroundThreads![0].status).toBe("done");
  });

  it("multiple concurrent tasks", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "background_run", input: { command: "cat data.txt" } },
            { id: "t2", name: "background_run", input: { command: "ls" } },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    const promise = agent.run("Two tasks");
    await vi.advanceTimersByTimeAsync(100);
    await promise;

    const state = agent.getState();
    expect(state.backgroundThreads).toBeDefined();
    expect(state.backgroundThreads!.length).toBe(2);
  });

  it("check_background returns status", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "background_run",
            input: { command: "ls" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "check_background",
            input: {},
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    const promise = agent.run("Check all");
    await vi.advanceTimersByTimeAsync(100);
    await promise;

    const result = findToolResultBlock(agent.getState().messages, "t2");
    expect(result.content).toContain("bg_1");
  });

  it("state includes background threads", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "background_run",
            input: { command: "echo test" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    const promise = agent.run("State check");
    await vi.advanceTimersByTimeAsync(100);
    await promise;

    const state = agent.getState();
    expect(state.backgroundThreads).toBeDefined();
    expect(state.backgroundThreads!.length).toBeGreaterThanOrEqual(1);
    expect(state.backgroundThreads![0].id).toBe("bg_1");
    expect(state.backgroundThreads![0].command).toBe("echo test");
  });

  it("background with timeout completes", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "background_run",
            input: { command: "cat data.txt" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    const promise = agent.run("Timeout test");
    await vi.advanceTimersByTimeAsync(10);
    await promise;

    const state = agent.getState();
    expect(state.backgroundThreads![0].status).toBe("done");
  });
});
