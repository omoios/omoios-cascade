# Harness Design Document

## Problem Statement

Building software with AI agents today is single-threaded: one agent, one context window, one task at a time. This limits throughput to however fast a single model can think and type. Cursor's research showed that thousands of agents working in parallel can achieve ~1,000 commits/hour — but only with the right orchestration architecture.

This design document specifies `harness`, a Python package that implements a recursive planner-worker architecture for long-running, multi-codebase autonomous development. It is a toy learning implementation that demonstrates production patterns at educational scale.

## Goals

1. Orchestrate 10-100 concurrent AI agents across 1-3 codebases
2. Structured data flow using pydantic v2 models throughout
3. Type-safe configuration via pydantic-settings and .env files
4. Incremental testability — every layer testable in isolation
5. Demonstrate all patterns from sessions s12-s20 of learn-claude-code

## Non-Goals

1. Distributed systems — single machine, single process
2. Production scale (1000+ agents) — this is a learning tool
3. Multi-model support — Anthropic SDK only
4. Web UI or dashboard — CLI and logs only
5. Real-time streaming — batch message processing

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│                   CLI Entry                  │
│            harness run <config>              │
└───────────────────┬─────────────────────────┘
                    │
┌───────────────────▼─────────────────────────┐
│              HarnessConfig                   │
│         (pydantic-settings from .env)        │
└───────────────────┬─────────────────────────┘
                    │
┌───────────────────▼─────────────────────────┐
│              Orchestrator                    │
│   Owns lifecycle: INIT → DECOMPOSE →        │
│   ORCHESTRATE → RECONCILE → DONE           │
└──────┬──────────────┬───────────────────────┘
       │              │
┌──────▼──────┐ ┌─────▼──────┐
│ Root Planner│ │  Watchdog  │
│  (agent)    │ │  (daemon)  │
└──────┬──────┘ └────────────┘
       │
  ┌────┴────┐
  │SubPlanner│──► Workers (each in own thread + workspace)
  └─────────┘
```

## Configuration

### HarnessConfig (pydantic-settings)

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")

    api_key: str = Field(description="Anthropic API key")
    model: str = Field(default="claude-sonnet-4-20250514")
    max_tokens: int = Field(default=8192)
    base_url: str | None = Field(default=None)


class WorkspaceConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKSPACE_")

    root_dir: str = Field(default=".workspaces")
    canonical_dir: str = Field(default=".")
    cleanup_on_success: bool = Field(default=True)


class AgentLimitsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_")

    max_workers: int = Field(default=10)
    max_depth: int = Field(default=3)
    worker_timeout_seconds: int = Field(default=300)
    worker_token_budget: int = Field(default=100_000)
    scratchpad_rewrite_interval: int = Field(default=10)
    context_compression_threshold: float = Field(default=0.8)


class ErrorPolicyConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ERROR_")

    budget_percentage: float = Field(default=0.15)
    window_size: int = Field(default=20)
    max_reconciliation_rounds: int = Field(default=3)


class WatchdogConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WATCHDOG_")

    enabled: bool = Field(default=True)
    poll_interval_seconds: int = Field(default=15)
    zombie_timeout_seconds: int = Field(default=60)
    tunnel_vision_threshold: int = Field(default=20)
    token_burn_threshold: int = Field(default=16_000)


class HarnessConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    agents: AgentLimitsConfig = Field(default_factory=AgentLimitsConfig)
    errors: ErrorPolicyConfig = Field(default_factory=ErrorPolicyConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
    repos: list[str] = Field(default_factory=list, description="Paths to target repositories")
    instructions: str = Field(default="", description="Top-level instructions for the harness")
```

### Example .env

```
LLM_API_KEY=sk-ant-xxx
LLM_MODEL=claude-sonnet-4-20250514
LLM_MAX_TOKENS=8192
AGENT_MAX_WORKERS=10
AGENT_MAX_DEPTH=3
AGENT_WORKER_TIMEOUT_SECONDS=300
ERROR_BUDGET_PERCENTAGE=0.15
WATCHDOG_ENABLED=true
WATCHDOG_ZOMBIE_TIMEOUT_SECONDS=60
```

## Core Pydantic Models

### Task Models

