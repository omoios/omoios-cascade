import type {
  AgentConfig,
  AgentState,
  ContentBlock,
  ToolDefinition,
  ToolResultBlock,
  ToolUseBlock,
} from "./shared";
import { FailureModesRecoveryAgent } from "./s19";

interface ReconciliationFailure {
  failure_id: string;
  check: string;
  path: string;
  output: string;
  severity: "critical" | "high" | "medium";
}

interface TestSuiteResult {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  failures: ReconciliationFailure[];
  output: string;
}

interface GreenBranchSnapshot {
  snapshot_id: string;
  created_at: number;
  file_count: number;
  report_id: string;
  path: string;
}

interface FixerTask {
  fixer_task_id: string;
  created_at: number;
  status: "pending" | "spawned" | "merged" | "failed";
  failure_id: string;
  failure_check: string;
  failure_path: string;
  iteration: number;
  worker_name: string;
  worker_task_id: string;
  spawn_output: string;
  merge_output: string;
}

interface ReconciliationIteration {
  iteration: number;
  test_suite: TestSuiteResult;
  fixer_task_ids: string[];
}

interface ReconciliationReport {
  report_id: string;
  started_at: number;
  completed_at: number;
  status: "green" | "red";
  max_iterations: number;
  iterations_executed: number;
  iterations: ReconciliationIteration[];
  final_test_suite: TestSuiteResult;
  fixer_tasks_applied: number;
  remaining_failures: number;
  green_branch_snapshot_id: string | null;
}

interface ReconciliationPassConfig {
  maxIterations: number;
  runTestSuite: () => TestSuiteResult;
  spawnFixer: (failure: ReconciliationFailure, iteration: number, index: number) => Promise<FixerTask>;
  createGreenSnapshot: (reportId: string) => GreenBranchSnapshot;
}

export class ReconciliationPass {
  private readonly maxIterations: number;
  private readonly runTestSuiteFn: () => TestSuiteResult;
  private readonly spawnFixerFn: (failure: ReconciliationFailure, iteration: number, index: number) => Promise<FixerTask>;
  private readonly createGreenSnapshotFn: (reportId: string) => GreenBranchSnapshot;

  constructor(config: ReconciliationPassConfig) {
    this.maxIterations = Math.max(1, Math.floor(config.maxIterations));
    this.runTestSuiteFn = config.runTestSuite;
    this.spawnFixerFn = config.spawnFixer;
    this.createGreenSnapshotFn = config.createGreenSnapshot;
  }

  async run(reportId: string): Promise<{ report: ReconciliationReport; fixers: FixerTask[] }> {
    const startedAt = Date.now();
    const iterations: ReconciliationIteration[] = [];
    const fixers: FixerTask[] = [];

    let finalSuite = this.runTestSuiteFn();
    let snapshotId: string | null = null;

    for (let iteration = 1; iteration <= this.maxIterations; iteration += 1) {
      const suite = iteration === 1 ? finalSuite : this.runTestSuiteFn();
      const fixerTaskIds: string[] = [];

      if (suite.failures.length === 0) {
        const snapshot = this.createGreenSnapshotFn(reportId);
        snapshotId = snapshot.snapshot_id;
        iterations.push({ iteration, test_suite: suite, fixer_task_ids: fixerTaskIds });
        finalSuite = suite;
        break;
      }

      for (let idx = 0; idx < suite.failures.length; idx += 1) {
        const failure = suite.failures[idx];
        const fixer = await this.spawnFixerFn(failure, iteration, idx);
        fixers.push(fixer);
        fixerTaskIds.push(fixer.fixer_task_id);
      }

      iterations.push({ iteration, test_suite: suite, fixer_task_ids: fixerTaskIds });
      finalSuite = this.runTestSuiteFn();

      if (finalSuite.failures.length === 0) {
        const snapshot = this.createGreenSnapshotFn(reportId);
        snapshotId = snapshot.snapshot_id;
        break;
      }
    }

    const completedAt = Date.now();
    const report: ReconciliationReport = {
      report_id: reportId,
      started_at: startedAt,
      completed_at: completedAt,
      status: finalSuite.failures.length === 0 ? "green" : "red",
      max_iterations: this.maxIterations,
      iterations_executed: iterations.length,
      iterations,
      final_test_suite: finalSuite,
      fixer_tasks_applied: fixers.filter((fixer) => fixer.status === "merged").length,
      remaining_failures: finalSuite.failures.length,
      green_branch_snapshot_id: snapshotId,
    };

    return { report, fixers };
  }
}

