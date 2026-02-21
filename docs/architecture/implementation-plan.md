# Harness Implementation Plan

Ultra Work Loop execution plan for building `src/harness/` package and `tests/python/` suite. Follows the layer-by-layer testing strategy — no layer skipped.

Source material: `agents/s_full.py` (2550 lines), `docs/architecture/design-doc.md`, `docs/architecture/testing-strategy.md`.

---

## Phase 1: Foundation (Layers 0-1)

### Step 1: Core Pydantic Models — Task, Handoff, Agent

**Files**: `src/harness/models/__init__.py`, `src/harness/models/task.py`, `src/harness/models/handoff.py`, `src/harness/models/agent.py`
**Depends on**: nothing
**Extract from**: design-doc.md "Core Pydantic Models" sections; s_full.py StructuredHandoff*, TaskManager patterns

**Implementation**:
- Create `src/harness/models/__init__.py` that re-exports all model classes
- `task.py`: TaskStatus enum (PENDING, CLAIMED, IN_PROGRESS, COMPLETED, FAILED, BLOCKED, ABANDONED), TaskPriority enum (CRITICAL, HIGH, NORMAL, LOW), Task model with all fields from design doc
- `handoff.py`: HandoffStatus enum, FileDiff model, HandoffMetrics model, Handoff model with narrative as required field
- `agent.py`: AgentRole enum (ROOT_PLANNER, SUB_PLANNER, WORKER, WATCHDOG), AgentState enum, AgentConfig model

**Tests**: `tests/python/test_models.py`
- Task defaults (status=PENDING, priority=NORMAL, assigned_to=None, blocked_by=[])
- Task blocked_by validation
- Task serialization roundtrip (model_dump -> model_validate)
- Task JSON roundtrip (model_dump_json -> model_validate_json)
- Handoff requires non-empty narrative (add validator)
- Handoff with diffs
- HandoffMetrics defaults (tool_calls=0)
- AgentRole enum values
- AgentConfig defaults (depth=0, token_budget=100_000)
- All enum .value checks

**Done when**:
- `uv run pytest tests/python/test_models.py -v` passes
- `uv run ruff check src/harness/models/` clean

---

### Step 2: Core Pydantic Models — Workspace, Merge, ErrorBudget, Watchdog

**Files**: `src/harness/models/workspace.py`, `src/harness/models/merge.py`, `src/harness/models/error_budget.py`, `src/harness/models/watchdog.py`
**Depends on**: Step 1
**Extract from**: design-doc.md model sections; s_full.py ErrorPolicy, WorkerWorkspace, optimistic_merge, Watchdog

**Implementation**:
- `workspace.py`: WorkspaceState enum (CREATING, READY, IN_USE, MERGING, CLEANED), Workspace model
- `merge.py`: MergeStatus enum (CLEAN, CONFLICT, NO_CHANGES), MergeResult model (with optional fix_forward_task: Task | None), ReconciliationRound model, ReconciliationReport model
- `error_budget.py`: ErrorZone enum, ErrorBudget model with failure_rate property, record() method, sliding window logic
- `watchdog.py`: FailureMode enum (ZOMBIE, TUNNEL_VISION, TOKEN_BURN, SCOPE_CREEP), WatchdogEvent model, ActivityEntry model

**Tests**: `tests/python/test_models.py` (append to existing)
- WorkspaceState enum values
- Workspace defaults (state=CREATING)
- MergeResult with/without fix_forward_task
- ReconciliationReport defaults (final_verdict="pending")
- ErrorBudget healthy zone (all successes -> HEALTHY, rate=0.0)
- ErrorBudget critical zone (many failures -> CRITICAL)
- ErrorBudget sliding window (old failures fall off)
- ErrorBudget window_size enforcement
- FailureMode enum values
- ActivityEntry defaults (tokens_used=0, files_touched=[])

**Done when**:
- `uv run pytest tests/python/test_models.py -v` passes (all Layer 0)
- `uv run ruff check src/harness/models/` clean

---

### Step 3: Coherence Models — StateSnapshot, ScratchpadSchema, CompletionChecklist, Idempotency

**Files**: `src/harness/models/state.py`, `src/harness/models/scratchpad.py`, `src/harness/models/coherence.py`
**Depends on**: Steps 1-2
**Extract from**: design-doc.md "Long-Running Agent Coherence" section; s_full.py ScratchpadManager

