# Coherence Mechanisms Appendix

This appendix traces the nine coherence mechanisms introduced across sessions s13-s20. Each mechanism addresses a specific failure mode that emerges when agents run for extended periods. Together they form an interlocking safety net that keeps multi-agent orchestration on track.


## Mechanism Reference

### 1. StateSnapshot (s13)

**Problem**: After context compression, the planner loses track of task board counts, worker status, and error budget state. The LLM cannot reconstruct what happened from compacted tool results.

**Session introduced**: s13 (Scratchpad Rewriting)

**Implementation**:

```
src/harness/models/state.py       -- StateSnapshot, TaskBoardSnapshot, WorkerSnapshot, ErrorBudgetSnapshot
src/harness/orchestration/compression.py -- auto_compact() injects StateSnapshot into compressed messages
```

**Key classes**:

```python
class StateSnapshot(BaseModel):
    turn_number: int
    total_tokens: int
    task_board: TaskBoardSnapshot
    workers: list[WorkerSnapshot] = []
    error_budget: ErrorBudgetSnapshot | None = None
    scratchpad_summary: str = ""
```

**Freshness strategy**: TaskBoardSnapshot counts are computed eagerly (cheap integer sums). WorkerSnapshots are lazy (only built when compression triggers). ErrorBudgetSnapshot is included when the error budget exists.

**Interaction**: Consumed by `auto_compact()` in compression.py. The snapshot is serialized via `model_dump_json()` and prepended to the compressed message list as a synthetic user message with `[state_snapshot]` prefix.


### 2. ScratchpadSchema (s13)

**Problem**: Without structure enforcement, planner scratchpads drift into unstructured notes that omit critical tracking sections. After compression, the planner cannot recover its plan.

**Session introduced**: s13 (Scratchpad Rewriting)

**Implementation**:

```
src/harness/orchestration/scratchpad.py -- Scratchpad class with REQUIRED_SECTIONS and validate()
```

**Key class**:

```python
class Scratchpad:
    REQUIRED_SECTIONS = [
        "## Goal",
        "## Active Workers",
        "## Pending Handoffs",
        "## Error Budget",
        "## Blockers",
        "## Next Action",
    ]
```

**Validation**: `validate(content)` returns `(bool, list[str])` -- True if all required sections present, or False with the list of missing section headers. Validation is advisory: the scratchpad is still written even if sections are missing, but a warning is returned to the planner.

**Interaction**: Called by `HarnessRunner._handle_rewrite_scratchpad()` in runner.py. The planner receives feedback about missing sections and can correct on the next rewrite. Scratchpad content feeds into `StateSnapshot.scratchpad_summary` during compression.


### 3. CompletionGate (s14)

**Problem**: The planner declares "done" prematurely -- workers still running, handoffs unmerged, tasks incomplete. Without a formal gate, the harness exits with partial work.

**Session introduced**: s14 (Planner-Worker Split)

**Implementation**:

```
src/harness/models/coherence.py        -- CompletionChecklist
src/harness/orchestration/idempotency.py -- CompletionGate.declare_done()
```

**Key class**:

```python
class CompletionChecklist(BaseModel):
    all_tasks_terminal: bool = False
    no_workers_running: bool = False
    error_budget_healthy: bool = False
    reconciliation_passed: bool = False
    pending_handoffs_empty: bool = False
```

**Gate logic**: `is_complete()` returns `(True, [])` only when all five conditions hold. Otherwise returns `(False, [list of failing conditions])`. The planner receives the failing conditions and must address them before the harness will exit cleanly.

**Interaction**: Used by `RootPlanner.check_completion()`. Depends on ErrorBudget (mechanism 7) for the `error_budget_healthy` check. Depends on reconciliation (mechanism 9) for `reconciliation_passed`.


### 4. Planner Loop Bounds (s14)

**Problem**: A planner stuck in a reasoning loop burns tokens indefinitely without spawning workers or making progress. Without bounds, the harness runs until the API key runs out.

**Session introduced**: s14 (Planner-Worker Split)

**Implementation**:

```
src/harness/agents/planner.py -- RootPlanner.is_over_limits(), max_planner_turns, max_wall_time_seconds
src/harness/agents/base.py    -- BaseAgent.run() checks token_budget and timeout_seconds
```

**Bounds enforced**:

- `max_planner_turns` (default 50): Hard cap on LLM call iterations
- `max_wall_time_seconds` (default 600): Wall clock timeout
- `token_budget` (from AgentConfig): Maximum cumulative tokens consumed
- `timeout_seconds` (from AgentConfig): Per-agent timeout

**Interaction**: When any bound is hit, the planner exits its loop and calls `on_loop_exit()`. The runner then joins any remaining worker threads and renders the final task board. CompletionGate (mechanism 3) may report incomplete if the planner timed out before all tasks finished.


### 5. ContextUpdate (s14)

**Problem**: Workers running in threads cannot receive new information from the planner after being spawned. If the planner discovers a dependency change or priority shift, workers are oblivious.

**Session introduced**: s14 (Planner-Worker Split)

**Implementation**:

```
src/harness/models/coherence.py -- ContextUpdate model
```