```python
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class TaskStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Task(BaseModel):
    id: str = Field(description="Unique task identifier")
    parent_id: str | None = Field(default=None)
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    assigned_to: str | None = Field(default=None)
    repo: str | None = Field(default=None, description="Target repository path")
    blocked_by: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)
```

### Handoff Models

```python
class HandoffStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    BLOCKED = "blocked"


class FileDiff(BaseModel):
    path: str
    before_hash: str | None = None
    after_hash: str | None = None
    diff_text: str


class HandoffMetrics(BaseModel):
    wall_time_seconds: float
    tokens_used: int
    attempts: int
    files_modified: int
    tool_calls: int = 0


class Handoff(BaseModel):
    agent_id: str
    task_id: str
    status: HandoffStatus
    diffs: list[FileDiff] = Field(default_factory=list)
    narrative: str = Field(description="What was done, concerns, suggestions — THE critical field")
    artifacts: list[str] = Field(default_factory=list)
    metrics: HandoffMetrics
    error_message: str | None = None
    submitted_at: datetime = Field(default_factory=datetime.now)
```

### Agent Models

```python
class AgentRole(str, Enum):
    ROOT_PLANNER = "root_planner"
    SUB_PLANNER = "sub_planner"
    WORKER = "worker"
    WATCHDOG = "watchdog"


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class AgentConfig(BaseModel):
    agent_id: str
    role: AgentRole
    depth: int = 0
    parent_id: str | None = None
    task_id: str | None = None
    repo: str | None = None
    system_prompt: str = ""
    tool_names: list[str] = Field(default_factory=list)
    token_budget: int = 100_000
    timeout_seconds: int = 300
```

### Workspace Models

```python
class WorkspaceState(str, Enum):
    CREATING = "creating"
    READY = "ready"
    IN_USE = "in_use"
    MERGING = "merging"
    CLEANED = "cleaned"


class Workspace(BaseModel):
    worker_id: str
    repo_path: str
    workspace_path: str
    base_commit: str
    state: WorkspaceState = WorkspaceState.CREATING
    created_at: datetime = Field(default_factory=datetime.now)
```

### Merge Models

```python
class MergeStatus(str, Enum):
    CLEAN = "clean"
    CONFLICT = "conflict"
    NO_CHANGES = "no_changes"


class MergeResult(BaseModel):
    worker_id: str
    status: MergeStatus
    files_merged: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    fix_forward_task: Task | None = None


class ReconciliationRound(BaseModel):
    round_number: int
    test_command: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    fixers_spawned: int = 0
    fixers_succeeded: int = 0
    duration_seconds: float = 0.0


class ReconciliationReport(BaseModel):
    rounds: list[ReconciliationRound] = Field(default_factory=list)
    final_verdict: str = "pending"
    green_commit: str | None = None
```

### Error Budget Models

```python
class ErrorZone(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


class ErrorBudget(BaseModel):
    total_tasks: int = 0
    failed_tasks: int = 0
    window: list[bool] = Field(default_factory=list, description="Recent outcomes: True=success, False=failure")
    window_size: int = 20
    budget_percentage: float = 0.15
    zone: ErrorZone = ErrorZone.HEALTHY

    @property
    def failure_rate(self) -> float:
        if not self.window:
            return 0.0
        return self.window.count(False) / len(self.window)

    def record(self, success: bool) -> None:
        self.window.append(success)
        if len(self.window) > self.window_size:
            self.window.pop(0)
        self.total_tasks += 1
        if not success:
            self.failed_tasks += 1
        rate = self.failure_rate
        if rate > self.budget_percentage:
            self.zone = ErrorZone.CRITICAL
        elif rate > self.budget_percentage * 0.5:
            self.zone = ErrorZone.WARNING
        else:
            self.zone = ErrorZone.HEALTHY
```

### Watchdog Models

```python
class FailureMode(str, Enum):
    ZOMBIE = "zombie"
    TUNNEL_VISION = "tunnel_vision"
    TOKEN_BURN = "token_burn"
    SCOPE_CREEP = "scope_creep"


class WatchdogEvent(BaseModel):
    agent_id: str
    failure_mode: FailureMode
    evidence: str
    action_taken: str
    timestamp: datetime = Field(default_factory=datetime.now)


class ActivityEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    agent_id: str
    details: dict = Field(default_factory=dict)
    tokens_used: int = 0
    files_touched: list[str] = Field(default_factory=list)
```

