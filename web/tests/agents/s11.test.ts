import { describe, it, expect, vi, beforeEach } from "vitest";
import { AutonomousAgent } from "@/agents/s11";

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

describe("s11 - AutonomousAgent", () => {
  let agent: AutonomousAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new AutonomousAgent({
      apiKey: "test-key",
      maxIterations: 5,
      maxIdleCycles: 3,
      agentName: "auto-agent",
    });
  });

  it("idle phase entered after idle tool call", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "idle", input: {} }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Going idle." }));

    await agent.run("Start working");

    const state = agent.getState();
    expect(state.idleCycle).toBeDefined();
    expect(state.idleCycle!.pollCount).toBe(3);
  });

  it("task auto-claimed from board", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "create_task", input: { subject: "Auto-claimable task" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t2", name: "idle", input: {} }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Going idle now." }))
      .mockResolvedValueOnce(mockResponse({ text: "Task completed." }));

    await agent.run("Create and idle");

    const state = agent.getState();
    expect(state.idleCycle!.claimedTask).toBe("1");
    expect(state.idleCycle!.isIdle).toBe(false);
  });

  it("claimed task marked in_progress", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "create_task", input: { subject: "Claim me" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t2", name: "idle", input: {} }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Idling." }))
      .mockResolvedValueOnce(mockResponse({ text: "Working on claimed task." }));

    await agent.run("Claim test");

    const state = agent.getState();
    const task = state.tasks!.find((t) => t.id === "1");
    expect(task).toBeDefined();
    expect(task!.status).toBe("in_progress");
  });

  it("blocked tasks not claimed", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "create_task", input: { subject: "Task A" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "claim_task", input: { task_id: "1" } },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Claim then check blocked");

    const claimResult = findToolResultBlock(agent.getState().messages, "t2");
    const parsed = JSON.parse(claimResult.content);
    expect(parsed.status).toBe("in_progress");
    expect(parsed.owner).toBe("auto-agent");
  });

  it("idle timeout (no tasks to claim)", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "idle", input: {} }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Going idle." }));

    await agent.run("Idle with nothing");

    const state = agent.getState();
    expect(state.idleCycle!.pollCount).toBe(3);
    expect(state.idleCycle!.isIdle).toBe(true);
    expect(state.idleCycle!.claimedTask).toBeUndefined();
  });

  it("claim_task tool works", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "create_task", input: { subject: "Manual claim" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "claim_task", input: { task_id: "1" } },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Manual claim");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    const parsed = JSON.parse(result.content);
    expect(parsed.id).toBe("1");
    expect(parsed.status).toBe("in_progress");
    expect(parsed.owner).toBe("auto-agent");
  });

  it("idle tool works", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "idle", input: {} }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Idle entered." }));

    await agent.run("Enter idle");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result).toBeDefined();
    expect(result.content).toContain("idle");
  });

  it("state includes idleCycle", () => {
    const state = agent.getState();
    expect(state.idleCycle).toBeDefined();
    expect(state.idleCycle!.isIdle).toBe(false);
    expect(state.idleCycle!.pollCount).toBe(0);
    expect(state.idleCycle!.lastPollTime).toBe(0);
  });
});
