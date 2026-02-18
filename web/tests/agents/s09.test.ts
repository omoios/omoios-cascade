import { describe, it, expect, vi, beforeEach } from "vitest";
import { TeamMessagingAgent } from "@/agents/s09";

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

describe("s09 - TeamMessagingAgent", () => {
  let agent: TeamMessagingAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new TeamMessagingAgent({ apiKey: "test-key", maxIterations: 10 });
  });

  it("spawn creates teammate", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "alice", role: "backend developer" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Create alice");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    const parsed = JSON.parse(result.content);
    expect(parsed.name).toBe("alice");
    expect(parsed.status).toBe("idle");
  });

  it("teammate status lifecycle", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "carol", role: "designer" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Create carol");

    const state = agent.getState();
    expect(state.teammates).toBeDefined();
    const carol = state.teammates!.find((t) => t.name === "carol");
    expect(carol).toBeDefined();
    expect(carol!.status).toBe("idle");
  });

  it("config stored in VFS", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "dave", role: "ops" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "read_file",
            input: { file_path: ".team/config.json" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Create and read config");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    const config = JSON.parse(result.content);
    expect(config.members).toBeDefined();
    expect(config.members.length).toBe(1);
    expect(config.members[0].name).toBe("dave");
  });

  it("message sent to inbox file", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "alice", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "send_message",
            input: { to: "alice", content: "Hello alice!" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Send message");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    expect(result.content).toContain("Message sent to alice");
  });

  it("read inbox drains messages", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "bob", role: "qa" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "send_message",
            input: { to: "bob", content: "Check this" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "read_inbox",
            input: { name: "bob" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t4", name: "read_inbox",
            input: { name: "bob" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Send and drain");

    const firstResult = findToolResultBlock(agent.getState().messages, "t3");
    expect(firstResult.content).toContain("Check this");

    const secondResult = findToolResultBlock(agent.getState().messages, "t4");
    expect(secondResult.content).toContain("empty");
  });

  it("broadcast sends to all", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "spawn_teammate", input: { name: "x", role: "a" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "spawn_teammate", input: { name: "y", role: "b" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "broadcast",
            input: { content: "Team announcement" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Broadcast test");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    expect(result.content).toContain("Broadcast sent to 2 teammates");
  });

  it("5 message types accepted", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "agent1", role: "worker" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "send_message",
            input: { to: "agent1", content: "test", type: "shutdown_request" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "read_inbox",
            input: { name: "agent1" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Typed message");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    const parsed = JSON.parse(result.content);
    expect(parsed[0].type).toBe("shutdown_request");
  });

  it("empty inbox returns empty", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "read_inbox",
            input: { name: "nobody" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Read empty");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result.content).toContain("empty");
  });

  it("JSONL format correct", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "carol", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "send_message", input: { to: "carol", content: "First" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t3", name: "send_message", input: { to: "carol", content: "Second" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t4", name: "read_inbox",
            input: { name: "carol" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("JSONL test");

    const result = findToolResultBlock(agent.getState().messages, "t4");
    const parsed = JSON.parse(result.content);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed.length).toBe(2);
    expect(parsed[0].content).toBe("First");
    expect(parsed[1].content).toBe("Second");
  });

  it("state includes teammates AND inbox", () => {
    const state = agent.getState();
    expect(state.teammates).toBeDefined();
    expect(state.inbox).toBeDefined();
    expect(state.inbox).toEqual([]);
  });

  it("message has timestamp", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "dave", role: "dev" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "send_message",
            input: { to: "dave", content: "Timestamp check" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "read_inbox",
            input: { name: "dave" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Check timestamp");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    const parsed = JSON.parse(result.content);
    expect(parsed[0].timestamp).toBeDefined();
    expect(typeof parsed[0].timestamp).toBe("number");
    expect(parsed[0].timestamp).toBeGreaterThan(0);
  });

  it("list_teammates works", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "eve", role: "analyst" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "spawn_teammate",
            input: { name: "frank", role: "tester" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "list_teammates",
            input: {},
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("List team");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    expect(result.content).toContain("eve");
    expect(result.content).toContain("frank");
    expect(result.content).toContain("idle");
  });

  it("duplicate name handled", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "bob", role: "tester" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "spawn_teammate",
            input: { name: "bob", role: "frontend" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Duplicate spawn");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    expect(result.content).toContain("Error");
    expect(result.content).toContain("already exists");
  });

  it("spawn with role shows in state", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "spawn_teammate",
            input: { name: "henry", role: "security expert" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Create specialist");

    const state = agent.getState();
    expect(state.teammates![0].currentTask).toBe("security expert");
  });
});
