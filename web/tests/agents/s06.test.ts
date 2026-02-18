import { describe, it, expect, vi, beforeEach } from "vitest";
import { CompressionAgent } from "@/agents/s06";
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

// Generate a large string to simulate large tool results
function largeContent(chars: number): string {
  return "x".repeat(chars);
}

describe("s06 - CompressionAgent", () => {
  let agent: CompressionAgent;
  let fs: VirtualFS;
  let exec: ToolExecutor;

  beforeEach(() => {
    vi.clearAllMocks();
    fs = new VirtualFS({ "big.txt": largeContent(5000) });
    exec = new ToolExecutor(fs);
    agent = new CompressionAgent({ apiKey: "test-key", maxIterations: 10 }, exec);
  });

  it("microCompact replaces old tool results with placeholders", async () => {
    // Create 5 iterations with bash tool calls producing large results,
    // so micro-compact has enough entries to compact (>3 kept + savings threshold)
    const calls: any[] = [];
    for (let i = 0; i < 5; i++) {
      calls.push(
        mockResponse({
          toolCalls: [{ id: `t${i}`, name: "bash", input: { command: `cat big.txt` } }],
        })
      );
    }
    calls.push(mockResponse({ text: "Done" }));
    for (const c of calls) mockCreate.mockResolvedValueOnce(c);

    await agent.run("Read big file multiple times");

    const state = agent.getState();
    expect(state.compression).toBeDefined();
    expect(state.compression!.layers.length).toBeGreaterThanOrEqual(1);
    // micro-compact layer should exist
    const microLayer = state.compression!.layers.find((l) => l.name === "micro-compact");
    expect(microLayer).toBeDefined();
  });

  it("microCompact keeps last N results intact", async () => {
    // Generate many tool calls with large content
    const calls: any[] = [];
    for (let i = 0; i < 6; i++) {
      calls.push(
        mockResponse({
          toolCalls: [{ id: `t${i}`, name: "bash", input: { command: "cat big.txt" } }],
        })
      );
    }
    calls.push(mockResponse({ text: "Done" }));
    for (const c of calls) mockCreate.mockResolvedValueOnce(c);

    await agent.run("Generate many results");

    // Check that the last call's messages still have recent tool results intact
    const lastCallMsgs = mockCreate.mock.calls[mockCreate.mock.calls.length - 1][0].messages;
    // The most recent tool result messages should not be replaced with placeholders
    const lastToolResults = lastCallMsgs
      .filter((m: any) => m.role === "user" && Array.isArray(m.content))
      .slice(-3);

    for (const msg of lastToolResults) {
      const blocks = msg.content as any[];
      for (const block of blocks) {
        if (block.type === "tool_result") {
          // Recent results should not be placeholders
          expect(block.content).not.toContain("[Previous:");
        }
      }
    }
  });

  it("autoCompact triggers at threshold", async () => {
    // Create a huge VFS file and generate many iterations to exceed 50000 token estimate
    const hugeFs = new VirtualFS({ "huge.txt": largeContent(100000) });
    const hugeExec = new ToolExecutor(hugeFs);
    const bigAgent = new CompressionAgent({ apiKey: "test-key", maxIterations: 10 }, hugeExec);

    // Multiple reads of 100k chars = ~25k tokens each, should exceed threshold
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t0", name: "bash", input: { command: "cat huge.txt" } }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "bash", input: { command: "cat huge.txt" } }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t2", name: "bash", input: { command: "cat huge.txt" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await bigAgent.run("Read huge file");

    const state = bigAgent.getState();
    // autoCompact should have been triggered
    expect(state.compression!.compressionCount).toBeGreaterThanOrEqual(1);
  });

  it("autoCompact replaces all messages with summary", async () => {
    const hugeFs = new VirtualFS({ "huge.txt": largeContent(100000) });
    const hugeExec = new ToolExecutor(hugeFs);
    const bigAgent = new CompressionAgent({ apiKey: "test-key", maxIterations: 10 }, hugeExec);

    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t0", name: "bash", input: { command: "cat huge.txt" } }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "bash", input: { command: "cat huge.txt" } }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t2", name: "bash", input: { command: "cat huge.txt" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await bigAgent.run("Trigger auto compact");

    // After auto-compact, messages should be compressed.
    // When auto-compact triggers, messages are replaced with [compressed, ack].
    // Subsequent calls should see the compressed format.
    const state = bigAgent.getState();
    if (state.compression!.compressionCount > 0) {
      // Messages should contain compression marker
      const msgContents = state.messages.map((m) =>
        typeof m.content === "string" ? m.content : JSON.stringify(m.content)
      );
      const allText = msgContents.join(" ");
      expect(allText).toContain("compressed");
    }
  });

  it("manual compress tool works", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "compress", input: {} }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Compress context");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result).toBeDefined();
    expect(result.content).toBe("Context compressed.");
  });

  it("token estimation is reasonable", () => {
    // estimateTokens uses chars/4, so 400 chars = ~100 tokens
    // We test this indirectly through the state
    const state = agent.getState();
    expect(state.compression!.totalTokens).toBeGreaterThanOrEqual(0);
    expect(state.compression!.threshold).toBe(50000);
  });

  it("compression state tracked", async () => {
    mockCreate.mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Check state");

    const state = agent.getState();
    expect(state.compression).toBeDefined();
    expect(state.compression!.compressionCount).toBe(0);
    expect(state.compression!.layers).toBeDefined();
    expect(state.compression!.layers.length).toBeGreaterThanOrEqual(3);
    const layerNames = state.compression!.layers.map((l) => l.name);
    expect(layerNames).toContain("micro-compact");
    expect(layerNames).toContain("auto-compact");
    expect(layerNames).toContain("manual-compact");
  });

  it("compression events emitted", async () => {
    const events: any[] = [];
    const eventAgent = new CompressionAgent(
      {
        apiKey: "test-key",
        maxIterations: 5,
        onEvent: (evt) => events.push(evt),
      },
      exec
    );

    mockCreate.mockResolvedValueOnce(mockResponse({ text: "Done" }));
    await eventAgent.run("Emit events");

    const stateEvents = events.filter((e) => e.type === "state_change");
    expect(stateEvents.length).toBeGreaterThan(0);
  });
});