**Implementation**:
- `state.py`: WorkerSnapshot, ErrorBudgetSnapshot, TaskBoardSnapshot, StateSnapshot models
- `scratchpad.py`: ScratchpadSchema with field validators (goal/next_action not empty, lists default to [])
- `coherence.py`: CompletionChecklist with is_complete() method, ContextUpdate model, IdempotencyGuard (dataclass with can_spawn_worker, can_merge_handoff, can_create_task, mark_* methods, optional JSON file persistence)

**Tests**: `tests/python/test_models.py` (append)
- StateSnapshot serialization roundtrip
- TaskBoardSnapshot all counts default to 0
- ScratchpadSchema rejects empty goal
- ScratchpadSchema rejects empty next_action
- ScratchpadSchema defaults lists to []
- CompletionChecklist.is_complete() returns (True, []) when all True
- CompletionChecklist.is_complete() returns (False, reasons) when any False
- ContextUpdate priority defaults to "info"
- IdempotencyGuard: can_spawn_worker True for new task, False after mark
- IdempotencyGuard: can_merge_handoff True for new handoff, False after mark
- IdempotencyGuard: can_create_task True for new title, False for duplicate
- IdempotencyGuard: file persistence save/load roundtrip

**Done when**:
- `uv run pytest tests/python/test_models.py -v` passes (30+ tests total)
- `uv run ruff check src/harness/models/` clean

---

### Step 4: Configuration — HarnessConfig + pydantic-settings

**Files**: `src/harness/config.py`, `tests/python/test_config.py`, `tests/python/conftest.py`
**Depends on**: Steps 1-3
**Extract from**: design-doc.md "Configuration" section

**Implementation**:
- `config.py`: LLMConfig, WorkspaceConfig, AgentLimitsConfig, ErrorPolicyConfig, WatchdogConfig, HarnessConfig — all as BaseSettings with env_prefix
- `conftest.py`: pytest markers (e2e, slow), common fixtures (tmp_path-based git repo, mock config factory)

**Tests**: `tests/python/test_config.py`
- HarnessConfig defaults (max_workers=10, max_depth=3, budget_percentage=0.15, watchdog enabled)
- Load from .env file (write tmp .env, load, verify)
- Env var override (monkeypatch LLM_API_KEY, AGENT_MAX_WORKERS)
- Nested config access (config.llm.api_key, config.agents.max_workers)
- Type coercion (string "10" -> int 10)
- All sub-configs have correct env_prefix

**Done when**:
- `uv run pytest tests/python/test_config.py -v` passes
- `uv run pytest tests/python/ -v` passes (all Layer 0 + Layer 1)
- `uv run ruff check src/harness/` clean

---

## Phase 2: Tools + Git (Layers 2-3)

### Step 5: Tool Handlers — Worker Tools

**Files**: `src/harness/tools/__init__.py`, `src/harness/tools/worker_tools.py`, `tests/python/test_tools.py`
**Depends on**: Step 4
**Extract from**: s_full.py run_bash, run_read, run_write, run_edit, _worker_exec

**Implementation**:
- `worker_tools.py`: bash_handler (command execution, exit code, stderr capture, timeout, dangerous command blocking), read_file_handler (path, offset, limit, missing file error), write_file_handler (create new, overwrite), edit_file_handler (find and replace, missing old_string error), submit_handoff_handler (builds Handoff model)
- Each handler returns a dict with structured output (not raw strings)
- Handlers accept workspace_path parameter for sandboxed execution

**Tests**: `tests/python/test_tools.py`
- bash: echo hello -> stdout contains "hello", exit_code=0
- bash: failing command -> exit_code=1
- bash: stderr capture
- bash: dangerous command blocked
- bash: timeout handling
- read_file: existing file
- read_file: missing file -> error
- read_file: with limit
- write_file: create new file
- write_file: overwrite existing
- edit_file: find and replace
- edit_file: missing old_string -> error

**Done when**:
- `uv run pytest tests/python/test_tools.py -v` passes
- `uv run ruff check src/harness/tools/` clean

---

### Step 6: Tool Registry — Role-Based Tool Dispatch

**Files**: `src/harness/tools/registry.py`, `src/harness/tools/planner_tools.py`
**Depends on**: Step 5
**Extract from**: s_full.py TOOL_HANDLERS, TOOLS, _planner_guard

