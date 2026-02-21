import { describe, it, expect, vi, beforeEach } from "vitest";
import { OptimisticMergeAgent } from "@/agents/s16";

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

describe("s16 - OptimisticMergeAgent", () => {
  let agent: OptimisticMergeAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new OptimisticMergeAgent({
      apiKey: "test-key",
      maxIterations: 6,
      plannerName: "planner",
    });
  });

  it("exposes optimistic merge and fix-forward planner tools", () => {
    const plannerTools = agent.getTools().map((t) => t.name);
    expect(plannerTools).toContain("spawn_worker");
    expect(plannerTools).toContain("optimistic_merge");
    expect(plannerTools).toContain("list_fix_tasks");
    expect(plannerTools).toContain("read_merge_log");
    expect(plannerTools).not.toContain("write_file");
    expect(plannerTools).not.toContain("edit_file");
  });

  it("applies clean optimistic merge for single worker handoff", async () => {
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
                task: "Create src/app.py and submit handoff",
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
              input: { path: "src/app.py", content: "print('hello from worker a')\n" },
            },
            {
              id: "w2",
              name: "submit_handoff",
              input: { status: "Success", narrative: "worker-a completed" },
            },
          ],
        })
      )
      // planner call: merge
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "p2",
              name: "optimistic_merge",
              input: { agent_id: "worker-a" },
            },
          ],
        })
      )
      // planner end
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("delegate and merge");

    const state = agent.getState() as any;
    expect(state.handoffs.length).toBe(1);
    const handoff = state.handoffs[0];
    expect(handoff.merged).toBe(true);
    expect(handoff.merge_status).toBe("Applied");

    const fs = (agent as any).toolExecutor.fs;
    expect(fs.getFile("src/app.py")).toContain("hello from worker a");

    expect(state.fixForwardTasks ?? []).toHaveLength(0);
    expect((state.mergeLog ?? []).length).toBeGreaterThan(0);
    expect(state.mergeLog[state.mergeLog.length - 1].status).toBe("Applied");
  });

  it("creates fix-forward task on 3-way conflict and does not revert", async () => {
    mockCreate
      // planner call: spawn two workers with same target file
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "p1",
              name: "spawn_worker",
              input: {
                name: "worker-a",
                task: "Write src/conflict.txt as A and submit",
                task_id: "t-a",
              },
            },
            {
              id: "p2",
              name: "spawn_worker",
              input: {
                name: "worker-b",
                task: "Write src/conflict.txt as B and submit",
                task_id: "t-b",
              },
            },
          ],
        })
      )
      // worker-a call
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "wa1",
              name: "write_file",
              input: { path: "src/conflict.txt", content: "version-A\n" },
            },
            {
              id: "wa2",
              name: "submit_handoff",
              input: { status: "Success", narrative: "A done" },
            },
          ],
        })
      )
      // worker-b call
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "wb1",
              name: "write_file",
              input: { path: "src/conflict.txt", content: "version-B\n" },
            },
            {
              id: "wb2",
              name: "submit_handoff",
              input: { status: "Success", narrative: "B done" },
            },
          ],
        })
      )
      // planner call: merge worker-b first (clean), then worker-a (conflict)
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "p3",
              name: "optimistic_merge",
              input: { agent_id: "worker-b" },
            },
            {
              id: "p4",
              name: "optimistic_merge",
              input: { agent_id: "worker-a" },
            },
          ],
        })
      )
      // planner end
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("run optimistic merge flow");

    const state = agent.getState() as any;

    expect(state.handoffs.length).toBe(2);
    const conflictHandoff = state.handoffs.find((h: any) => h.agent_id === "worker-a");
    expect(conflictHandoff?.merged).toBe(true);
    expect(conflictHandoff?.merge_status).toBe("Conflict");

    expect((state.fixForwardTasks ?? []).length).toBe(1);
    const fixTask = state.fixForwardTasks[0];
    expect(fixTask.status).toBe("pending");
    expect(fixTask.description).toContain("DO NOT REVERT");

    const mergeLog = state.mergeLog as Array<any>;
    expect(mergeLog.length).toBeGreaterThanOrEqual(2);
    expect(mergeLog.some((m) => m.status === "Conflict")).toBe(true);

    const fs = (agent as any).toolExecutor.fs;
    // worker-b merge remains applied even after worker-a conflict (fix-forward, no revert)
    expect(fs.getFile("src/conflict.txt")).toContain("version-B");
  });
});