## Agent Lifecycle

### Root Planner Lifecycle

```
INIT
 │  Load config, set up workspace tree, initialize task board
 │
 ▼
DECOMPOSE
 │  Analyze instructions + repo structure
 │  Create top-level tasks with dependencies
 │  Assign repos to tasks for multi-repo work
 │
 ▼
ORCHESTRATE (loop)
 │  While tasks remain:
 │    Spawn SubPlanners / Workers for ready tasks
 │    Receive handoffs from children
 │    Review handoffs → accept / retry / escalate
 │    Run optimistic merge on accepted handoffs
 │    Record error budget outcomes
 │    Rewrite scratchpad with current state
 │    Check watchdog reports, handle failures
 │
 ▼
RECONCILE
 │  Run full test suite on canonical repo
 │  Parse failures → spawn targeted fixers
 │  Re-merge fixer outputs → re-test
 │  Max N rounds (default: 3)
 │
 ▼
DONE
   Snapshot green branch (if tests pass)
   Generate final report
```

### Worker Lifecycle

```
SPAWN
 │  Receive task assignment + AgentConfig
 │  Create workspace (copy of target repo)
 │  Capture base commit hash
 │
 ▼
EXECUTE (agent loop)
 │  While stop_reason == "tool_use":
 │    Call LLM with task context + tools
 │    Execute tool calls (bash, read, write, edit)
 │    Append results to messages
 │    Heartbeat to activity log
 │    Maybe rewrite scratchpad (every N turns)
 │    Maybe auto-summarize (at 80% context)
 │
 ▼
HANDOFF
 │  Compute diff against base commit
 │  Build Handoff with status, diff, narrative, metrics
 │  Submit to parent's inbox
 │
 ▼
CLEANUP
   Remove workspace (if configured)
```

## Tool Registry

Tools are registered per-role. The registry maps tool names to handler functions and provides the LLM-facing schema.

### Planner Tools

| Tool | Parameters | Returns |
|------|-----------|---------|
| spawn_worker | task_id, instructions | worker_id |
| spawn_sub_planner | scope, instructions | sub_planner_id |
| review_handoff | handoff_id | handoff summary |
| accept_handoff | handoff_id | merge result |
| reject_handoff | handoff_id, reason | retry task |
| rewrite_scratchpad | content | confirmation |
| read_scratchpad | | current scratchpad |
| send_message | agent_id, content | confirmation |
| read_inbox | | list of messages |
| list_agents | | agent statuses |
| get_error_budget | | current error zone + stats |

### Worker Tools

| Tool | Parameters | Returns |
|------|-----------|---------|
| bash | command | stdout + stderr + exit code |
| read_file | path, offset, limit | file contents |
| write_file | path, content | confirmation |
| edit_file | path, old_string, new_string | confirmation |
| submit_handoff | status, narrative | confirmation |
| rewrite_scratchpad | content | confirmation |
| read_scratchpad | | current scratchpad |

## Multi-Codebase Support

When `repos` contains multiple paths, the harness:

1. Root Planner receives all repo paths in its context
2. Decomposition assigns each task a `repo` field
3. SubPlanners are scoped to a single repo (or cross-repo coordination)
4. Workers get a workspace copy of their assigned repo only
5. Merge happens per-repo against each repo's canonical
6. Reconciliation runs per-repo test suites, then cross-repo integration tests

```
repos: ["./api-server", "./frontend"]

Root Planner
├── SubPlanner (api-server) ──► Workers with api-server copies
├── SubPlanner (frontend) ──► Workers with frontend copies
└── Cross-repo integration tasks (after per-repo work)
```

## Git Integration

### Workspace Creation

```python
def create_workspace(repo_path: str, worker_id: str) -> Workspace:
    workspace_path = f".workspaces/{worker_id}"
    # Option A: Full copy (simple, wasteful)
    shutil.copytree(repo_path, workspace_path, ignore=shutil.ignore_patterns('.git'))
    # Option B: git worktree (efficient, shares .git)
    subprocess.run(["git", "worktree", "add", workspace_path, "HEAD"], cwd=repo_path)
    base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True).stdout.strip()
    return Workspace(worker_id=worker_id, repo_path=repo_path, workspace_path=workspace_path, base_commit=base_commit)
```

