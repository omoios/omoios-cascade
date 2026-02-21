import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/agents/shared/api-client", () => ({ createMessage: vi.fn() }));

import { createMessage } from "@/agents/shared/api-client";

const mockCreate = vi.mocked(createMessage);

function mockResponse(text: string) {
  return {
    id: "msg_test",
    role: "assistant" as const,
    content: [{ type: "text" as const, text }],
    stop_reason: "end_turn" as const,
    usage: { input_tokens: 120, output_tokens: 60 },
  };
}

async function instantiateS18Agent(): Promise<any> {
  const mod = await import("@/agents/s18");
  return new mod.ErrorTolerantAgent({
    apiKey: "test-key",
    maxIterations: 8,
    plannerName: "planner",
    errorBudget: 3,
  });
}

function getState(agent: any) {
  return (agent.getState?.() ?? {}) as {
    errorPolicy?: { consumed?: number; budget?: number; over_budget?: boolean };
    errorTasks?: Array<{
      error_task_id: string;
      category: string;
      source: string;
      status: string;
      over_budget: boolean;
      budget_index: number;
    }>;
  };
}

describe("s18 - ErrorTolerantAgent", () => {
  let agent: any;

  beforeEach(async () => {
    vi.clearAllMocks();
    agent = await instantiateS18Agent();
  });

  it("tracks error budget consumption", async () => {
    const before = getState(agent);
    const beforeConsumed = before.errorPolicy?.consumed ?? 0;
    const beforeTaskCount = before.errorTasks?.length ?? 0;

    mockCreate
      .mockRejectedValueOnce(new Error("timeout while calling model"))
      .mockResolvedValueOnce(mockResponse("recovered"));

    await agent.run("continue after llm error");

    const after = getState(agent);
    expect(after.errorPolicy?.consumed).toBe(beforeConsumed + 1);
    expect(after.errorTasks?.length ?? 0).toBe(beforeTaskCount + 1);
  });

  it("turns errors into tracked tasks", async () => {
    mockCreate
      .mockRejectedValueOnce(new Error("old_text not found during edit"))
      .mockResolvedValueOnce(mockResponse("done"));

    await agent.run("record filesystem failure as task");

    const state = getState(agent);
    const task = state.errorTasks?.at(-1);

    expect(task).toBeTruthy();
    expect(task?.error_task_id).toContain("err-");
    expect(task?.source).toBe("llm:create_message");
    expect(task?.status).toBe("open");
    expect(task?.category).toBe("Filesystem");
  });

  it("categorizes different errors correctly", async () => {
    mockCreate
      .mockRejectedValueOnce(new Error("permission denied writing file"))
      .mockResolvedValueOnce(mockResponse("step 1 done"))
      .mockRejectedValueOnce(new Error("invalid schema payload"))
      .mockResolvedValueOnce(mockResponse("step 2 done"));

    await agent.run("first category");
    await agent.run("second category");

    const state = getState(agent);
    const categories = new Set((state.errorTasks ?? []).map((task) => task.category));

    expect(categories.has("Permission")).toBe(true);
    expect(categories.has("Validation")).toBe(true);
  });

  it("does not halt when an error occurs", async () => {
    mockCreate
      .mockRejectedValueOnce(new Error("temporary api outage"))
      .mockResolvedValueOnce(mockResponse("workflow completed"));

    const text = await agent.run("should continue after error");

    expect(mockCreate).toHaveBeenCalledTimes(2);
    expect(text).toContain("workflow completed");
    expect((getState(agent).errorTasks ?? []).length).toBeGreaterThanOrEqual(1);
  });
});