**Implementation**:
- `registry.py`: ToolRegistry class with register(), get_tools_for_role(AgentRole), get_handler(tool_name) methods. Returns both LLM-facing schema list and handler functions.
- `planner_tools.py`: Planner tool schemas and handler stubs for spawn_worker, spawn_sub_planner, review_handoff, accept_handoff, reject_handoff, rewrite_scratchpad, read_scratchpad, send_message, read_inbox, list_agents, get_error_budget
- Planner guard: bash, write_file, edit_file blocked for planner role

**Tests**: `tests/python/test_tools.py` (append)
- Planner tools exclude bash, write_file, edit_file
- Worker tools exclude spawn_worker, spawn_sub_planner
- Planner guard rejects forbidden tools with clear error
- Tool registry returns correct schema format (name, description, input_schema)
- get_handler returns callable for known tool, None for unknown

**Done when**:
- `uv run pytest tests/python/test_tools.py -v` passes
- `uv run ruff check src/harness/tools/` clean

---

### Step 7: Git Workspace — Creation, Diff, Cleanup

**Files**: `src/harness/git/__init__.py`, `src/harness/git/workspace.py`, `tests/python/test_git.py`
**Depends on**: Steps 1-2 (workspace models)
**Extract from**: s_full.py WorkerWorkspace class; design-doc.md "Git Integration"

**Implementation**:
- `workspace.py`: create_workspace(repo_path, worker_id, workspaces_root) -> Workspace model, compute_diff(workspace) -> list[FileDiff], cleanup_workspace(workspace), snapshot_workspace(workspace) -> dict[str, str]
- Start with full copy (shutil.copytree), not git worktree
- Ignore patterns: .git, .workspaces, .team, .tasks, node_modules, __pycache__
- File diff via comparison of workspace files against base snapshot

**Tests**: `tests/python/test_git.py`
- Fixture: git_repo (tmp_path with git init, initial commit)
- create_workspace: workspace directory exists, files copied
- Workspace isolation: changes in ws1 don't affect ws2
- compute_diff: detect changes (modify file -> diff returned)
- compute_diff: no changes -> empty list
- compute_diff: new file detected
- cleanup_workspace: directory removed
- snapshot_workspace: returns dict of rel_path -> content

**Done when**:
- `uv run pytest tests/python/test_git.py -v` passes
- `uv run ruff check src/harness/git/` clean

---

### Step 8: Git Commit + Merge Foundation

**Files**: `src/harness/git/commit.py`, `src/harness/orchestration/__init__.py`, `src/harness/orchestration/merge.py`
**Depends on**: Step 7
**Extract from**: s_full.py optimistic_merge function; design-doc.md "Merge" section

**Implementation**:
- `commit.py`: commit_changes(repo_path, message, author) -> commit hash
- `orchestration/merge.py`: optimistic_merge(workspace, canonical_path, idempotency_guard) -> MergeResult. 3-way merge: base_snapshot vs canonical_now vs worker_changes. Clean merge -> apply. Conflict -> spawn FixForwardTask. Uses IdempotencyGuard to prevent duplicate merges.

**Tests**: `tests/python/test_git.py` (append)
- Clean merge: new file in workspace -> applied to canonical
- Clean merge: modified file (canonical unchanged) -> applied
- Conflict detection: same file modified in both canonical and workspace
- Conflict generates fix_forward_task with conflict markers
- No changes -> MergeStatus.NO_CHANGES
- IdempotencyGuard prevents duplicate merge of same handoff

**Done when**:
- `uv run pytest tests/python/test_git.py -v` passes (all Layer 3)
- `uv run ruff check src/harness/` clean

---

## Phase 3: Agent Loop + Coherence (Layers 4-4.6)

### Step 9: Event Bus + Events

**Files**: `src/harness/events.py`
**Depends on**: Steps 1-3
**Extract from**: architecture decision #3; design-doc.md

**Implementation**:
- `events.py`: HarnessEvent base model (timestamp, event_type, agent_id, details), typed event subclasses: WorkerSpawned, WorkerCompleted, HandoffReceived, MergeCompleted, WatchdogAlert, ReconciliationStarted, ReconciliationCompleted, ErrorBudgetChanged, PlannerDecision
- EventBus class: subscribe(event_type, callback), emit(event), history property
- Thread-safe (threading.Lock on emit/subscribe)

**Tests**: `tests/python/test_events.py`
- EventBus emit + subscribe callback fires
- EventBus history records events
- Thread-safety: concurrent emit doesn't crash
- Event serialization roundtrip