### Diff Computation

```python
def compute_diff(workspace: Workspace) -> list[FileDiff]:
    # Compare workspace files against base commit
    result = subprocess.run(
        ["git", "diff", "--no-index", workspace.repo_path, workspace.workspace_path],
        capture_output=True, text=True
    )
    return parse_git_diff(result.stdout)
```

### Commit Creation

After successful merge + reconciliation:
```python
def commit_changes(repo_path: str, message: str, author: str = "harness") -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo_path)
    subprocess.run(["git", "commit", "-m", message, f"--author={author} <harness@local>"], cwd=repo_path)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True).stdout.strip()
```

## Concurrency Model

```
Main Thread
│
├── Orchestrator (manages lifecycle)
│   │
│   ├── Root Planner (agent loop in main or dedicated thread)
│   │
│   ├── Worker Pool (ThreadPoolExecutor)
│   │   ├── Worker-1 thread (own workspace, own agent loop)
│   │   ├── Worker-2 thread
│   │   └── Worker-N thread
│   │
│   └── Watchdog (daemon thread, polls worker activity)
│
└── Inbox/Outbox (thread-safe queues per agent)
```

Workers run in a ThreadPoolExecutor with max_workers from config. Each worker owns its thread, workspace, and agent loop. Communication happens via thread-safe message queues (not shared files as in the educational code).

## Long-Running Agent Coherence

The harness must maintain coherent state across extended execution periods (hours, thousands of LLM calls). This section defines six mechanisms that prevent drift, contradiction, and memory loss in long-running planner-worker hierarchies.

### State Reconstruction After Compression

After auto_compact, the planner has only a prose summary. It loses structured knowledge of worker states, pending handoffs, error budget, blocked tasks.

**Solution:** Define a `StateSnapshot` pydantic model that captures all critical runtime state. After every compression cycle, serialize the StateSnapshot and inject it as a structured `<state>` block alongside the prose summary.

```python
from pydantic import BaseModel
from typing import Optional


class WorkerSnapshot(BaseModel):
    """Snapshot of a single worker's state."""
    worker_id: str
    task_id: str | None
    status: str  # running, waiting, completed, failed
    tokens_used: int
    last_update: float  # wall time


class ErrorBudgetSnapshot(BaseModel):
    """Snapshot of error budget state."""
    zone: str  # healthy, warning, critical
    failure_rate: float
    window_size: int
    total_tasks: int
    failed_tasks: int


class TaskBoardSnapshot(BaseModel):
    """Snapshot of task board counts."""
    pending: int
    in_progress: int
    completed: int
    failed: int
    blocked: int
    blocked_task_ids: list[str]


class StateSnapshot(BaseModel):
    """Structured state that survives context compression."""
    active_workers: list[WorkerSnapshot]  # worker_id, task_id, status, tokens_used
    pending_handoffs: list[str]  # handoff IDs not yet merged
    error_budget: ErrorBudgetSnapshot  # zone, rate, window summary
    task_board: TaskBoardSnapshot  # counts by status, blocked tasks
    scratchpad_summary: str  # current scratchpad content (truncated)
    compression_count: int  # how many times we've compressed
    wall_time_elapsed: float
```

**Injection pattern:** after auto_compact, append `<state>{snapshot.model_dump_json()}</state>` to the compressed context.

```python
def compress_with_snapshot(messages: list[dict], snapshot: StateSnapshot) -> list[dict]:
    compressed = auto_compact(messages)  # existing compression logic
    state_block = f"<state>{snapshot.model_dump_json()}</state>"
    compressed.append({"role": "user", "content": state_block})
    return compressed
```

**Config addition:**

```python
class AgentLimitsConfig(BaseSettings):
    # ... existing fields ...
    state_snapshot_enabled: bool = Field(default=True, description="Inject StateSnapshot after compression")
```

### Mandatory Scratchpad Schema

Without enforced structure, scratchpad content drifts from reality over many turns.

**Solution:** Define required sections that every scratchpad rewrite must contain. Validate on write.

Required schema:

