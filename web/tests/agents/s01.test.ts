import { describe, it, expect, vi, beforeEach } from "vitest";
import { AgentLoopAgent } from "@/agents/s01";

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

// Messages array is passed by reference, so after run() completes it includes
// the final assistant response. Tool results are always at msgs.length - 2.
function lastToolResult(msgs: any[]): any {
  // Walk backwards to find the last user message with tool_result content
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === "user" && Array.isArray(msgs[i].content)) {
      const blocks = msgs[i].content;
      if (blocks.length > 0 && blocks[0].type === "tool_result") {
        return blocks[0];
      }
    }
  }
  return undefined;
}

describe("s01 - AgentLoopAgent", () => {
  let agent: AgentLoopAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new AgentLoopAgent({ apiKey: "test-key", maxIterations: 5 });
  });

  it("loop terminates on end_turn", async () => {
    mockCreate.mockResolvedValueOnce(mockResponse({ text: "Done." }));
    const result = await agent.run("Hello");
    expect(result).toBe("Done.");
    expect(mockCreate).toHaveBeenCalledTimes(1);
  });

  it("loop continues on tool_use", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "bash", input: { command: "ls" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Files listed." }));

    const result = await agent.run("List files");
    expect(result).toBe("Files listed.");
    expect(mockCreate).toHaveBeenCalledTimes(2);
  });

  it("bash tool executes commands via VirtualFS", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "bash", input: { command: "ls" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "OK" }));

    await agent.run("List files");

    const state = agent.getState();
    // The messages include: user, assistant(tool_use), user(tool_result), assistant(text)
    const toolResultMsg = state.messages[2];
    expect(toolResultMsg.role).toBe("user");
    const blocks = toolResultMsg.content as any[];
    expect(blocks[0].type).toBe("tool_result");
    expect(blocks[0].tool_use_id).toBe("t1");
    expect(blocks[0].content).toContain("README.md");
  });

  it("max iterations respected", async () => {
    mockCreate.mockResolvedValue(
      mockResponse({
        toolCalls: [{ id: "t1", name: "bash", input: { command: "echo hi" } }],
      })
    );

    const result = await agent.run("Loop forever");
    expect(result).toBe("");
    expect(mockCreate).toHaveBeenCalledTimes(5);
  });

  it("abort() stops the loop", async () => {
    mockCreate.mockImplementation(async () => {
      agent.abort();
      return mockResponse({
        toolCalls: [{ id: "t1", name: "bash", input: { command: "ls" } }],
      });
    });

    const result = await agent.run("Abort test");
    expect(result).toBe("");
    expect(mockCreate).toHaveBeenCalledTimes(1);
  });
});