**Done when**:
- `uv run pytest tests/python/test_events.py -v` passes
- `uv run ruff check src/harness/events.py` clean

---

### Step 10: Base Agent Loop

**Files**: `src/harness/agents/__init__.py`, `src/harness/agents/base.py`, `tests/python/test_agent_loop.py`
**Depends on**: Steps 4-6, 9
**Extract from**: s_full.py agent_loop function, _worker_loop; design-doc.md "Agent Lifecycle"

**Implementation**:
- `base.py`: BaseAgent class with:
  - Constructor: client (Anthropic), config (AgentConfig), tools (from registry), event_bus
  - run() method: the core while loop (call LLM, dispatch tools, check stop conditions)
  - Token tracking (accumulate input_tokens + output_tokens from usage)
  - Token budget enforcement (stop when exceeded)
  - Timeout enforcement (wall time)
  - Heartbeat emission (activity logging)
  - Hook points for subclasses: on_before_llm_call(), on_tool_result(), on_loop_exit()

**Tests**: `tests/python/test_agent_loop.py`
- Helper: make_mock_response, make_text_block, make_tool_use_block
- Loop exits on end_turn (1 LLM call)
- Loop executes tool and continues (2 LLM calls)
- Token budget enforcement (agent stops after exceeding)
- Timeout enforcement
- Tool results appended to messages correctly
- Messages alternate user/assistant correctly

**Done when**:
- `uv run pytest tests/python/test_agent_loop.py -v` passes
- `uv run ruff check src/harness/agents/` clean

---

### Step 11: Scratchpad Manager + Context Compression

**Files**: `src/harness/orchestration/scratchpad.py`, `src/harness/orchestration/compression.py`
**Depends on**: Steps 3, 10
**Extract from**: s_full.py ScratchpadManager, microcompact, auto_compact, estimate_tokens