```
## Goal
(immutable — copied from original task assignment)
## Active Workers
(structured: worker_id | task_id | status | last_update)
## Pending Handoffs
(handoffs received but not yet merged)
## Error Budget
(zone, failure_rate, window_size)
## Blockers
(what can't proceed and why)
## Next Action
(single concrete next step)
```

**Pydantic validator:**

```python
from pydantic import BaseModel, field_validator


class ScratchpadSchema(BaseModel):
    """Enforced scratchpad structure."""
    goal: str
    active_workers: list[dict]  # worker_id, task_id, status, last_update
    pending_handoffs: list[str]
    error_budget_zone: str
    blockers: list[str]
    next_action: str

    @field_validator("goal", "next_action")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("active_workers", "pending_handoffs", "blockers")
    @classmethod
    def not_none(cls, v) -> list:
        if v is None:
            return []
        return v
```

**Config addition:**

```python
class AgentLimitsConfig(BaseSettings):
    # ... existing fields ...
    scratchpad_schema_enforced: bool = Field(default=True, description="Require structured scratchpad format")
```

### Completion Verification Gate

The planner can declare "done" (stop_reason != "tool_use") without actual verification. Premature completion is the most common failure mode.

**Solution:** Add a `declare_done` tool that runs a completion checklist before accepting. The agent loop should NOT exit on stop_reason alone — it should only exit when declare_done returns success.

```python
from pydantic import BaseModel


class CompletionChecklist(BaseModel):
    """Verification gate before accepting completion."""
    all_tasks_terminal: bool  # all COMPLETED or CANCELLED
    no_workers_running: bool  # no workers in RUNNING state
    error_budget_healthy: bool  # zone != CRITICAL
    reconciliation_passed: bool  # last reconcile verdict = PASS
    pending_handoffs_empty: bool  # all handoffs merged or rejected

    def is_complete(self) -> tuple[bool, list[str]]:
        """Returns (passed, list of failure reasons)."""
        failures = []
        if not self.all_tasks_terminal:
            failures.append("not_all_tasks_terminal")
        if not self.no_workers_running:
            failures.append("workers_still_running")
        if not self.error_budget_healthy:
            failures.append("error_budget_critical")
        if not self.reconciliation_passed:
            failures.append("reconciliation_not_passed")
        if not self.pending_handoffs_empty:
            failures.append("pending_handoffs_exist")
        return (len(failures) == 0, failures)
```

**Gate logic:** if any check fails, inject `<completion_blocked reason="...">` and continue the loop.

```python
def check_completion(harness_state: HarnessState) -> tuple[bool, str]:
    checklist = CompletionChecklist(
        all_tasks_terminal=all(t.status in ("COMPLETED", "CANCELLED") for t in harness_state.tasks),
        no_workers_running=all(w.status != "running" for w in harness_state.workers.values()),
        error_budget_healthy=harness_state.error_budget.zone != "critical",
        reconciliation_passed=harness_state.reconciliation.final_verdict == "pass",
        pending_handoffs_empty=len(harness_state.pending_handoffs) == 0,
    )
    passed, failures = checklist.is_complete()
    if not passed:
        return False, f"completion_blocked: {', '.join(failures)}"
    return True, "completion_approved"
```

**Config addition:**

```python
class HarnessConfig(BaseSettings):
    # ... existing fields ...
    require_completion_gate: bool = Field(default=True, description="Run completion checklist before exit")
```

### Downward Context Updates

When Worker A's changes affect Worker B's task, Worker B has no way to learn this mid-execution.

**Solution:** The planner pushes ContextUpdate messages to running workers via their inbox. Workers check inbox between LLM calls and inject updates into their context.

```python
from pydantic import BaseModel
from typing import Literal


class ContextUpdate(BaseModel):
    """Push update from planner to worker."""
    source_task_id: str  # which task caused this update
    affected_workers: list[str]
    message: str  # what changed and why it matters
    priority: Literal["info", "warning", "critical"] = "info"
```

**Trigger pattern:** after each successful merge, the planner scans running workers for task overlap and sends updates.

