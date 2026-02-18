import { describe, it, expect, vi, beforeEach } from "vitest";
import { TodoAgent } from "@/agents/s03";

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

describe("s03 - TodoAgent", () => {
  let agent: TodoAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new TodoAgent({ apiKey: "test-key", maxIterations: 10 });
  });

  it("todo update stores items", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "todo", input: {
              items: [
                { content: "Write tests", status: "pending", activeForm: "Writing tests" },
                { content: "Review code", status: "in_progress", activeForm: "Reviewing code" },
              ],
            },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Plan work");
    const state = agent.getState();
    expect(state.todos).toBeDefined();
    expect(state.todos!.length).toBe(2);
    expect(state.todos![0].text).toBe("Write tests");
    expect(state.todos![1].text).toBe("Review code");
  });

  it("max 20 items enforced", async () => {
    const items = Array.from({ length: 21 }, (_, i) => ({
      content: `Task ${i}`, status: "pending", activeForm: `Doing task ${i}`,
    }));
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "todo", input: { items } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Too many todos");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result).toBeDefined();
    expect(result.is_error).toBe(true);
    expect(result.content).toContain("Max 20");
  });

  it("single in_progress enforced", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "todo", input: {
              items: [
                { content: "A", status: "in_progress", activeForm: "Doing A" },
                { content: "B", status: "in_progress", activeForm: "Doing B" },
              ],
            },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Two in_progress");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result).toBeDefined();
    expect(result.is_error).toBe(true);
    expect(result.content).toContain("one task can be in_progress");
  });

  it("nag reminder injected after 3 rounds without todo update", async () => {
    // First: set up some todos
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "todo", input: {
              items: [{ content: "Do stuff", status: "pending", activeForm: "Doing stuff" }],
            },
          }],
        })
      )
      // Rounds 2-4: use bash (no todo tool) to trigger nag at round 4
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t2", name: "bash", input: { command: "ls" } }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t3", name: "bash", input: { command: "ls" } }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t4", name: "bash", input: { command: "ls" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Do work");

    // After 3 rounds without todo, a nag reminder should have been injected
    // The reminder is appended to the last user message content
    const allMsgs = agent.getState().messages;
    const allContent = JSON.stringify(allMsgs);
    expect(allContent).toContain("reminder");
    expect(allContent).toContain("Please update todos");
  });

  it("nag NOT injected if todos recently updated", async () => {
    // Round 1: update todos
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "todo", input: {
              items: [{ content: "Task", status: "pending", activeForm: "Working" }],
            },
          }],
        })
      )
      // Round 2: use todo again (resets counter)
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "todo", input: {
              items: [{ content: "Task", status: "in_progress", activeForm: "Working" }],
            },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Keep updating");

    const allMsgs = agent.getState().messages;
    const allContent = JSON.stringify(allMsgs);
    expect(allContent).not.toContain("reminder");
  });

  it("render format correct", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "todo", input: {
              items: [
                { content: "First", status: "completed", activeForm: "Done" },
                { content: "Second", status: "in_progress", activeForm: "Working on second" },
                { content: "Third", status: "pending", activeForm: "Waiting" },
              ],
            },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Show format");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result).toBeDefined();
    expect(result.content).toContain("[x] First");
    expect(result.content).toContain("[>] Second");
    expect(result.content).toContain("[ ] Third");
    expect(result.content).toContain("1/3 completed");
  });

  it("agent state includes todos", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "todo", input: {
              items: [{ content: "Check state", status: "completed", activeForm: "Checking" }],
            },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Check state");

    const state = agent.getState();
    expect(state.todos).toHaveLength(1);
    expect(state.todos![0].done).toBe(true);
    expect(state.todos![0].id).toBe("todo-0");
  });

  it("empty todo list handled", async () => {
    mockCreate.mockResolvedValueOnce(mockResponse({ text: "Nothing to do." }));

    await agent.run("Hello");

    const state = agent.getState();
    expect(state.todos).toHaveLength(0);
  });
});
