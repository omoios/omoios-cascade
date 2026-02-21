import { describe, it, expect, vi, beforeEach } from "vitest";
import { StructuredHandoffsAgent } from "@/agents/s12";

vi.mock("@/agents/shared/api-client", () => ({ createMessage: vi.fn() }));

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
  if (opts.text) content.push({ type: "text", text: opts.text });

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
      if (block.type === "tool_result" && block.tool_use_id === toolUseId) return block;
    }
  }
  return undefined;
}

describe("s12 - StructuredHandoffsAgent", () => {
  let agent: StructuredHandoffsAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new StructuredHandoffsAgent({ apiKey: "test-key", maxIterations: 8, agentName: "worker-a", leadName: "lead" });
  });

  it("auto-creates handoff with diff, narrative, and metrics", async () => {
    mockCreate
      .mockResolvedValueOnce(mockResponse({ toolCalls: [{ id: "t1", name: "create_task", input: { subject: "Implement feature" } }] }))
      .mockResolvedValueOnce(mockResponse({ toolCalls: [
        { id: "t2", name: "claim_task", input: { task_id: "1" } },
        { id: "t3", name: "write_file", input: { path: "src/a.ts", content: "export const a = 1;" } },
      ] }))
      .mockResolvedValueOnce(mockResponse({ text: "Done." }))
      .mockResolvedValueOnce(mockResponse({ text: "Implemented src/a.ts and left no blockers. Next step: lead review." }));

    await agent.run("Do assigned work");

    const state = agent.getState() as any;
    expect(state.handoffs).toBeDefined();
    expect(state.handoffs.length).toBe(1);

    const h = state.handoffs[0];
    expect(h.agent_id).toBe("worker-a");
    expect(h.task_id).toBe("1");
    expect(["Success", "PartialFailure", "Failed", "Blocked"]).toContain(h.status);
    expect(h.diff["src/a.ts"]).toBeDefined();
    expect(typeof h.narrative).toBe("string");
    expect(h.narrative.length).toBeGreaterThan(0);
    expect(h.metrics).toMatchObject({ wall_time: expect.any(Number), tokens_used: expect.any(Number), attempts: expect.any(Number), files_modified: 1 });
  });

  it("submit_handoff sends structured payload to lead inbox", async () => {
    mockCreate
      .mockResolvedValueOnce(mockResponse({ toolCalls: [{ id: "t1", name: "create_task", input: { subject: "Task for handoff" } }] }))
      .mockResolvedValueOnce(mockResponse({ toolCalls: [
        { id: "t2", name: "claim_task", input: { task_id: "1" } },
        { id: "t3", name: "write_file", input: { path: "src/b.ts", content: "export const b = 2;" } },
        { id: "t4", name: "submit_handoff", input: { status: "Success" } },
      ] }))
      .mockResolvedValueOnce(mockResponse({ text: "Handoff narrative for lead." }))
      .mockResolvedValueOnce(mockResponse({ text: "Completed." }));

    await agent.run("Explicitly submit handoff");

    const submitResult = findToolResultBlock((agent.getState() as any).messages, "t4");
    expect(submitResult).toBeDefined();
    expect(submitResult.content).toContain("Submitted handoff");

    const fs = (agent as any).toolExecutor.fs;
    const inboxRaw = fs.getFile(".team/inbox/lead.jsonl");
    expect(inboxRaw).toBeDefined();
    const line = inboxRaw.trim().split("\n")[0];
    const parsed = JSON.parse(line);
    expect(parsed.type).toBe("handoff");
    expect(parsed.handoff.task_id).toBe("1");
    expect(parsed.handoff.diff["src/b.ts"]).toBeDefined();
  });

  it("review_handoff returns narrative summaries for lead", async () => {
    mockCreate
      .mockResolvedValueOnce(mockResponse({ toolCalls: [{ id: "t1", name: "create_task", input: { subject: "Task C" } }] }))
      .mockResolvedValueOnce(mockResponse({ toolCalls: [
        { id: "t2", name: "claim_task", input: { task_id: "1" } },
        { id: "t3", name: "write_file", input: { path: "src/c.ts", content: "export const c = 3;" } },
        { id: "t4", name: "submit_handoff", input: {} },
      ] }))
      .mockResolvedValueOnce(mockResponse({ text: "Changed src/c.ts. Risk: none. Next: review." }))
      .mockResolvedValueOnce(mockResponse({ toolCalls: [{ id: "t5", name: "review_handoff", input: { task_id: "1" } }] }))
      .mockResolvedValueOnce(mockResponse({ text: "Done." }));

    await agent.run("Submit then review");

    const reviewResult = findToolResultBlock((agent.getState() as any).messages, "t5");
    expect(reviewResult).toBeDefined();

    const parsed = JSON.parse(reviewResult.content);
    expect(parsed.length).toBe(1);
    expect(parsed[0].task_id).toBe("1");
    expect(typeof parsed[0].narrative).toBe("string");
    expect(parsed[0].narrative.length).toBeGreaterThan(0);
  });
});
