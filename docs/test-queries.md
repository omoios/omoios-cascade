# Harness Test Queries

Test scenarios for exercising long-running harness capabilities. Each tier targets specific mechanisms, progressing from single-worker smoke tests to full orchestration.

## Setup

Prepare a disposable test repo:

```bash
mkdir -p /tmp/test-repo && cd /tmp/test-repo && git init
echo "# Test Repo" > README.md
git add . && git commit -m "init"
```

For tiers requiring existing files, run the setup commands listed under each query.

All queries use this pattern:

```bash
uv run python -m harness run -i "INSTRUCTIONS" --repos /tmp/test-repo
```

---

## Tier 1: Single-Worker Smoke Tests

Verify the basic planner -> worker -> handoff flow with one worker.

### 1a. Create a single file

```bash
uv run python -m harness run -i "Create a file called hello.py that prints hello world" --repos /tmp/test-repo
```

**Mechanisms exercised:** planner loop, spawn_worker, worker workspace isolation, structured handoff, accept_handoff

**Expected behavior:** Planner creates one task, spawns one worker. Worker uses write_file to create hello.py. Worker submits handoff. Planner reviews and accepts.

**Success criteria:** /tmp/test-repo workspace copy contains hello.py. Planner completes within 5 turns. One worker spawned and cleaned up.

**Setup required:** Base test repo only.

### 1b. Read and summarize

```bash
uv run python -m harness run -i "Read README.md and create SUMMARY.md with a one-line summary" --repos /tmp/test-repo
```

**Mechanisms exercised:** planner loop, worker read_file + write_file, handoff with file diffs

**Expected behavior:** Worker reads README.md, writes SUMMARY.md. Handoff includes diffs for the new file.

**Success criteria:** SUMMARY.md created in worker workspace. Handoff contains diff showing file creation.

**Setup required:** Base test repo with README.md.

---

## Tier 2: Multi-Worker Parallelism

Two or more workers running on independent tasks simultaneously.

### 2a. Three independent modules

```bash
uv run python -m harness run -i "Create three Python modules: string_utils.py with reverse_string and capitalize_words functions, math_utils.py with factorial and fibonacci functions, date_utils.py with days_between and is_weekend functions. Each file should be self-contained." --repos /tmp/test-repo
```

**Mechanisms exercised:** planner task decomposition, multiple spawn_worker calls, parallel worker execution (threading), multiple handoff review/accept cycles, event bus (WorkerSpawned x3, WorkerCompleted x3)

**Expected behavior:** Planner creates 3 tasks (no dependencies). Spawns 3 workers in parallel. Each worker creates one module. All handoffs reviewed and accepted.

**Success criteria:** Three .py files created. Three WorkerSpawned events emitted. Three handoffs accepted. Total wall time less than 3x single-worker time (parallelism benefit).

**Setup required:** Base test repo only.

### 2b. Independent refactors across files

```bash
uv run python -m harness run -i "Create two files: Create validators.py with an email_validator function and a phone_validator function. Create formatters.py with a format_currency function and a format_date function." --repos /tmp/test-repo
```

**Mechanisms exercised:** parallel spawn, independent workspaces, no merge conflicts (disjoint files)

**Expected behavior:** Two workers, each creating one file. No merge needed since files are independent.

**Success criteria:** Both files exist with correct functions. Two workers completed in parallel.

**Setup required:** Base test repo only.

---

## Tier 3: Dependency Chains

Tasks with explicit ordering constraints (blocked_by).

### 3a. Model -> Service -> Tests

```bash
uv run python -m harness run -i "Build a layered module: First create models.py with a User dataclass (name, email, age fields). Then create service.py that imports User from models and has create_user and validate_user functions. Finally create test_service.py that imports from service and tests both functions." --repos /tmp/test-repo
```

**Mechanisms exercised:** create_task with blocked_by, scheduler dependency resolution, sequential worker spawning, scratchpad tracking of progress across phases

