import { describe, it, expect, vi, beforeEach } from "vitest";
import { PlannerWorkerSplitAgent } from "@/agents/s14";

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
    usage: { input_tokens: 120, output_tokens: 60 },
  };
}

describe("s14 - PlannerWorkerSplitAgent", () => {
  let agent: PlannerWorkerSplitAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new PlannerWorkerSplitAgent({
      apiKey: "test-key",
      maxIterations: 4,
      plannerName: "planner",
    });
  });

  it("planner tool surface excludes bash/write/edit while worker excludes spawn", () => {
    const plannerTools = agent.getTools().map((t) => t.name);
    expect(plannerTools).toContain("spawn_worker");
    expect(plannerTools).toContain("review_handoff");
    expect(plannerTools).not.toContain("bash");
    expect(plannerTools).not.toContain("write_file");
    expect(plannerTools).not.toContain("edit_file");

    const workerTools = ((agent as any).getWorkerTools() as Array<{ name: string }>).map(
      (t) => t.name
    );
    expect(workerTools).toContain("bash");
    expect(workerTools).toContain("write_file");
    expect(workerTools).toContain("submit_handoff");
    expect(workerTools).not.toContain("spawn_worker");
  });

  it("spawn_worker runs worker with fresh worker system prompt and submits handoff", async () => {
    mockCreate
      // planner call: spawn worker
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "p1",
              name: "spawn_worker",
              input: {
                name: "worker-a",
                task: "Create src/app.py with hello output and submit handoff",
                task_id: "t-1",
              },
            },
          ],
        })
      )
      // worker call
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "w1",
              name: "write_file",
              input: { path: "src/app.py", content: "print('hello')\n" },
            },
            {
              id: "w2",
              name: "submit_handoff",
              input: { status: "Success", narrative: "implemented app.py" },
            },
          ],
        })
      )
      // planner follow-up end
      .mockResolvedValueOnce(mockResponse({ text: "delegation complete" }));

    await agent.run("Decompose and delegate");

    const state = agent.getState() as any;
    expect(state.handoffs.length).toBe(1);
    expect(state.handoffs[0].agent_id).toBe("worker-a");
    expect(state.handoffs[0].status).toBe("Success");

    const fs = (agent as any).toolExecutor.fs;
    expect(fs.getFile("src/app.py")).toContain("hello");

    const workerScratch = fs.getFile(".scratchpad/worker-a.md") || "";
    expect(workerScratch).toContain("I execute tasks and submit handoff");

    const plannerScratch = fs.getFile(".scratchpad/planner.md") || "";
    expect(plannerScratch).toContain("I NEVER write code");

    const workerCall = mockCreate.mock.calls[1][0];
    expect(String(workerCall.system)).toContain("WORKER 'worker-a'");
    expect(String(workerCall.system)).toContain("do NOT decompose or delegate");
  });

  it("review_handoff tool returns planner-readable handoff payload", async () => {
    mockCreate
      // planner call: spawn
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "p1",
              name: "spawn_worker",
              input: {
                name: "worker-b",
                task: "Write docs/notes.txt",
                task_id: "t-2",
              },
            },
          ],
        })
      )
      // worker call
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "w1",
              name: "write_file",
              input: { path: "docs/notes.txt", content: "notes\n" },
            },
            {
              id: "w2",
              name: "submit_handoff",
              input: { narrative: "worker notes done" },
            },
          ],
        })
      )
      // planner call: review handoff
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "p2",
              name: "review_handoff",
              input: { agent_id: "worker-b", include_diff: true },
            },
          ],
        })
      )
      // planner final
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("Delegate and inspect handoff");

    const msgs = (agent.getState() as any).messages;
    const serialized = JSON.stringify(msgs);
    expect(serialized).toContain("worker-b");
    expect(serialized).toContain("worker notes done");
    expect(serialized).toContain("docs/notes.txt");
  });
});