**Implementation**:
- `scratchpad.py`: Scratchpad class with read(name), rewrite(name, content), validate(content) -> validates against ScratchpadSchema, autosummarize(name, messages, client). In-memory dict storage (not file-based). Validation: required sections enforced (## Goal, ## Active Workers, ## Pending Handoffs, ## Error Budget, ## Blockers, ## Next Action), advisory on optional.
- `compression.py`: estimate_tokens(messages), microcompact(messages) -> clears old tool results, auto_compact(messages, client, snapshot) -> compressed messages with state injection, CompressionTracker (tracks compression count)

**Tests**: `tests/python/test_coherence.py`
- Scratchpad read/rewrite roundtrip
- Scratchpad validate rejects missing required sections
- Scratchpad validate accepts valid content
- estimate_tokens returns reasonable estimate
- microcompact clears old tool results, keeps recent 3
- auto_compact produces compressed messages
- State injection: StateSnapshot JSON present in compressed output
- CompressionTracker increments correctly
- 3 compression cycles maintain state accuracy

**Done when**:
- `uv run pytest tests/python/test_coherence.py -v` passes
- `uv run ruff check src/harness/orchestration/` clean

---

### Step 12: Idempotency + Completion Gate

**Files**: `src/harness/orchestration/idempotency.py`
**Depends on**: Steps 3, 10
**Extract from**: design-doc.md "Duplicate Work Prevention", "Completion Verification Gate"

**Implementation**:
- `idempotency.py`: IdempotencyGuard class (re-export from models or standalone with file persistence). Methods: can_spawn_worker(task_id), mark_worker_completed(task_id, handoff_id), can_merge_handoff(handoff_id), mark_handoff_merged(handoff_id), can_create_task(title, description), mark_task_created(title, description, task_id). File persistence: save_to_file(path), load_from_file(path) using JSON.
- CompletionGate: declare_done(workers, handoffs, tasks, error_budget, reconciliation) -> (passed, reasons). Checks: all_tasks_terminal, no_workers_running, error_budget_healthy, reconciliation_passed, pending_handoffs_empty.

**Tests**: `tests/python/test_confusion_regression.py`
- Reject duplicate worker spawn after task completed
- Reject duplicate handoff merge
- Reject duplicate task creation (same title+description)
- Completion gate blocks with running workers
- Completion gate blocks with pending handoffs
- Completion gate blocks with non-terminal tasks
- Completion gate blocks with critical error budget
- Completion gate passes when all checks satisfied
- IdempotencyGuard file persistence roundtrip

**Done when**:
- `uv run pytest tests/python/test_confusion_regression.py -v` passes
- `uv run ruff check src/harness/orchestration/` clean

---

## Phase 4: Orchestration (Layer 5)

### Step 13: Scheduler — Task Dispatch + Error Budget

**Files**: `src/harness/orchestration/scheduler.py`
**Depends on**: Steps 1-2 (task/error_budget models)
**Extract from**: s_full.py TaskManager patterns; design-doc.md scheduler

**Implementation**:
- `scheduler.py`: Scheduler class with add_task(task), get_ready_tasks() -> list (respects blocked_by, returns PENDING tasks with no blockers), claim_task(task_id, worker_id), complete_task(task_id), fail_task(task_id), requeue_on_failure(task_id), get_task_board() -> TaskBoardSnapshot. Integrates ErrorBudget for tracking.

**Tests**: `tests/python/test_orchestration.py`
- Dispatches pending tasks
- Respects blocked_by (blocked task not in ready list)
- Unblocks task when blocker completes
- claim_task sets assigned_to and IN_PROGRESS
- complete_task sets COMPLETED
- requeue_on_failure sets back to PENDING
- get_task_board returns accurate counts
- Error budget integration: record success/failure

**Done when**:
- `uv run pytest tests/python/test_orchestration.py -v` passes
- `uv run ruff check src/harness/orchestration/scheduler.py` clean

---

### Step 14: Watchdog — Failure Detection + Kill/Respawn

**Files**: `src/harness/agents/watchdog.py`
**Depends on**: Steps 2, 9 (watchdog models, events)
**Extract from**: s_full.py Watchdog class

**Implementation**:
- `watchdog.py`: Watchdog class (threading.Thread daemon). record_activity(ActivityEntry), check_agents() -> list[WatchdogEvent]. Detection: zombie (no heartbeat for N seconds), tunnel_vision (same file edited N+ times), token_burn (N+ tokens without tool calls). Actions: emit WatchdogAlert event, request worker shutdown. Configurable thresholds from WatchdogConfig.

**Tests**: `tests/python/test_orchestration.py` (append)
- Detects zombie (stale heartbeat)
- Detects tunnel vision (repeated file edits)
- Detects token burn (tokens without tool calls)
- Does NOT flag healthy workers
- Respects configurable thresholds
- Emits WatchdogAlert events

**Done when**:
- `uv run pytest tests/python/test_orchestration.py -v` passes
- `uv run ruff check src/harness/agents/watchdog.py` clean

---

### Step 15: Reconciliation — Green Branch + Fixer Loop

**Files**: `src/harness/orchestration/reconcile.py`
**Depends on**: Steps 8, 13 (merge, scheduler)
**Extract from**: s_full.py ReconciliationPass class; design-doc.md "Reconciliation"

**Implementation**:
- `reconcile.py`: reconcile(repo_path, test_command, max_rounds, spawn_fixer_fn) -> ReconciliationReport. Runs test command, parses failures, spawns targeted fixers, re-tests. Hard cap at max_rounds (default 3). Green snapshot on pass. Returns ReconciliationReport with rounds, final_verdict, green_commit.

**Tests**: `tests/python/test_orchestration.py` (append)
- Green on first try (test_command="exit 0")
- Fixers spawned on failure (test_command fails, fixer function called)
- Respects max_rounds cap
- Final verdict "pass" when tests pass after fix
- Final verdict "fail" when max rounds exhausted
- Green commit set on success

**Done when**:
- `uv run pytest tests/python/test_orchestration.py -v` passes (all Layer 5)
- `uv run ruff check src/harness/orchestration/` clean

---

### Step 16: Worker Agent — Isolated Execution

**Files**: `src/harness/agents/worker.py`
**Depends on**: Steps 5, 7, 10, 11
**Extract from**: s_full.py WorkerOrchestrator._worker_loop, WorkerAgentRuntime

**Implementation**:
- `worker.py`: Worker(BaseAgent) with workspace creation, sandboxed tool execution (all file ops in workspace), diff tracking (before/after per file), heartbeat emission, auto-handoff submission on loop exit, scratchpad rewrite every N turns. Worker lifecycle: SPAWN -> EXECUTE -> HANDOFF -> CLEANUP.

**Tests**: `tests/python/test_agent_loop.py` (append or new test_worker.py)
- Worker creates workspace on init
- Worker tools operate in workspace (not canonical)
- Worker tracks file diffs
- Worker auto-submits handoff on exit
- Worker respects token budget
- Worker cleans up workspace on completion

**Done when**:
- `uv run pytest tests/python/test_agent_loop.py -v` passes
- `uv run ruff check src/harness/agents/worker.py` clean

---

### Step 17: Planner Agent — Delegation + Review

**Files**: `src/harness/agents/planner.py`
**Depends on**: Steps 6, 10, 12, 13, 14, 16
**Extract from**: s_full.py RecursiveHierarchy, WorkerOrchestrator.spawn_worker, _planner_guard; design-doc.md planner lifecycle

**Implementation**:
- `planner.py`: RootPlanner(BaseAgent) — lifecycle: INIT -> DECOMPOSE -> ORCHESTRATE -> RECONCILE -> DONE. Planner guard (cannot use bash/write/edit). spawn_worker, spawn_sub_planner, review_handoff, accept_handoff, reject_handoff tools. SubPlanner(BaseAgent) — recursive, owns delegated scope, depth tracking. Integration: IdempotencyGuard, CompletionGate, ErrorBudget, ContextUpdate.
- Planner loop bounds: max_planner_turns, max_wall_time_seconds, forced_reconcile_on_limit.

**Tests**: `tests/python/test_orchestration.py` (append)
- Planner cannot use bash/write/edit (guard)
- Planner spawns worker for ready task
- Planner reviews handoff
- Planner triggers optimistic merge on accept
- SubPlanner respects depth limit
- Planner loop bounds: stops at max_turns
- Completion gate blocks premature exit

**Done when**:
- `uv run pytest tests/python/test_orchestration.py -v` passes
- `uv run ruff check src/harness/agents/planner.py` clean

---

## Phase 5: Integration + Robustness (Layers 5.5-6)

### Step 18: Graceful Shutdown — Signal Handler + Checkpoint

**Files**: `src/harness/orchestration/shutdown.py`
**Depends on**: Steps 16, 17
**Extract from**: architecture decision #12

**Implementation**:
- `shutdown.py`: register_signal_handlers(), checkpoint(harness_state) -> saves state to JSON, resume(checkpoint_path) -> restores state. On SIGINT/SIGTERM: request all workers to stop, wait for handoff submissions, checkpoint current state, exit cleanly.

**Tests**: `tests/python/test_orchestration.py` (append)
- Checkpoint saves state to file
- Resume loads state from file
- State roundtrip (checkpoint -> resume -> verify)

**Done when**:
- `uv run pytest tests/python/test_orchestration.py -v` passes
- `uv run ruff check src/harness/orchestration/shutdown.py` clean

---

### Step 19: CLI Entry Point

**Files**: `src/harness/cli.py`, update `src/harness/__init__.py`
**Depends on**: Steps 4, 17
**Extract from**: s_full.py __main__ REPL section; design-doc.md CLI entry

**Implementation**:
- `cli.py`: main() function that loads HarnessConfig, initializes Orchestrator (RootPlanner + Watchdog + EventBus), runs the harness. Argparse: `harness run --config .env --instructions "..."`.
- `__init__.py`: export key classes (HarnessConfig, Task, Handoff, etc.) and __version__

**Tests**: No dedicated CLI tests (Layer 6 covers E2E)

**Done when**:
- `uv run python -m harness --help` works (shows usage)
- `uv run ruff check src/harness/cli.py` clean

---

### Step 20: Endurance Tests

**Files**: `tests/python/test_endurance.py`
**Depends on**: Steps 13-17
**Extract from**: testing-strategy.md "Layer 5.5: Endurance Tests"

**Implementation**:
- 20-task orchestration over 50+ planner turns (mocked LLM, scripted responses)
- Multiple compression cycles maintain coherent task tracking
- Worker failures mid-execution trigger re-queuing
- Error budget transitions: HEALTHY -> WARNING -> CRITICAL -> recovery
- Planner loop bounds trigger graceful shutdown
- Final task board state matches expected outcomes

**Done when**:
- `uv run pytest tests/python/test_endurance.py -v` passes
- All invariants hold across extended runs

---

### Step 21: Chaos Tests

**Files**: `tests/python/test_chaos.py`
**Depends on**: Steps 13-17
**Extract from**: testing-strategy.md "Layer 5.6: Chaos Tests"

**Implementation**:
- Worker thread crash: auto-submits FAILED handoff
- Workspace deleted during merge: graceful error + fix-forward task
- Corrupt handoff (missing narrative): rejected gracefully
- Two workers modify same file: optimistic merge handles conflict
- Watchdog kills worker: replacement spawned
- Out-of-order handoff arrivals: processed correctly

**Done when**:
- `uv run pytest tests/python/test_chaos.py -v` passes
- System degrades gracefully under all failure scenarios

---

### Step 22: Instructor Library Integration

**Files**: Update `src/harness/agents/base.py`, `src/harness/agents/planner.py`, `src/harness/agents/worker.py`, `pyproject.toml`
**Depends on**: Steps 10, 16, 17
**Extract from**: architecture decisions #1-2

**Implementation**:
- Add `instructor` to pyproject.toml dependencies
- Integrate instructor for structured LLM outputs:
  - Loop-level: planner decisions (PlannerDecision model with action enum + parameters)
  - Tool-level: handoff submission (Handoff model validation), scratchpad rewrite (ScratchpadSchema validation)
- Patch anthropic client with instructor: `instructor.from_anthropic(client)`

**Done when**:
- `uv run pytest tests/python/ -v -m "not e2e"` all pass
- Instructor integration doesn't break existing tests
- `uv run ruff check src/harness/` clean

---

### Step 23: Rich CLI Renderer + Event Bus Integration

**Files**: `src/harness/rendering.py`, update `pyproject.toml`
**Depends on**: Steps 9, 19
**Extract from**: architecture decision #3

**Implementation**:
- Add `rich` to pyproject.toml dependencies
- `rendering.py`: RichRenderer class that subscribes to EventBus and renders events using Rich. Live display: worker status table, error budget gauge, task board summary, recent watchdog events. Log panel for scrolling event history.

**Done when**:
- Rich renderer doesn't crash on any event type
- Manual smoke test with mock events produces readable output
- `uv run ruff check src/harness/rendering.py` clean

---

### Step 24: Layer 3.5 Testing Strategy Update + Structured Output Tests

**Files**: `docs/architecture/testing-strategy.md` (update), `tests/python/test_structured_output.py`
**Depends on**: Step 22
**Extract from**: CLAUDE.md "Not Started" item 5

**Implementation**:
- Add Layer 3.5 section to testing-strategy.md between Layer 3 and Layer 4
- Tests: instructor produces valid PlannerDecision from mocked LLM response, instructor produces valid Handoff from tool payload, instructor rejects invalid structured output, ScratchpadSchema validation via instructor

**Done when**:
- `uv run pytest tests/python/test_structured_output.py -v` passes
- testing-strategy.md updated with Layer 3.5 section

---

### Step 25: Final Integration — Update CLAUDE.md + Run Full Suite

**Files**: `CLAUDE.md` (update Implementation Status), `src/harness/__init__.py` (final exports)
**Depends on**: All previous steps

**Implementation**:
- Update CLAUDE.md "Not Started" -> "Done" for completed items
- Verify all `__init__.py` files export correctly
- Run full test suite: `uv run pytest tests/python/ -v -m "not e2e"`
- Run linter: `uv run ruff check src/ --fix`
- Run formatter: `uv run ruff format src/`

**Done when**:
- `uv run pytest tests/python/ -v -m "not e2e"` — ALL PASS
- `uv run ruff check src/ agents/` — clean
- `uv run ruff format --check src/ agents/` — clean
- CLAUDE.md Implementation Status updated

---

## Execution Summary

| Phase | Steps | Layer | Estimated Effort |
|-------|-------|-------|-----------------|
| 1: Foundation | 1-4 | 0-1 | Models + Config |
| 2: Tools + Git | 5-8 | 2-3 | Tool handlers + Git ops |
| 3: Agent + Coherence | 9-12 | 4-4.6 | Agent loop + State mgmt |
| 4: Orchestration | 13-17 | 5 | Scheduler + Planner + Worker |
| 5: Integration | 18-25 | 5.5-6 | Shutdown + CLI + Tests + Polish |

**Total**: 25 steps, ~100 tests, ~27 source files

**Critical path**: Steps 1 -> 2 -> 3 -> 4 -> 5 -> 7 -> 10 -> 16 -> 17 (the core agent pipeline)

**Parallel opportunities**:
- Steps 5-6 (tools) and Step 7 (git) can run in parallel after Step 4
- Steps 13 (scheduler) and 14 (watchdog) can run in parallel
- Steps 20 (endurance) and 21 (chaos) can run in parallel