**Expected behavior:** Planner creates 3 tasks: task-models (no deps), task-service (blocked_by task-models), task-tests (blocked_by task-service). Workers spawn sequentially as dependencies resolve.

**Success criteria:** All three files created. service.py correctly imports from models.py. test_service.py imports from service.py. Tasks completed in correct order.

**Setup required:** Base test repo only.

### 3b. Config -> App -> Deploy script

```bash
uv run python -m harness run -i "Create config.py with a Settings class that reads from environment variables. Then create app.py that imports Settings and uses it. Then create deploy.sh that echoes the deployment steps." --repos /tmp/test-repo
```

**Mechanisms exercised:** two-level dependency chain, task board progression (pending -> in_progress -> completed)

**Expected behavior:** Three sequential tasks. Each waits for predecessor.

**Success criteria:** All files created. app.py references config.py structures. deploy.sh is executable or has bash content.

**Setup required:** Base test repo only.

---

## Tier 4: Merge Conflict Scenarios

Workers editing overlapping files, triggering merge resolution.

### 4a. Two workers edit the same file

Setup:
```bash
cd /tmp/test-repo
cat > utils.py << 'EOF'
def helper():
    return "original"
EOF
git add . && git commit -m "add utils"
```

```bash
uv run python -m harness run -i "Two changes to utils.py: Add a logging_decorator function at the top of the file, AND add an error_handler function at the bottom of the file. These should be done by separate workers." --repos /tmp/test-repo
```

**Mechanisms exercised:** parallel workers editing same file, optimistic merge (3-way), potential fix-forward, handoff diffs with overlapping paths

**Expected behavior:** Planner spawns 2 workers, both targeting utils.py. When merging handoffs, conflict detection occurs. If changes are in different regions, 3-way merge succeeds. If conflict, a fixer worker is spawned.

**Success criteria:** Final utils.py contains both functions plus the original helper(). No content lost.

**Setup required:** utils.py with existing content.

### 4b. Shared imports section

Setup:
```bash
cd /tmp/test-repo
cat > main.py << 'EOF'
import os

def main():
    print("hello")

if __name__ == "__main__":
    main()
EOF
git add . && git commit -m "add main"
```

```bash
uv run python -m harness run -i "Add 'import sys' to the imports in main.py AND add 'import json' to the imports in main.py. Do these as separate tasks." --repos /tmp/test-repo
```

**Mechanisms exercised:** merge conflict in same file region (imports block), conflict resolution

**Expected behavior:** Both workers add an import line near the top. High likelihood of textual conflict in the same region.

**Success criteria:** Final main.py has import os, import sys, and import json. Program still runs.

**Setup required:** main.py with single import.

---

## Tier 5: Error Budget Stress

Instructions that trigger failures consuming the error budget.

### 5a. Task with intentional failure

```bash
uv run python -m harness run -i "Create a file called output.txt. Then run the command 'python nonexistent_script.py' and report the result. Then create success.txt with the word done." --repos /tmp/test-repo
```

**Mechanisms exercised:** error_budget.record(success=False), ErrorZone transitions (healthy -> warning), get_error_budget tool, worker failure handling

**Expected behavior:** First and third tasks succeed. Second task fails (nonexistent script). Error budget records 1 failure in 3 total (33%) -- exceeds 15% threshold, enters warning/critical zone.

**Success criteria:** Error budget shows non-zero failures. Planner acknowledges the failed task. output.txt and success.txt exist. get_error_budget returns warning or critical zone.

**Setup required:** Base test repo only.

### 5b. Multiple failing tasks

```bash
uv run python -m harness run -i "Run these commands: 'cat /nonexistent/path', 'python -c import_nonexistent_module', 'ls /fake/directory'. Report results for each." --repos /tmp/test-repo
```

**Mechanisms exercised:** multiple error_budget.record(success=False), ErrorZone.CRITICAL threshold, planner reaction to degraded budget

**Expected behavior:** All three commands fail. Error budget reaches critical. Planner should note the critical state.

**Success criteria:** Error budget zone is CRITICAL. At least 3 failures recorded.

