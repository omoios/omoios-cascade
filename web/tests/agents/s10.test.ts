import { describe, it, expect, vi, beforeEach } from "vitest";
import { TeamProtocolsAgent } from "@/agents/s10";

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

describe("s10 - TeamProtocolsAgent", () => {
  let agent: TeamProtocolsAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new TeamProtocolsAgent({ apiKey: "test-key", maxIterations: 10 });
  });

  it("shutdown request sent with request_id", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "worker1", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "shutdown_request",
            input: { target: "worker1" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Shutdown worker1");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    const parsed = JSON.parse(result.content);
    expect(parsed.requestId).toBe("req_1");
    expect(parsed.target).toBe("worker1");
    expect(parsed.status).toBe("pending");
  });

  it("shutdown response approve", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "worker1", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "shutdown_request",
            input: { target: "worker1" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "shutdown_response",
            input: { request_id: "req_1", approve: true },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Approve shutdown");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    const parsed = JSON.parse(result.content);
    expect(parsed.requestId).toBe("req_1");
    expect(parsed.status).toBe("approved");
  });

  it("shutdown response reject", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "worker1", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "shutdown_request",
            input: { target: "worker1" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "shutdown_response",
            input: { request_id: "req_1", approve: false },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Reject shutdown");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    const parsed = JSON.parse(result.content);
    expect(parsed.requestId).toBe("req_1");
    expect(parsed.status).toBe("rejected");
  });

  it("request_id correlates", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "spawn_teammate", input: { name: "a", role: "x" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "spawn_teammate", input: { name: "b", role: "y" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "shutdown_request",
            input: { target: "a" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t4", name: "shutdown_request",
            input: { target: "b" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Two shutdown requests");

    const result3 = findToolResultBlock(agent.getState().messages, "t3");
    const parsed3 = JSON.parse(result3.content);
    expect(parsed3.requestId).toBe("req_1");

    const result4 = findToolResultBlock(agent.getState().messages, "t4");
    const parsed4 = JSON.parse(result4.content);
    expect(parsed4.requestId).toBe("req_2");

    expect(parsed3.requestId).not.toBe(parsed4.requestId);
  });

  it("plan submitted", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "plan_approval",
            input: { from: "alice", plan: "Refactor the auth module" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Submit plan");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    const parsed = JSON.parse(result.content);
    expect(parsed.requestId).toBe("req_1");
    expect(parsed.status).toBe("pending");
  });

  it("plan approved", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "plan_approval",
            input: { from: "bob", plan: "Add caching layer" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "plan_approval",
            input: { from: "bob", request_id: "req_1", approve: true },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Approve plan");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    const parsed = JSON.parse(result.content);
    expect(parsed.requestId).toBe("req_1");
    expect(parsed.status).toBe("approved");
  });

  it("plan rejected with feedback", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t0", name: "spawn_teammate",
            input: { name: "carol", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "plan_approval",
            input: { from: "carol", plan: "Rewrite everything" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "plan_approval",
            input: { from: "carol", request_id: "req_1", approve: false, feedback: "Too risky" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "read_inbox",
            input: { name: "carol" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Reject plan");

    const rejectionResult = findToolResultBlock(agent.getState().messages, "t2");
    const parsed = JSON.parse(rejectionResult.content);
    expect(parsed.requestId).toBe("req_1");
    expect(parsed.status).toBe("rejected");

    const inboxResult = findToolResultBlock(agent.getState().messages, "t3");
    const inboxMsgs = JSON.parse(inboxResult.content);
    expect(inboxMsgs[0].type).toBe("plan_approval_response");
    expect(inboxMsgs[0].content).toContain("rejected");
    expect(inboxMsgs[0].content).toContain("Too risky");
  });

  it("plan request_id correlates", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "plan_approval",
            input: { from: "dev1", plan: "Plan A" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "plan_approval",
            input: { from: "dev2", plan: "Plan B" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Two plans");

    const result1 = findToolResultBlock(agent.getState().messages, "t1");
    const parsed1 = JSON.parse(result1.content);

    const result2 = findToolResultBlock(agent.getState().messages, "t2");
    const parsed2 = JSON.parse(result2.content);

    expect(parsed1.requestId).toBe("req_1");
    expect(parsed2.requestId).toBe("req_2");
    expect(parsed1.requestId).not.toBe(parsed2.requestId);
  });

  it("state includes protocolState", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "worker", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "shutdown_request",
            input: { target: "worker" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Check protocol state");

    const state = agent.getState();
    expect(state.protocolState).toBeDefined();
    expect(state.protocolState!.shutdownRequests).toHaveLength(1);
    expect(state.protocolState!.shutdownRequests[0].id).toBe("req_1");
    expect(state.protocolState!.shutdownRequests[0].target).toBe("worker");
    expect(state.protocolState!.shutdownRequests[0].status).toBe("pending");
  });

  it("teammate status updates on shutdown approval", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "worker", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "shutdown_request",
            input: { target: "worker" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "shutdown_response",
            input: { request_id: "req_1", approve: true },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Shutdown with approval");

    const state = agent.getState();
    const worker = state.teammates!.find((t) => t.name === "worker");
    expect(worker).toBeDefined();
    expect(worker!.status).toBe("shutdown");
  });

  it("state includes plan approvals", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "plan_approval",
            input: { from: "engineer", plan: "Optimize queries" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Check state");

    const state = agent.getState();
    expect(state.protocolState).toBeDefined();
    expect(state.protocolState!.planApprovals).toHaveLength(1);
    expect(state.protocolState!.planApprovals[0].id).toBe("req_1");
    expect(state.protocolState!.planApprovals[0].from).toBe("engineer");
    expect(state.protocolState!.planApprovals[0].status).toBe("pending");
  });
});
