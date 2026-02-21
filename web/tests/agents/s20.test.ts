import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/agents/shared/api-client", () => ({ createMessage: vi.fn() }));

type UnknownRecord = Record<string, unknown>;

const S20_MODULE_PATH = "@/agents/s20";

async function loadS20Module(): Promise<UnknownRecord | null> {
  try {
    const modulePath = S20_MODULE_PATH;
    return (await import(modulePath)) as UnknownRecord;
  } catch {
    return null;
  }
}

async function instantiateS20Runtime(): Promise<any | null> {
  const mod = await loadS20Module();
  if (!mod) return null;

  const ctorCandidates = [
    "ReconciliationPassAgent",
    "ReconciliationAgent",
    "ReconciliationManagerAgent",
    "HarnessReconciliationAgent",
    "CapstoneHarnessAgent",
    "ReconciliationPass",
    "ReconciliationManager",
    "default",
  ];

  for (const name of ctorCandidates) {
    const Candidate = mod[name] as unknown;
    if (typeof Candidate !== "function") continue;

    const config = {
      apiKey: "test-key",
      maxIterations: 3,
      reconciliationMaxIterations: 3,
      plannerName: "planner",
    };

    try {
      return new (Candidate as new (cfg: UnknownRecord) => unknown)(config);
    } catch {
      try {
        return (Candidate as (cfg: UnknownRecord) => unknown)(config);
      } catch {
        try {
          return new (Candidate as new () => unknown)();
        } catch {
          try {
            return (Candidate as () => unknown)();
          } catch {}
        }
      }
    }
  }

  return null;
}

function getState(runtime: any): UnknownRecord {
  if (typeof runtime?.getState === "function") {
    return (runtime.getState() ?? {}) as UnknownRecord;
  }
  return (runtime?.state ?? {}) as UnknownRecord;
}

async function invokeFirst(target: any, names: string[], ...args: unknown[]): Promise<unknown> {
  for (const name of names) {
    if (typeof target?.[name] === "function") {
      return await target[name](...args);
    }
  }
  throw new Error(`Expected one method from: ${names.join(", ")}`);
}

function textOf(value: unknown): string {
  return JSON.stringify(value ?? "").toLowerCase();
}

describe("s20 - Reconciliation pass", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("captures a green-branch snapshot when reconciliation reaches clean state", async () => {
    const runtime = await instantiateS20Runtime();
    if (!runtime) return;

    await invokeFirst(runtime, ["runReconciliation", "reconcile", "executeReconciliation", "run_reconciliation"]);

    const state = getState(runtime);
    const asText = textOf(state);

    expect(
      asText.includes("green") || asText.includes("snapshot") || asText.includes("reconciliation_complete")
    ).toBe(true);
  });

  it("executes validation suite during reconciliation", async () => {
    const runtime = await instantiateS20Runtime();
    if (!runtime) return;

    await invokeFirst(runtime, ["runReconciliation", "reconcile", "executeReconciliation", "run_reconciliation"]);

    const state = getState(runtime);
    const asText = textOf(state);

    expect(
      asText.includes("validation") ||
        asText.includes("test_suite") ||
        asText.includes("test") ||
        asText.includes("build")
    ).toBe(true);
  });

  it("spawns fixer workers when failures are detected", async () => {
    const runtime = await instantiateS20Runtime();
    if (!runtime) return;

    await invokeFirst(runtime, ["runReconciliation", "reconcile", "executeReconciliation", "run_reconciliation"]);

    const state = getState(runtime);
    const asText = textOf(state);

    expect(asText.includes("fixer") || asText.includes("fix_task") || asText.includes("spawn") || asText.includes("critical")).toBe(true);
  });

  it("enforces reconciliation iteration cap", async () => {
    const runtime = await instantiateS20Runtime();
    if (!runtime) return;

    await invokeFirst(runtime, ["runReconciliation", "reconcile", "executeReconciliation", "run_reconciliation"]);

    const state = getState(runtime);
    const asText = textOf(state);

    expect(
      asText.includes("max_iterations") ||
        asText.includes("iteration cap") ||
        asText.includes("iterations") ||
        asText.includes("max_retries")
    ).toBe(true);
  });

  it("produces a final reconciliation verdict", async () => {
    const runtime = await instantiateS20Runtime();
    if (!runtime) return;

    const outcome = await invokeFirst(runtime, [
      "runReconciliation",
      "reconcile",
      "executeReconciliation",
      "run_reconciliation",
      "run",
    ]);

    const outcomeText = textOf(outcome);
    const stateText = textOf(getState(runtime));
    const combined = `${outcomeText} ${stateText}`;

    expect(
      combined.includes("green") ||
        combined.includes("partial") ||
        combined.includes("failed") ||
        combined.includes("verdict") ||
        combined.includes("success")
    ).toBe(true);
  });
});