```python
def send_context_updates(merge_result: MergeResult, workers: dict[str, WorkerState]) -> None:
    # Find workers whose tasks may be affected by this merge
    affected = []
    for worker_id, worker in workers.items():
        if worker.task_id in merge_result.affected_task_ids:
            affected.append(worker_id)
    
    if affected:
        update = ContextUpdate(
            source_task_id=merge_result.task_id,
            affected_workers=affected,
            message=f"Task {merge_result.task_id} merged. Files: {merge_result.files_merged}",
            priority="warning",
        )
        for worker_id in affected:
            workers[worker_id].inbox.append(update)
```

Workers receive as `<context_update priority="warning">...</context_update>` in their message stream.

```python
def worker_loop_with_context_updates(worker: WorkerState) -> None:
    while worker.running:
        # Check for context updates before LLM call
        updates = drain_inbox(worker.inbox)
        for update in updates:
            worker.messages.append({
                "role": "user",
                "content": f"<context_update priority=\"{update.priority}\">{update.message}</context_update>"
            })
        
        # Normal agent loop
        response = llm_call(worker.messages)
        # ... process response ...
```

### Planner Loop Bounds

The planner loop has no upper bound. It can run forever, burning tokens without progress.

**Solution:** Hard limits on turns and wall time. When hit: forced reconciliation, snapshot, report, exit.

```
┌─────────────────────────────────────────┐
│         Planner Loop Bounds              │
├─────────────────────────────────────────┤
│  max_planner_turns: 200 (default)       │
│  max_wall_time_seconds: 3600 (1 hour)   │
├─────────────────────────────────────────┤
│  On limit hit:                          │
│  1. Force reconcile                     │
│  2. Snapshot if pass                     │
│  3. Generate final report               │
│  4. Exit with status code               │
└─────────────────────────────────────────┘
```

**Config additions:**

```python
class AgentLimitsConfig(BaseSettings):
    # ... existing fields ...
    max_planner_turns: int = Field(default=200, description="Max planner loop iterations")
    max_wall_time_seconds: int = Field(default=3600, description="Max wall time for planner")
    forced_reconcile_on_limit: bool = Field(default=True, description="Run reconciliation before exit on limit")
```

**Exit sequence:**

```python
def check_planner_limits(harness_state: HarnessState, config: HarnessConfig) -> bool:
    """Returns True if limits exceeded."""
    if harness_state.planner_turns >= config.max_planner_turns:
        return True
    if harness_state.wall_time_elapsed >= config.max_wall_time_seconds:
        return True
    return False


def handle_limit_exceeded(harness_state: HarnessState, config: HarnessConfig) -> None:
    logger.warning(f"Planner limits exceeded: turns={harness_state.planner_turns}, "
                   f"time={harness_state.wall_time_elapsed:.1f}s")
    
    if config.forced_reconcile_on_limit:
        logger.info("Running forced reconciliation...")
        report = run_reconciliation(harness_state)
        harness_state.reconciliation = report
    
    # Generate snapshot if reconciliation passed
    if harness_state.reconciliation.final_verdict == "pass":
        snapshot = create_green_snapshot(harness_state)
        save_snapshot(snapshot)
    
    # Final report
    report = generate_final_report(harness_state)
    logger.info(f"Final report: {report.summary}")
    
    # Exit with status code
    sys.exit(0 if harness_state.reconciliation.final_verdict == "pass" else 1)
```

### Duplicate Work Prevention (Idempotency)

After compression, the planner has lost fine-grained history and may re-spawn workers for completed tasks, merge handoffs twice, or create duplicate tasks.

**Solution:** System-level idempotency checks that reject duplicates regardless of planner memory.

```
┌─────────────────────────────────────────┐
│       Idempotency Guard Layer            │
├─────────────────────────────────────────┤
│  spawn_worker                           │
│   └── reject if task_id has COMPLETED   │
├─────────────────────────────────────────┤
│  optimistic_merge                       │
│   └── reject if handoff_id already      │
│       merged (track merged IDs)         │
├─────────────────────────────────────────┤
│  task_create                           │
│   └── reject if identical               │
│       title+description exists          │
└─────────────────────────────────────────┘
```

