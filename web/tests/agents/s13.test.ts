import { describe, it, expect, vi, beforeEach } from "vitest";
import { ScratchpadRewritingAgent } from "@/agents/s13";

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

describe("s13 - ScratchpadRewritingAgent", () => {
  let agent: ScratchpadRewritingAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new ScratchpadRewritingAgent({
      apiKey: "test-key",
      maxIterations: 6,
      agentName: "worker-a",
      leadName: "lead",
    });
  });

  it("rewrite_scratchpad replaces content instead of appending", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "t1",
              name: "rewrite_scratchpad",
              input: { content: "# Plan\n- First model" },
            },
            {
              id: "t2",
              name: "rewrite_scratchpad",
              input: { content: "# Plan\n- Second model" },
            },
            {
              id: "t3",
              name: "submit_handoff",
              input: { status: "Success", narrative: "done" },
            },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "Completed." }));

    await agent.run("Update your scratchpad twice");

    const fs = (agent as any).toolExecutor.fs;
    const scratchpad = fs.getFile(".scratchpad/worker-a.md");
    expect(scratchpad).toContain("Second model");
    expect(scratchpad).not.toContain("First model");
  });

  it("auto-summarizes at threshold and re-injects alignment", async () => {
    const seeded = Array.from({ length: 45 }, (_, i) => ({
      role: i % 2 === 0 ? "user" : "assistant",
      content: `seed-${i}`,
    }));
    (agent as any).messages = seeded;

    mockCreate
      // summarizeAndReset call
      .mockResolvedValueOnce(mockResponse({ text: "compressed conversation" }))
      // normal loop call
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "t1",
              name: "submit_handoff",
              input: { status: "Success", narrative: "summary-aware handoff" },
            },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("continue");

    const state = agent.getState() as any;
    expect(state.runtime.summaryCount).toBe(1);

    const messages = state.messages;
    const hasIdentity = messages.some(
      (m: any) => m.role === "user" && String(m.content).includes("<identity>")
    );
    const hasAlignment = messages.some(
      (m: any) => m.role === "user" && String(m.content).includes("<alignment>")
    );
    expect(hasIdentity).toBe(true);
    expect(hasAlignment).toBe(true);

    const fs = (agent as any).toolExecutor.fs;
    const scratchpad = fs.getFile(".scratchpad/worker-a.md") || "";
    expect(scratchpad).toContain("summary_count: 1");
  });

  it("injects self-reflection every 10 turns", async () => {
    (agent as any).runtime.turns = 10;

    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "t1",
              name: "submit_handoff",
              input: { status: "Success", narrative: "ok" },
            },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("keep working");

    const messages = (agent.getState() as any).messages;
    const reflection = messages.find(
      (m: any) =>
        m.role === "user" &&
        typeof m.content === "string" &&
        m.content.includes("making progress or going in circles")
    );
    expect(reflection).toBeDefined();
  });
});