**Key class**:

```python
class ContextUpdate(BaseModel):
    agent_id: str
    content: str
    priority: str = "info"
    timestamp: datetime
```

**Delivery mechanism**: Thread-safe queue per worker. The planner enqueues `ContextUpdate` messages; workers drain the queue before each LLM call. In the current implementation, the model is defined but queue wiring is minimal -- workers receive their full instructions at spawn time via the system prompt.

**Interaction**: Conceptually feeds into worker `on_before_llm_call()` hooks in base.py. In production usage, workers would check their queue and inject updates into their message list.


### 6. IdempotencyGuard (s16)

**Problem**: After context compression, the planner forgets it already spawned a worker for task X and spawns a duplicate. Similarly, it may attempt to merge the same handoff twice or create duplicate tasks.

**Session introduced**: s16 (Optimistic Merge)

**Implementation**:

```
src/harness/models/coherence.py -- IdempotencyGuard class
```

**Key class**:

```python
class IdempotencyGuard:
    _spawned_workers: set[str]
    _merged_handoffs: set[str]
    _created_tasks: dict[str, str]
```

**Guards provided**:

- `can_spawn_worker(task_id)` / `mark_worker_spawned(task_id)`
- `can_merge_handoff(handoff_id)` / `mark_handoff_merged(handoff_id)`
- `can_create_task(title)` / `mark_task_created(title)`

**Persistence**: Optional file-based persistence via `load_from_file(path)` and `save_to_file(path)` for checkpoint/resume across graceful shutdowns. Serializes to `.idempotency.json`.

**Interaction**: Used by `RootPlanner.can_spawn_worker()` and `RootPlanner.spawn_worker()`. The runner's `_handle_spawn_worker()` also guards against duplicate spawns via its own `_workers` dict check. The guard survives compression because it lives outside the message history.


### 7. Error Budget Snapshots in StateSnapshot (s18)

**Problem**: The planner needs to know failure rates to decide whether to continue, abort, or switch strategies. After compression, error budget state is lost from the message history.

**Session introduced**: s18 (Error Tolerance)

**Implementation**:

```
src/harness/models/error_budget.py -- ErrorBudget, ErrorZone
src/harness/models/state.py        -- ErrorBudgetSnapshot (embedded in StateSnapshot)
```

**Key classes**:

```python
class ErrorBudget(BaseModel):
    window: list[bool]       # sliding window of success/failure
    window_size: int = 20
    budget_percentage: float = 0.15
    zone: ErrorZone          # HEALTHY / WARNING / CRITICAL

class ErrorBudgetSnapshot(BaseModel):
    zone: str
    failure_rate: float
    total: int
    failed: int
```

**Zone transitions**: `record(success)` appends to the sliding window and recalculates zone. Rate > budget_percentage triggers CRITICAL. Rate > 50% of budget triggers WARNING. Otherwise HEALTHY.

**Interaction**: ErrorBudget is owned by HarnessRunner. The runner calls `record(success=True)` on accept_handoff and `record(success=False)` on reject_handoff. The planner reads it via `get_error_budget` tool. ErrorBudgetSnapshot is embedded in StateSnapshot for compression survival. CompletionGate (mechanism 3) checks `error_budget_healthy` which fails if zone is CRITICAL.


### 8. Watchdog Pattern Analysis (s19)

**Problem**: Workers exhibit three failure modes that the planner cannot detect from handoffs alone: zombie (no activity), tunnel vision (editing the same file repeatedly), and token burn (consuming tokens without tool calls).

**Session introduced**: s19 (Failure Modes & Recovery)

**Implementation**:

```
src/harness/agents/watchdog.py  -- Watchdog class with check_agents()
src/harness/models/watchdog.py  -- ActivityEntry, FailureMode, WatchdogEvent
src/harness/config.py           -- WatchdogConfig thresholds
```

**Detection patterns**:

```
Zombie:         last_activity age > zombie_timeout_seconds (default 60s)
Tunnel vision:  single file touched > tunnel_vision_threshold times (default 20)
Token burn:     tokens > token_burn_threshold (default 16000) with no tool calls
```

**Key flow**: `record_activity(entry)` accumulates ActivityEntry records per agent. `check_agents()` scans all agents against the three patterns. Detected failures produce WatchdogEvent and emit WatchdogAlert via the EventBus.

**Interaction**: Emits events consumed by RichRenderer for CLI display. In a production harness, watchdog events would trigger worker kills and task re-queuing. The watchdog runs independently of the planner loop -- it can be polled periodically via `poll_interval_seconds`.


### 9. Fixer Loop Bounds (s20)

**Problem**: The reconciliation pass (run tests, spawn fixer, re-run tests) can loop indefinitely if the fixer introduces new bugs while fixing old ones.

**Session introduced**: s20 (Reconciliation Pass)

**Implementation**:

```
src/harness/orchestration/reconcile.py -- reconcile() function with max_rounds parameter
```

**Key function**:

```python
def reconcile(
    repo_path: str,
    test_command: str,
    max_rounds: int = 3,            # HARD CAP
    spawn_fixer_fn: Callable | None = None,
) -> ReconciliationReport:
```

