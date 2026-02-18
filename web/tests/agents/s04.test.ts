import { describe, it, expect, vi, beforeEach } from "vitest";
import { SubagentAgent } from "@/agents/s04";

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

describe("s04 - SubagentAgent", () => {
  let agent: SubagentAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new SubagentAgent({ apiKey: "test-key", maxIterations: 5 });
  });

  it("subagent gets fresh messages", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task",
            input: { description: "Test task", prompt: "Do something" },
          }],
        })
      )
      // Child LLM call
      .mockResolvedValueOnce(mockResponse({ text: "Subagent done." }))
      // Parent continues
      .mockResolvedValueOnce(mockResponse({ text: "All done." }));

    await agent.run("Delegate work");

    // The child call (second createMessage call) should have a fresh set of messages
    // with only the prompt as user message
    const childCall = mockCreate.mock.calls[1][0];
    expect(childCall.messages[0].role).toBe("user");
    expect(childCall.messages[0].content).toBe("Do something");
    // The child system prompt is different from the parent's
    expect(childCall.system).toContain("focused subagent");
  });

  it("subagent result is summary only", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task",
            input: { description: "Explore files", prompt: "List all files" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Found 3 files." }))
      .mockResolvedValueOnce(mockResponse({ text: "Parent done." }));

    await agent.run("Check files");

    // The task tool result in parent should contain only the child's text summary
    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result).toBeDefined();
    expect(result.content).toBe("Found 3 files.");
  });

  it("parent context unchanged after subagent", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task",
            input: { description: "Sub work", prompt: "Do sub work" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Sub result." }))
      .mockResolvedValueOnce(mockResponse({ text: "Parent result." }));

    await agent.run("Main task");

    const msgs = agent.getState().messages;
    // Parent messages: user, assistant(task tool_use), user(tool_result), assistant(end_turn)
    expect(msgs[0].role).toBe("user");
    expect(msgs[0].content).toBe("Main task");
    expect(msgs).toHaveLength(4);
  });

  it("subagent tool execution works", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task",
            input: { description: "File ops", prompt: "Write a file" },
          }],
        })
      )
      // Child uses bash tool, then returns
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "ct1", name: "bash", input: { command: "ls" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Child used tools and done." }))
      // Parent continues
      .mockResolvedValueOnce(mockResponse({ text: "Parent done." }));

    await agent.run("Delegate file ops");

    expect(mockCreate).toHaveBeenCalledTimes(4);
    const state = agent.getState();
    expect(state.subagentContexts).toHaveLength(1);
    // Child messages: [user:prompt, assistant:tool_use, user:tool_result, assistant:text] = 4
    expect(state.subagentContexts![0].messageCount).toBe(4);
  });

  it("state includes subagent contexts", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task",
            input: { description: "First sub", prompt: "Do first" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "First done." }))
      .mockResolvedValueOnce(mockResponse({ text: "All done." }));

    await agent.run("Delegate");

    const state = agent.getState();
    expect(state.subagentContexts).toBeDefined();
    expect(state.subagentContexts!.length).toBeGreaterThanOrEqual(1);
    expect(state.subagentContexts![0].name).toBe("First sub");
    expect(state.subagentContexts![0].messageCount).toBeGreaterThan(0);
  });

  it("subagent respects max iterations (5 child iterations)", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task",
            input: { description: "Looping sub", prompt: "Loop forever" },
          }],
        })
      );

    // 5 child iterations that all return tool_use
    for (let i = 0; i < 5; i++) {
      mockCreate.mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: `ct${i}`, name: "bash", input: { command: "echo loop" } }],
        })
      );
    }
    // Parent continues after child finishes
    mockCreate.mockResolvedValueOnce(mockResponse({ text: "Parent done." }));

    await agent.run("Test child limit");

    // 1 parent + 5 child + 1 parent = 7
    expect(mockCreate).toHaveBeenCalledTimes(7);
  });
});