**Setup required:** Base test repo only.

---

## Tier 6: Watchdog Trigger Scenarios

Instructions designed to trigger watchdog failure mode detection.

### 6a. Tunnel vision (repeated file edits)

```bash
uv run python -m harness run -i "Create a file called draft.txt. Then edit it 25 times, each time appending a new line with the current edit number." --repos /tmp/test-repo
```

**Mechanisms exercised:** watchdog tunnel_vision_threshold (default 20), WatchdogAlert event, activity recording

**Expected behavior:** Worker edits draft.txt > 20 times, exceeding tunnel_vision_threshold. Watchdog emits WatchdogAlert with FailureMode.TUNNEL_VISION.

**Success criteria:** WatchdogAlert event with failure_mode="tunnel_vision" in event bus history. Evidence mentions the file path.

**Setup required:** Base test repo only.

### 6b. Token burn without tool use

```bash
uv run python -m harness run -i "Write a 5000-word essay about the history of computing. Do not use any files, just output the text in your response." --repos /tmp/test-repo
```

**Mechanisms exercised:** watchdog token_burn_threshold (default 16000), TOKEN_BURN detection, no tool activity flag

**Expected behavior:** Worker produces large text output without tool calls. Token count exceeds burn threshold. Watchdog flags TOKEN_BURN.

**Success criteria:** WatchdogAlert with failure_mode="token_burn" emitted. Evidence mentions token count.

**Setup required:** Base test repo only.

---

## Tier 7: Reconciliation

Tasks ending with a verification command that must pass.

### 7a. Create package with passing tests

```bash
uv run python -m harness run -i "Create a Python package: calculator/__init__.py (empty), calculator/ops.py (add, subtract, multiply, divide functions), and tests/test_ops.py (pytest tests for all four operations). Then run 'python -m pytest tests/ -v' and confirm all tests pass." --repos /tmp/test-repo
```

**Mechanisms exercised:** reconcile() with test_command, fixer loop (if tests fail on first run), max 3 reconciliation rounds, ReconciliationReport

**Expected behavior:** Workers create the package and tests. Reconciliation runs pytest. If tests fail, a fixer worker attempts repairs (up to 3 rounds). Final verdict: pass or fail.

**Success criteria:** ReconciliationReport.final_verdict == "pass". All test files exist. pytest exit code 0.

**Setup required:** Base test repo with pytest available (`uv pip install pytest` in the workspace).

### 7b. Lint compliance

```bash
uv run python -m harness run -i "Create module.py with 3 functions. Ensure it passes 'python -m py_compile module.py' without errors." --repos /tmp/test-repo
```

**Mechanisms exercised:** reconciliation with compile check, green_commit on success

**Expected behavior:** Worker creates module.py. Reconciliation verifies it compiles. Should pass on first round.

**Success criteria:** ReconciliationReport.rounds == 1, final_verdict == "pass", green_commit set.

**Setup required:** Base test repo only.

---

## Tier 8: Graceful Shutdown

Test Ctrl+C mid-execution with checkpoint and resume.

### 8a. Interrupt during multi-worker execution

```bash
uv run python -m harness run -i "Create 10 separate Python files: file_01.py through file_10.py, each with a unique function" --repos /tmp/test-repo
# Send SIGINT (Ctrl+C) after ~5 seconds
```

**Mechanisms exercised:** ShutdownHandler signal registration, shutdown_requested flag, checkpoint() serialization, HarnessCheckpoint model

**Expected behavior:** SIGINT triggers shutdown handler. Running workers complete or are interrupted. Checkpoint file written with task_states, worker_states, scratchpad content. CLI exits with code 130.

**Success criteria:** Checkpoint file exists (.harness-checkpoint.json). Partial progress preserved. Some files created before interrupt. Exit code 130.

**Setup required:** Base test repo only. Manual SIGINT timing.

---

## Tier 9: Context Compression (Long-Running)

Verbose instructions that push context window limits, triggering scratchpad rewriting.

### 9a. Multi-endpoint API

