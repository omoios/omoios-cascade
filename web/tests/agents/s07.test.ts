import { describe, it, expect, vi, beforeEach } from "vitest";
import { TasksAgent } from "@/agents/s07";
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

describe("s07 - TasksAgent", () => {
  let agent: TasksAgent;
  let exec: ToolExecutor;

  beforeEach(() => {
    vi.clearAllMocks();
    exec = new ToolExecutor(new VirtualFS());
    agent = new TasksAgent({ apiKey: "test-key", maxIterations: 10 }, exec);
  });

  it("task create assigns ID", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task_create",
            input: { subject: "Build API", description: "Create REST endpoints" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Create a task");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    const parsed = JSON.parse(result.content);
    expect(parsed.id).toBe("1");
    expect(parsed.subject).toBe("Build API");
    expect(parsed.status).toBe("pending");
  });

  it("task get returns data", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task_create",
            input: { subject: "Setup DB", description: "Initialize database" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t2", name: "task_get", input: { id: "1" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Create then get");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    const parsed = JSON.parse(result.content);
    expect(parsed.id).toBe("1");
    expect(parsed.subject).toBe("Setup DB");
  });

  it("task update status works", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t1", name: "task_create",
            input: { subject: "Deploy", description: "Deploy to prod" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t2", name: "task_update",
            input: { id: "1", status: "in_progress" },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Update task status");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    const parsed = JSON.parse(result.content);
    expect(parsed.status).toBe("in_progress");
  });

  it("dependency graph: addBlocks/addBlockedBy", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "task_create", input: { subject: "Task A", description: "First" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "task_create", input: { subject: "Task B", description: "Second" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "task_update",
            input: { id: "2", blockedBy: ["1"] },
          }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Set up deps");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    const parsed = JSON.parse(result.content);
    expect(parsed.blockedBy).toContain("1");
  });

  it("completing task clears blocked_by in dependents", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "task_create", input: { subject: "Task A", description: "First" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "task_create", input: { subject: "Task B", description: "Second" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t3", name: "task_update",
            input: { id: "2", blockedBy: ["1"] },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{
            id: "t4", name: "task_update",
            input: { id: "1", status: "completed" },
          }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t5", name: "task_get", input: { id: "2" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Complete dep chain");

    const result = findToolResultBlock(agent.getState().messages, "t5");
    const parsed = JSON.parse(result.content);
    expect(parsed.blockedBy).toEqual([]);
  });

  it("task list returns all tasks", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "task_create", input: { subject: "First", description: "A" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "task_create", input: { subject: "Second", description: "B" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t3", name: "task_list", input: {} }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("List tasks");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    expect(result.content).toContain("#1");
    expect(result.content).toContain("First");
    expect(result.content).toContain("#2");
    expect(result.content).toContain("Second");
  });

  it("task get nonexistent returns error", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "task_get", input: { id: "999" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Get missing task");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result.content).toContain("Error");
    expect(result.content).toContain("999");
  });

  it("file persistence in VFS", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "task_create", input: { subject: "Persisted", description: "Check VFS" } },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Persist task");

    const stored = exec.fs.getFile(".tasks/1.json");
    expect(stored).toBeDefined();
    const parsed = JSON.parse(stored!);
    expect(parsed.subject).toBe("Persisted");
  });

  it("state includes tasks", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "task_create", input: { subject: "State check", description: "Verify" } },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Check state");

    const state = agent.getState();
    expect(state.tasks).toBeDefined();
    expect(state.tasks!.length).toBe(1);
    expect(state.tasks![0].subject).toBe("State check");
    expect(state.tasks![0].status).toBe("pending");
    expect(state.tasks![0].blockedBy).toEqual([]);
  });
});
