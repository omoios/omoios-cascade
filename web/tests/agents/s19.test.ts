import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/agents/shared/api-client", () => ({ createMessage: vi.fn() }));

type Failure = { agentId: string; failureType: string };

async function instantiateS19Runtime(): Promise<any> {
  const mod = await import("@/agents/s19");

  const AgentCtor =
    mod.FailureModesAgent ?? mod.FailureModesRecoveryAgent ?? mod.WatchdogRecoveryAgent ?? mod.default;

  if (typeof AgentCtor === "function") {
    return new AgentCtor({
      apiKey: "test-key",
      maxIterations: 8,
      zombieMs: 25,
      tunnelVisionEdits: 3,
      tokenBurnCalls: 6,
    });
  }

  if (typeof mod.Watchdog === "function") {
    return new mod.Watchdog({
      zombieMs: 25,
      tunnelVisionEdits: 3,
      tokenBurnCalls: 6,
    });
  }

  throw new Error("Could not find s19 runtime export (expected agent class or Watchdog)");
}

function watchdogOf(runtime: any): any {
  return runtime?.watchdog ?? runtime;
}

function invokeFirst(target: any, names: string[], ...args: unknown[]): unknown {
  for (const name of names) {
    if (typeof target?.[name] === "function") {
      return target[name](...args);
    }
  }
  throw new Error(`Expected one method from: ${names.join(", ")}`);
}

function normalizeFailureType(raw: unknown): string {
  const text = String(raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_");

  if (text.includes("zombie")) return "zombie";
  if (text.includes("tunnel")) return "tunnel_vision";
  if (text.includes("token") && text.includes("burn")) return "token_burn";
  return text;
}

function extractFailures(raw: unknown): Failure[] {
  const rows = Array.isArray(raw)
    ? raw
    : Array.isArray((raw as any)?.failures)
      ? (raw as any).failures
      : [];

  return rows
    .map((entry: any) => {
      if (Array.isArray(entry)) {
        return {
          agentId: String(entry[0] ?? ""),
          failureType: normalizeFailureType(entry[1]),
        };
      }

      return {
        agentId: String(entry?.agentId ?? entry?.agent_id ?? entry?.id ?? ""),
        failureType: normalizeFailureType(entry?.failureType ?? entry?.failure_type ?? entry?.type),
      };
    })
    .filter((entry: Failure) => entry.agentId.length > 0 && entry.failureType.length > 0);
}

async function detectFailures(watchdog: any): Promise<Failure[]> {
  const result = await invokeFirst(watchdog, [
    "checkFailures",
    "detectFailures",
    "inspectFailures",
    "runDetection",
    "_checkFailures",
  ]);
  return extractFailures(result);
}

function getState(runtime: any): Record<string, unknown> {
  if (typeof runtime?.getState === "function") {
    return runtime.getState() as Record<string, unknown>;
  }
  const wd = watchdogOf(runtime);
  if (typeof wd?.getState === "function") {
    return wd.getState() as Record<string, unknown>;
  }
  return {};
}

function registerAgent(watchdog: any, agentId: string): void {
  invokeFirst(watchdog, ["registerAgent", "register_agent", "trackAgent"], agentId, "test scope");
}

function heartbeat(watchdog: any, agentId: string): void {
  invokeFirst(watchdog, ["heartbeat", "touch", "ping"], agentId);
}

function recordActivity(watchdog: any, agentId: string, input: Record<string, unknown>): void {
  invokeFirst(
    watchdog,
    ["recordActivity", "record_activity", "trackActivity", "logActivity"],
    agentId,
    input
  );
}

describe("s19 - Failure modes and recovery", () => {
  let runtime: any;
  let watchdog: any;

  beforeEach(async () => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    runtime = await instantiateS19Runtime();
    watchdog = watchdogOf(runtime);
  });

  it("detects zombie agents", async () => {
    registerAgent(watchdog, "agent-zombie");
    heartbeat(watchdog, "agent-zombie");

    vi.advanceTimersByTime(200);
    const failures = await detectFailures(watchdog);

    expect(failures.some((entry) => entry.agentId === "agent-zombie" && entry.failureType === "zombie")).toBe(true);
  });

  it("detects tunnel vision on repeated same-file edits", async () => {
    registerAgent(watchdog, "agent-tunnel");

    for (let i = 0; i < 4; i += 1) {
      recordActivity(watchdog, "agent-tunnel", {
        file: "src/repeated.ts",
        action: "edit_file",
        outputLines: 0,
      });
    }

    const failures = await detectFailures(watchdog);
    expect(
      failures.some((entry) => entry.agentId === "agent-tunnel" && entry.failureType === "tunnel_vision")
    ).toBe(true);
  });

  it("detects token burn when spend has no progress", async () => {
    registerAgent(watchdog, "agent-burn");

    for (let i = 0; i < 8; i += 1) {
      recordActivity(watchdog, "agent-burn", {
        tokens: 100,
        outputLines: 0,
        action: "llm_call",
      });
    }

    const failures = await detectFailures(watchdog);
    expect(failures.some((entry) => entry.agentId === "agent-burn" && entry.failureType === "token_burn")).toBe(true);
  });

  it("runs kill + respawn recovery cycle", async () => {
    registerAgent(watchdog, "agent-recover");
    heartbeat(watchdog, "agent-recover");
    vi.advanceTimersByTime(200);

    const failures = await detectFailures(watchdog);
    const zombieFailure = failures.find(
      (entry) => entry.agentId === "agent-recover" && entry.failureType === "zombie"
    );
    expect(zombieFailure).toBeTruthy();

    invokeFirst(watchdog, ["handleFailure", "applyRecovery", "recoverFailure", "killAndRespawn"], {
      agentId: "agent-recover",
      failureType: "zombie",
    });

    const state = getState(runtime);
    const asText = JSON.stringify(state).toLowerCase();

    expect(asText.includes("kill") || asText.includes("shutdown") || asText.includes("terminated")).toBe(true);
    expect(asText.includes("respawn") || asText.includes("requeue") || asText.includes("re-queue")).toBe(true);
  });
});
