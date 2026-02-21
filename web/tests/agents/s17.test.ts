import { describe, it, expect, vi, beforeEach } from "vitest";

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

describe("s17 - RecursiveHierarchyAgent", () => {
  let agent: any;

  beforeEach(async () => {
    vi.clearAllMocks();
    const mod = await import("@/agents/s17");
    agent = new mod.RecursiveHierarchy({
      apiKey: "test-key",
      maxIterations: 8,
      rootName: "root",
    });
  });

  it("lets sub-planners spawn workers", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "r1",
              name: "spawn_sub_planner",
              input: {
                name: "sub-a",
                task: "Implement subsystem across src/a.ts src/b.ts src/c.ts",
                task_id: "sp-1",
              },
            },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "s1",
              name: "spawn_worker",
              input: {
                name: "worker-a",
                task: "Create src/a.ts and submit handoff",
                task_id: "w-1",
              },
            },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "w1",
              name: "write_file",
              input: { path: "src/a.ts", content: "export const A = 1;\n" },
            },
            {
              id: "w2",
              name: "submit_handoff",
              input: { status: "Success", narrative: "worker completed leaf task" },
            },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "s2",
              name: "submit_aggregate_handoff",
              input: { status: "Success", narrative: "sub planner aggregate" },
            },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("build recursively");

    const state = agent.getState() as any;
    const workerHandoff = (state.handoffs ?? []).find((h: any) => h.agent_id === "worker-a");
    const aggregateHandoff = (state.handoffs ?? []).find((h: any) => h.agent_id === "sub-a");

    expect(workerHandoff).toBeTruthy();
    expect(aggregateHandoff).toBeTruthy();
  });

  it("bubbles aggregate handoffs upward with child linkage", async () => {
    mockCreate
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "r1",
              name: "spawn_sub_planner",
              input: {
                name: "sub-b",
                task: "Complex scope across src/x.ts src/y.ts src/z.ts",
                task_id: "sp-2",
              },
            },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "s1",
              name: "spawn_worker",
              input: {
                name: "worker-b",
                task: "Create src/x.ts and submit",
                task_id: "w-2",
              },
            },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "w1",
              name: "write_file",
              input: { path: "src/x.ts", content: "export const X = 1;\n" },
            },
            {
              id: "w2",
              name: "submit_handoff",
              input: { status: "Success", narrative: "leaf complete" },
            },
          ],
        })
      )
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "s2",
              name: "submit_aggregate_handoff",
              input: { status: "Success", narrative: "aggregate complete" },
            },
          ],
        })
      )
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("run hierarchy");

    const state = agent.getState() as any;
    const workerHandoff = (state.handoffs ?? []).find((h: any) => h.agent_id === "worker-b");
    const aggregateHandoff = (state.handoffs ?? []).find((h: any) => h.agent_id === "sub-b");

    expect(workerHandoff).toBeTruthy();
    expect(aggregateHandoff).toBeTruthy();
    expect(aggregateHandoff.aggregated).toBe(true);
    expect(aggregateHandoff.parent_id).toBe("root");
    expect(aggregateHandoff.child_handoff_ids ?? []).toContain(workerHandoff.handoff_id);
  });

  it("enforces depth limit at spawn time", async () => {
    const spawnSubPlanner = (agent as any).spawnSubPlanner ?? (agent as any).spawn_sub_planner;
    expect(typeof spawnSubPlanner).toBe("function");

    const r1 = await spawnSubPlanner.call(agent, {
      parent_id: "root",
      name: "sub-l1",
      task: "complex task src/a.ts src/b.ts src/c.ts",
      task_id: "l1",
    });
    expect(String(r1)).toContain("Spawned");

    const r2 = await spawnSubPlanner.call(agent, {
      parent_id: "sub-l1",
      name: "sub-l2",
      task: "complex task src/d.ts src/e.ts src/f.ts",
      task_id: "l2",
    });
    expect(String(r2)).toContain("Spawned");

    const r3 = await spawnSubPlanner.call(agent, {
      parent_id: "sub-l2",
      name: "sub-l3",
      task: "complex task src/g.ts src/h.ts src/i.ts",
      task_id: "l3",
    });
    expect(String(r3)).toContain("Spawned");

    const r4 = await spawnSubPlanner.call(agent, {
      parent_id: "sub-l3",
      name: "sub-l4",
      task: "too deep",
      task_id: "l4",
    });
    expect(String(r4)).toContain("depth limit");
  });

  it("maintains recursive structure with nested sub-planners", async () => {
    const spawnSubPlanner = (agent as any).spawnSubPlanner ?? (agent as any).spawn_sub_planner;
    expect(typeof spawnSubPlanner).toBe("function");

    await spawnSubPlanner.call(agent, {
      parent_id: "root",
      name: "sub-r1",
      task: "complex task src/a.ts src/b.ts src/c.ts",
      task_id: "sr1",
    });

    await spawnSubPlanner.call(agent, {
      parent_id: "sub-r1",
      name: "sub-r2",
      task: "complex task src/d.ts src/e.ts src/f.ts",
      task_id: "sr2",
    });

    const state = agent.getState() as any;
    const teammates = state.teammates ?? [];
    const subR1 = teammates.find((t: any) => t.name === "sub-r1");
    const subR2 = teammates.find((t: any) => t.name === "sub-r2");

    expect(subR1).toBeTruthy();
    expect(subR2).toBeTruthy();
    expect(String(subR1.currentTask ?? "")).toContain("depth=1");
    expect(String(subR2.currentTask ?? "")).toContain("depth=2");
  });
});