**Loop behavior**: Each round runs the test command. If exit code is 0, returns `final_verdict="pass"` with the green commit marker. If non-zero, collects failures and calls `spawn_fixer_fn` with the failure list. After `max_rounds` attempts without green, returns `final_verdict="fail"`.

**Interaction**: ReconciliationReport feeds into CompletionGate (mechanism 3) via the `reconciliation_passed` flag. The hard cap of 3 rounds is an architecture decision (see CLAUDE.md decision #8).


## Mechanism Interaction Diagram

```
                    +-------------------+
                    |   Planner Loop    |
                    |   Bounds (#4)     |
                    +--------+----------+
                             |
                    max_turns / wall_time exceeded
                             |
                             v
+----------------+    +------+-------+    +------------------+
| IdempotencyGuard|<---|  RootPlanner  |--->| ScratchpadSchema |
|     (#6)       |    |              |    |      (#2)        |
+----------------+    +------+-------+    +------------------+
  prevents dupes             |                    |
  after compression          |              validates sections
                             |                    |
                    +--------v--------+    +------v---------+
                    | spawn_worker    |    | rewrite_       |
                    | review_handoff  |    | scratchpad     |
                    | accept/reject   |    +------+---------+
                    +--------+--------+           |
                             |              feeds into
                    +--------v--------+    +------v---------+
                    |  ErrorBudget    |    | StateSnapshot  |
                    |     (#7)       |    |     (#1)       |
                    +--------+--------+    +------+---------+
                             |                    |
                    zone changes           injected after
                             |              compression
                    +--------v--------+           |
                    | CompletionGate  |<----------+
                    |     (#3)       |
                    +--------+--------+
                             |
                    requires all conditions
                             |
                    +--------v--------+    +------------------+
                    | Reconciliation  |    |    Watchdog      |
                    | Fixer Loop (#9) |    |      (#8)        |
                    +-----------------+    +------------------+
                      max 3 rounds           zombie / tunnel
                      feeds gate             vision / burn
                                             detection
```


## Activation Timeline

During a typical harness run, mechanisms activate in this order:

```
Time -->

START
  |
  |  [Planner Loop Bounds (#4)] -- armed at planner creation
  |  [IdempotencyGuard (#6)]    -- armed at planner creation
  |
  |-- Planner: rewrite_scratchpad
  |     [ScratchpadSchema (#2)] -- validates required sections
  |
  |-- Planner: create_task, spawn_worker
  |     [IdempotencyGuard (#6)] -- checks for duplicate spawns
  |     [Watchdog (#8)]         -- starts recording worker activity
  |
  |-- Workers: execute tasks in threads
  |     [ContextUpdate (#5)]    -- planner can push updates (if wired)
  |     [Watchdog (#8)]         -- monitors for zombie/tunnel/burn
  |
  |-- Planner: review_handoff, accept/reject
  |     [ErrorBudget (#7)]      -- records success/failure per handoff
  |
  |-- (if token threshold exceeded) Context Compression
  |     [StateSnapshot (#1)]    -- snapshot injected into compressed messages
  |     [ScratchpadSchema (#2)] -- scratchpad_summary preserved in snapshot
  |     [ErrorBudget (#7)]      -- ErrorBudgetSnapshot embedded in state
  |
  |-- Planner: check_completion
  |     [CompletionGate (#3)]   -- verifies all 5 conditions
  |     [Reconciliation (#9)]   -- fixer loop if tests fail (max 3 rounds)
  |
  |-- (if bounds hit) Planner forced exit
  |     [Planner Loop Bounds (#4)] -- max_turns or wall_time exceeded
  |
END
```


## Mechanism Dependencies

Which mechanisms depend on which:

```
Mechanism               Depends On              Depended On By
---------               ----------              --------------
StateSnapshot (#1)      ErrorBudget (#7)        Compression pipeline
                        Scratchpad (#2)
ScratchpadSchema (#2)   (none)                  StateSnapshot (#1)
CompletionGate (#3)     ErrorBudget (#7)        Planner exit logic
                        Reconciliation (#9)
Planner Bounds (#4)     (none)                  Planner loop
ContextUpdate (#5)      (none)                  Worker loop (optional)
IdempotencyGuard (#6)   (none)                  Planner spawn/create
ErrorBudget (#7)        (none)                  StateSnapshot (#1)
                                                CompletionGate (#3)
Watchdog (#8)           EventBus                RichRenderer (display)
Fixer Loop (#9)         (none)                  CompletionGate (#3)
```


## Design Decisions Referenced

These architecture decisions from CLAUDE.md constrain the mechanism implementations:

- **Decision #6**: Strict scratchpad validation on required sections, advisory on optional
- **Decision #7**: ABANDONED as TaskStatus enum value (not a separate tool)
- **Decision #8**: Hard cap of 3 fixer rounds in reconciliation
- **Decision #9**: Watchdog uses metrics + output pattern analysis
- **Decision #10**: Uniform model for all roles (single model from config)
- **Decision #12**: Signal handler + checkpoint + resume for graceful shutdown (IdempotencyGuard persists to `.idempotency.json`)