export class ReconciliationPassAgent extends FailureModesRecoveryAgent {
  private readonly reconciliationIterationCap: number;
  private readonly reconciliationPass: ReconciliationPass;
  private readonly reconciliationReports: ReconciliationReport[] = [];
  private readonly fixerTasks: FixerTask[] = [];
  private readonly greenBranchSnapshots: GreenBranchSnapshot[] = [];

  constructor(config: AgentConfig & { reconciliationMaxIterations?: number }) {
    super(config);
    this.reconciliationIterationCap = Math.max(1, Math.floor(config.reconciliationMaxIterations ?? 3));

    this.reconciliationPass = new ReconciliationPass({
      maxIterations: this.reconciliationIterationCap,
      runTestSuite: () => this.runTestSuite(),
      spawnFixer: (failure, iteration, index) => this.spawnFixerForFailure(failure, iteration, index),
      createGreenSnapshot: (reportId) => this.createGreenBranchSnapshot(reportId),
    });
  }

  override getSystemPrompt(): string {
    return [
      super.getSystemPrompt(),
      "Reconciliation policy:",
      "- Lifecycle includes INIT -> DECOMPOSE -> ORCHESTRATE -> RECONCILE -> DONE.",
      "- RECONCILE runs full test sweep and spawns fixers for remaining failures.",
      "- Capture green branch snapshot when suite is fully green.",
      "- Reconciliation has strict iteration cap (default 3).",
    ].join("\n");
  }

  override getTools(): ToolDefinition[] {
    return [
      ...super.getTools(),
      {
        name: "run_reconciliation",
        description: "Run final reconciliation pass (test -> fixers -> retest) with iteration cap.",
        input_schema: {
          type: "object",
          properties: {
            reason: { type: "string" },
          },
        },
      },
      {
        name: "run_test_suite",
        description: "Run reconciliation test suite check and return current failure list.",
        input_schema: {
          type: "object",
          properties: {},
        },
      },
      {
        name: "list_reconciliation_reports",
        description: "List reconciliation reports (latest first).",
        input_schema: {
          type: "object",
          properties: {
            limit: { type: "integer" },
          },
        },
      },
      {
        name: "list_green_branch_snapshots",
        description: "List green branch snapshots produced by reconciliation.",
        input_schema: {
          type: "object",
          properties: {
            limit: { type: "integer" },
          },
        },
      },
      {
        name: "list_fixer_tasks",
        description: "List fixer tasks spawned during reconciliation.",
        input_schema: {
          type: "object",
          properties: {
            limit: { type: "integer" },
            status: { type: "string", enum: ["pending", "spawned", "merged", "failed"] },
          },
        },
      },
    ];
  }