**Guard implementation:**

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class IdempotencyGuard:
    """Tracks completed operations to prevent duplicates."""
    completed_tasks: set[str] = field(default_factory=set)  # task_id -> completed
    merged_handoffs: set[str] = field(default_factory=set)  # handoff_id -> merged
    created_tasks: dict[str, str] = field(default_factory=dict)  # (title, desc) hash -> task_id
    
    def can_spawn_worker(self, task_id: str) -> bool:
        """Reject if task already completed."""
        return task_id not in self.completed_tasks
    
    def mark_worker_completed(self, task_id: str, handoff_id: str) -> None:
        """Record task completion and its final handoff."""
        self.completed_tasks.add(task_id)
        self.merged_handoffs.add(handoff_id)
    
    def can_merge_handoff(self, handoff_id: str) -> bool:
        """Reject if handoff already merged."""
        return handoff_id not in self.merged_handoffs
    
    def mark_handoff_merged(self, handoff_id: str) -> None:
        """Record handoff merge."""
        self.merged_handoffs.add(handoff_id)
    
    def can_create_task(self, title: str, description: str) -> bool:
        """Reject if identical task exists."""
        key = hash((title.strip().lower(), description.strip().lower()))
        return key not in self.created_tasks
    
    def mark_task_created(self, title: str, description: str, task_id: str) -> None:
        """Record task creation."""
        key = hash((title.strip().lower(), description.strip().lower()))
        self.created_tasks[key] = task_id
```

**Integration:**

```python
def spawn_worker(task_id: str, config: AgentConfig, guard: IdempotencyGuard) -> str | None:
    if not guard.can_spawn_worker(task_id):
        logger.warning(f"Rejecting spawn_worker: task {task_id} already completed")
        return None
    # ... normal spawn logic ...


def optimistic_merge(handoff: Handoff, guard: IdempotencyGuard) -> MergeResult:
    if not guard.can_merge_handoff(handoff.id):
        logger.warning(f"Rejecting merge: handoff {handoff.id} already merged")
        return MergeResult(worker_id=handoff.agent_id, status=MergeStatus.NO_CHANGES)
    # ... normal merge logic ...
    guard.mark_handoff_merged(handoff.id)
```

**Config addition:** No new config needed — this is an internal guard layer.

## Open Questions

1. **git worktree vs full copy** — Worktrees are efficient but share .git locks. Full copies are simpler but wasteful for large repos. Start with full copy, measure, optimize later.

2. **Token counting accuracy** — Anthropic SDK provides input/output token counts per response. Accumulate these for budget tracking. No need for local tokenizer.

3. **Scratchpad storage** — File-based (like educational code) or in-memory dict? File-based survives crashes but adds I/O. Start with in-memory, add file persistence as needed.

4. **Test suite discovery** — How does the harness know what test command to run for reconciliation? Config field `test_command: str = "pytest"`. User specifies per-repo.

5. **Merge conflict resolution** — Current design spawns a FixForwardTask. Should the fixer get both versions (base + conflicting) in its context? Yes — include full conflict markers.

6. **StateSnapshot granularity** — Should StateSnapshot include full message history summaries or only structural state? Current design captures structural state only. Could add optional message_summary field for debugging.

7. **ContextUpdate frequency** — Should workers receive context updates after every merge or batched? Current design sends immediately. Batching may reduce noise but increases staleness risk.

8. **Idempotency persistence** — Should IdempotencyGuard state survive harness restarts? Current design is in-memory only. File-based persistence would enable crash recovery but adds complexity.

## Alternatives Considered

### Flat agent pool (rejected)
Cursor tried equal-role agents with shared coordination file. Failed due to lock contention, lack of ownership, and agents avoiding complex work. Sessions s09-s11 demonstrate this path.

### Single executor with many roles (rejected)
Cursor tried giving one agent all roles (plan, explore, spawn, review, merge, judge). Created pathological behaviors: random sleeping, premature completion claims, refusal to delegate. Session s14 formalizes the separation.

### Central integrator/reviewer (rejected)
A single agent reviewing all merges became an obvious bottleneck with hundreds of workers. Removed in favor of optimistic merge + reconciliation pass. Session s16 implements this.

### asyncio-only (deferred)
Pure async would be cleaner but requires async Anthropic client and careful management. Threading is simpler for the educational scope. The models module is sync-agnostic (pydantic models don't care about concurrency).

---

*This document specifies the design of the harness package. Implementation follows the incremental approach defined in the testing strategy.*
