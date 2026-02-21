import { describe, it, expect, vi, beforeEach } from "vitest";
import { WorkerIsolationAgent } from "@/agents/s15";

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

describe("s15 - WorkerIsolationAgent", () => {
  let agent: WorkerIsolationAgent;

  beforeEach(() => {
    vi.clearAllMocks();
    agent = new WorkerIsolationAgent({
      apiKey: "test-key",
      maxIterations: 4,
      plannerName: "planner",
    });
  });

  it("planner and worker tool surfaces are role-isolated", () => {
    const plannerTools = agent.getTools().map((t) => t.name);
    expect(plannerTools).toContain("spawn_worker");
    expect(plannerTools).toContain("review_handoff");
    expect(plannerTools).not.toContain("write_file");
    expect(plannerTools).not.toContain("edit_file");
    expect(plannerTools).not.toContain("bash");

    const workerTools = ((agent as any).getWorkerTools() as Array<{ name: string }>).map(
      (t) => t.name
    );
    expect(workerTools).toContain("write_file");
    expect(workerTools).toContain("edit_file");
    expect(workerTools).toContain("submit_handoff");
    expect(workerTools).not.toContain("spawn_worker");
  });

  it("worker writes only in private workspace and diff is against canonical", async () => {
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
              input: { path: "src/app.py", content: "print('hello from workspace')\n" },
            },
            {
              id: "w2",
              name: "submit_handoff",
              input: { status: "Success", narrative: "implemented in workspace" },
            },
          ],
        })
      )
      // planner end
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("Decompose and delegate");

    const state = agent.getState() as any;
    expect(state.handoffs.length).toBe(1);

    const handoff = state.handoffs[0];
    expect(handoff.agent_id).toBe("worker-a");
    expect(handoff.status).toBe("Success");
    expect(handoff.workspace_path).toContain(".workspaces/worker-a");
    expect(Object.keys(handoff.diff)).toContain("src/app.py");
    expect(handoff.diff["src/app.py"].before).toBe("");
    expect(handoff.diff["src/app.py"].after).toContain("hello from workspace");

    const fs = (agent as any).toolExecutor.fs;
    expect(fs.getFile("src/app.py")).toBeUndefined();

    const workspaceState = (state.workspaces as Array<{ worker: string; cleaned: boolean }>).find(
      (w) => w.worker === "worker-a"
    );
    expect(workspaceState?.cleaned).toBe(true);
  });

  it("worker cannot access sibling workspace paths", async () => {
    mockCreate
      // planner call
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "p1",
              name: "spawn_worker",
              input: {
                name: "worker-c",
                task: "Try writing in another workspace and submit handoff",
                task_id: "t-2",
              },
            },
          ],
        })
      )
      // worker call tries forbidden path
      .mockResolvedValueOnce(
        mockResponse({
          toolCalls: [
            {
              id: "w1",
              name: "write_file",
              input: { path: ".workspaces/worker-d/hijack.txt", content: "bad\n" },
            },
            {
              id: "w2",
              name: "submit_handoff",
              input: { narrative: "blocked by workspace boundary" },
            },
          ],
        })
      )
      // planner end
      .mockResolvedValueOnce(mockResponse({ text: "done" }));

    await agent.run("delegate");

    const state = agent.getState() as any;
    expect(state.handoffs.length).toBe(1);
    const handoff = state.handoffs[0];
    expect(["Blocked", "Failed"]).toContain(handoff.status);
    expect(handoff.metrics.files_modified).toBe(0);

    const fs = (agent as any).toolExecutor.fs;
    expect(fs.getFile(".workspaces/worker-d/hijack.txt")).toBeUndefined();
  });
});