```bash
uv run python -m harness run -i "Build a complete REST API simulation: Create models.py with User, Product, Order, Review, and Category dataclasses. Create routes.py with handler functions for GET/POST/PUT/DELETE for each model (20 handlers total). Create validators.py with input validation for each model. Create tests.py with at least 2 tests per handler." --repos /tmp/test-repo
```

**Mechanisms exercised:** scratchpad rewrite_scratchpad (multiple rewrites as state evolves), context compression via microcompact, planner turn count approaching limits, many worker spawns and handoff reviews

**Expected behavior:** Planner creates 4+ tasks. Multiple scratchpad rewrites tracking evolving state. Workers produce substantial code. Planner manages 10+ handoff reviews across multiple turns.

**Success criteria:** Scratchpad rewritten at least 3 times. Planner stays within 50-turn limit. All files created. Models, routes, validators, and tests present.

**Setup required:** Base test repo only.

---

## Tier 10: Full Orchestration (Kitchen Sink)

One complex instruction exercising all mechanisms simultaneously.

### 10a. CLI calculator with full lifecycle

```bash
uv run python -m harness run -i "Build a CLI calculator application: 1) Create calc/parser.py that parses arithmetic expressions. 2) Create calc/engine.py that evaluates parsed expressions (add, subtract, multiply, divide). 3) Create calc/formatter.py that formats results with commas and decimal places. 4) Create calc/__init__.py that wires parser->engine->formatter. 5) Create calc/__main__.py for CLI entry point. 6) Create tests/test_parser.py, tests/test_engine.py, tests/test_formatter.py with pytest tests. 7) Workers should run in parallel where possible and sequential where there are dependencies. 8) Run pytest to verify all tests pass." --repos /tmp/test-repo
```

**Mechanisms exercised:**
- Planner task decomposition with dependency graph (parser/engine/formatter parallel, __init__ depends on all three, tests depend on their target module)
- Multi-worker parallelism (3 workers for parser/engine/formatter)
- Dependency chains (__init__ waits for the three modules)
- Structured handoffs with file diffs
- Scratchpad tracking across 7+ tasks
- Error budget monitoring
- Reconciliation with pytest verification
- Event bus activity (7+ WorkerSpawned, 7+ WorkerCompleted)
- Watchdog monitoring across all workers

**Expected behavior:** Planner creates ~8 tasks with a dependency DAG. First wave: 3 parallel workers (parser, engine, formatter). Second wave: __init__.py + __main__.py (depend on first wave). Third wave: 3 test workers (each depends on its module). Final: reconciliation runs pytest.

**Success criteria:** All 8 files created. Dependency ordering respected. Parallel workers actually ran concurrently (check timestamps). pytest passes (reconciliation verdict: pass). Error budget healthy. No watchdog alerts. Planner completed within turn/time limits.

**Setup required:** Base test repo with pytest available.

---

## Mechanism Coverage Matrix

| Mechanism | Tier 1 | Tier 2 | Tier 3 | Tier 4 | Tier 5 | Tier 6 | Tier 7 | Tier 8 | Tier 9 | Tier 10 |
|-----------|--------|--------|--------|--------|--------|--------|--------|--------|--------|---------|
| Planner loop | X | X | X | X | X | X | X | X | X | X |
| Worker spawn | X | X | X | X | X | X | X | X | X | X |
| Workspace isolation | X | X | X | X | X | X | X | X | X | X |
| Structured handoff | X | X | X | X | X | X | X | | X | X |
| Task dependencies | | | X | | | | | | | X |
| Parallel workers | | X | | X | | | | | X | X |
| Optimistic merge | | | | X | | | | | | X |
| Error budget | | | | | X | | | | | X |
| Watchdog | | | | | | X | | | | X |
| Reconciliation | | | | | | | X | | | X |
| Graceful shutdown | | | | | | | | X | | |
| Scratchpad rewrite | | | | | | | | | X | X |
| Context compression | | | | | | | | | X | |
| Event bus | X | X | X | X | X | X | X | X | X | X |