  private makeFailureId(prefix: string): string {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  private relevantFiles(snapshot: Record<string, string>): Array<[string, string]> {
    return Object.entries(snapshot)
      .filter(([path]) => {
        if (path.startsWith(".activity/")) return false;
        if (path.startsWith(".green-branch/")) return false;
        if (path.startsWith(".scratchpad/")) return false;
        if (path.startsWith(".team/")) return false;
        return true;
      })
      .sort(([a], [b]) => a.localeCompare(b));
  }

  private runTestSuite(): TestSuiteResult {
    const snapshot = this.toolExecutor.fs.snapshot();
    const files = this.relevantFiles(snapshot);
    const failures: ReconciliationFailure[] = [];

    for (const [path, content] of files) {
      if (/^<{7}|^={7}|^>{7}/m.test(content)) {
        failures.push({
          failure_id: this.makeFailureId("merge-conflict"),
          check: "merge_conflict_markers",
          path,
          output: `Conflict markers detected in ${path}`,
          severity: "critical",
        });
      }

      if (content.includes("FAIL_RECONCILIATION") || content.includes("TODO_FAIL") || content.includes("__RECONCILE_FAIL__")) {
        failures.push({
          failure_id: this.makeFailureId("assertion-failure"),
          check: "explicit_failure_marker",
          path,
          output: `Failure marker detected in ${path}`,
          severity: "high",
        });
      }

      if (/\.test\.[jt]sx?$/.test(path) && /\b(?:it|test)\.only\(/.test(content)) {
        failures.push({
          failure_id: this.makeFailureId("focused-test"),
          check: "focused_test_present",
          path,
          output: `Focused test (.only) detected in ${path}`,
          severity: "medium",
        });
      }
    }

    const totalChecks = Math.max(1, files.length);
    const failed = failures.length;
    const passed = Math.max(0, totalChecks - Math.min(totalChecks, failed));

    return {
      total: totalChecks,
      passed,
      failed,
      skipped: 0,
      failures,
      output:
        failed === 0
          ? "Test suite: PASS (simulated reconciliation suite)"
          : `Test suite: FAIL (${failed} issue${failed === 1 ? "" : "s"})`,
    };
  }

  private parseSpawnOutput(output: string): { name: string; taskId: string } | null {
    const match = output.match(/Spawned '([^']+)' with task_id=([^\s]+)/);
    if (!match) return null;
    return { name: match[1], taskId: match[2] };
  }

  private createSyntheticToolUse(name: string, input: Record<string, unknown>): ToolUseBlock {
    return {
      type: "tool_use",
      id: `reconcile-${name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name,
      input,
    };
  }

  private async spawnFixerForFailure(
    failure: ReconciliationFailure,
    iteration: number,
    index: number
  ): Promise<FixerTask> {
    const fixerTaskId = `reconcile-fix-${iteration}-${index + 1}-${Math.random().toString(36).slice(2, 6)}`;
    const fixerName = `fixer-${iteration}-${index + 1}`;

    const fixerTask: FixerTask = {
      fixer_task_id: fixerTaskId,
      created_at: Date.now(),
      status: "pending",
      failure_id: failure.failure_id,
      failure_check: failure.check,
      failure_path: failure.path,
      iteration,
      worker_name: fixerName,
      worker_task_id: fixerTaskId,
      spawn_output: "",
      merge_output: "",
    };

    const spawnDescription = [
      "RECONCILIATION FIXER TASK (CRITICAL):",
      `- failure_id: ${failure.failure_id}`,
      `- check: ${failure.check}`,
      `- path: ${failure.path}`,
      `- output: ${failure.output}`,
      "Goal: make the suite green. Apply the smallest deterministic fix and submit handoff.",
    ].join("\n");

    const spawnUse = this.createSyntheticToolUse("spawn_worker", {
      name: fixerName,
      task: spawnDescription,
      task_id: fixerTaskId,
    });

    const spawnResults = await super.processToolCalls([spawnUse]);
    const spawnOutput = spawnResults[0]?.content ?? "";
    fixerTask.spawn_output = spawnOutput;

    if (spawnOutput.startsWith("Error:")) {
      fixerTask.status = "failed";
      return fixerTask;
    }

    fixerTask.status = "spawned";

    const parsed = this.parseSpawnOutput(spawnOutput);
    if (parsed) {
      fixerTask.worker_name = parsed.name;
      fixerTask.worker_task_id = parsed.taskId;
    }

    const mergeUse = this.createSyntheticToolUse("optimistic_merge", {
      agent_id: fixerTask.worker_name,
      task_id: fixerTask.worker_task_id,
    });

    const mergeResults = await super.processToolCalls([mergeUse]);
    const mergeOutput = mergeResults[0]?.content ?? "";
    fixerTask.merge_output = mergeOutput;

    if (mergeOutput.startsWith("Error:")) {
      fixerTask.status = "failed";
      return fixerTask;
    }

    fixerTask.status = "merged";
    return fixerTask;
  }

  private createGreenBranchSnapshot(reportId: string): GreenBranchSnapshot {
    const snapshotId = `green-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const fullSnapshot = this.toolExecutor.fs.snapshot();
    const filteredSnapshot = Object.fromEntries(this.relevantFiles(fullSnapshot));
    const path = `.green-branch/${snapshotId}.json`;

    this.toolExecutor.fs.writeFile(path, JSON.stringify(filteredSnapshot, null, 2));

    const snapshot: GreenBranchSnapshot = {
      snapshot_id: snapshotId,
      created_at: Date.now(),
      file_count: Object.keys(filteredSnapshot).length,
      report_id: reportId,
      path,
    };

    this.greenBranchSnapshots.push(snapshot);
    return snapshot;
  }

  private listReconciliationReports(input: Record<string, unknown>): string {
    const rawLimit = Number(input.limit ?? 20);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.floor(rawLimit) : 20;
    return JSON.stringify(this.reconciliationReports.slice(-limit), null, 2);
  }

  private listGreenBranchSnapshots(input: Record<string, unknown>): string {
    const rawLimit = Number(input.limit ?? 20);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.floor(rawLimit) : 20;
    return JSON.stringify(this.greenBranchSnapshots.slice(-limit), null, 2);
  }

  private listFixerTasks(input: Record<string, unknown>): string {
    const rawLimit = Number(input.limit ?? 100);
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.floor(rawLimit) : 100;
    const status =
      input.status === "pending" || input.status === "spawned" || input.status === "merged" || input.status === "failed"
        ? input.status
        : undefined;

    const filtered = status ? this.fixerTasks.filter((task) => task.status === status) : this.fixerTasks;
    return JSON.stringify(filtered.slice(-limit), null, 2);
  }

  private async runReconciliation(reason = "manual"): Promise<string> {
    const reportId = `reconcile-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const { report, fixers } = await this.reconciliationPass.run(reportId);

    this.fixerTasks.push(...fixers);
    this.reconciliationReports.push(report);

    const summary = {
      report_id: report.report_id,
      reason,
      status: report.status,
      iterations_executed: report.iterations_executed,
      max_iterations: report.max_iterations,
      fixer_tasks_applied: report.fixer_tasks_applied,
      remaining_failures: report.remaining_failures,
      green_branch_snapshot_id: report.green_branch_snapshot_id,
    };

    return JSON.stringify(summary, null, 2);
  }

  protected override async processToolCalls(content: ContentBlock[]): Promise<ToolResultBlock[]> {
    const results: ToolResultBlock[] = [];

    for (const block of content) {
      if (block.type !== "tool_use") continue;

      if (block.name === "run_reconciliation") {
        this.emit("tool_call", { name: block.name, input: block.input });
        const reason = String((block.input as Record<string, unknown>).reason ?? "manual");
        const output = await this.runReconciliation(reason);
        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: output,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: output, is_error: false });
        continue;
      }

      if (block.name === "run_test_suite") {
        this.emit("tool_call", { name: block.name, input: block.input });
        const output = JSON.stringify(this.runTestSuite(), null, 2);
        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: output,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: output, is_error: false });
        continue;
      }

      if (block.name === "list_reconciliation_reports") {
        this.emit("tool_call", { name: block.name, input: block.input });
        const output = this.listReconciliationReports(block.input as Record<string, unknown>);
        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: output,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: output, is_error: false });
        continue;
      }

      if (block.name === "list_green_branch_snapshots") {
        this.emit("tool_call", { name: block.name, input: block.input });
        const output = this.listGreenBranchSnapshots(block.input as Record<string, unknown>);
        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: output,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: output, is_error: false });
        continue;
      }

      if (block.name === "list_fixer_tasks") {
        this.emit("tool_call", { name: block.name, input: block.input });
        const output = this.listFixerTasks(block.input as Record<string, unknown>);
        const result: ToolResultBlock = {
          type: "tool_result",
          tool_use_id: block.id,
          content: output,
        };
        results.push(result);
        this.emit("tool_result", { tool_use_id: block.id, name: block.name, content: output, is_error: false });
        continue;
      }

      const delegated = await super.processToolCalls([block]);
      const delegatedResult = delegated[0] ?? {
        type: "tool_result" as const,
        tool_use_id: block.id,
        content: "",
      };
      results.push(delegatedResult);
    }

    return results;
  }

  override async run(userMessage: string): Promise<string> {
    const primary = await super.run(userMessage);
    const reconcileSummary = await this.runReconciliation("auto_post_orchestrate");
    const merged = [primary, `Reconciliation summary:\n${reconcileSummary}`].filter((item) => item && item.trim().length > 0);
    const finalText = merged.join("\n\n");
    this.emit("done", { text: finalText, iterations: this.loopIteration });
    return finalText;
  }

  override getState(): AgentState {
    return {
      ...super.getState(),
      lifecycle: "INIT -> DECOMPOSE -> ORCHESTRATE -> RECONCILE -> DONE",
      reconciliationReports: this.reconciliationReports,
      fixerTasks: this.fixerTasks,
      greenBranchSnapshots: this.greenBranchSnapshots,
      reconciliationPolicy: {
        iteration_cap: this.reconciliationIterationCap,
      },
    } as AgentState;
  }
}

export { ReconciliationPassAgent as ReconciliationAgent };
export { ReconciliationPassAgent as GreenBranchReconciliationAgent };
export default ReconciliationPassAgent;
