import { describe, it, expect, vi, beforeEach } from "vitest";
import { MultiToolAgent } from "@/agents/s02";

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

// Find the Nth tool_result user message (0-indexed) from agent state messages.
// Messages is a live reference, so we read from getState() after run() completes.
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

describe("s02 - MultiToolAgent", () => {
  let agent: MultiToolAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new MultiToolAgent({ apiKey: "test-key", maxIterations: 5 });
  });

  it("dispatch routes to bash", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "bash", input: { command: "ls" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Run ls");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result.type).toBe("tool_result");
    expect(result.content).toContain("README.md");
  });

  it("dispatch routes to read_file", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "read_file", input: { file_path: "README.md" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Read readme");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result.content).toContain("Project");
  });

  it("dispatch routes to write_file", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "write_file", input: { file_path: "test.txt", content: "hello world" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Create file");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result.content).toContain("test.txt");
  });

  it("dispatch routes to edit_file", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "edit_file", input: { file_path: "README.md", old_string: "Project", new_string: "MyProject" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Edit readme");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result.content).toContain("README.md");
  });

  it("unknown tool returns not-implemented message", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "unknown_thing", input: {} }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Try unknown");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result.content).toContain("not implemented");
  });

  it("read nonexistent file returns error", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "read_file", input: { file_path: "nonexistent.txt" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Read missing file");

    const result = findToolResultBlock(agent.getState().messages, "t1");
    expect(result.content).toContain("Error");
    expect(result.content).toContain("nonexistent.txt");
  });

  it("write creates file and read returns it", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t1", name: "write_file", input: { file_path: "new.txt", content: "data" } }],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t2", name: "read_file", input: { file_path: "new.txt" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Write then read");

    const result = findToolResultBlock(agent.getState().messages, "t2");
    expect(result.content).toBe("data");
  });

  it("edit replaces text in existing file", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t1", name: "write_file", input: { file_path: "code.ts", content: "const x = 1;" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            { id: "t2", name: "edit_file", input: { file_path: "code.ts", old_string: "x = 1", new_string: "x = 42" } },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [{ id: "t3", name: "read_file", input: { file_path: "code.ts" } }],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Done" }));

    await agent.run("Edit code");

    const result = findToolResultBlock(agent.getState().messages, "t3");
    expect(result.content).toBe("const x = 42;");
  });
});
