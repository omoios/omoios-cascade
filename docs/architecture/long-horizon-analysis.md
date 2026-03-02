# Long-Horizon Autonomous Coding: Strategic Analysis

> Decision document for bringing the harness MVP to a close and enabling multi-day autonomous operation.

## 1. Where You Are

The harness is architecturally complete. You have:

- 20 progressive sessions (s01-s20) implementing every mechanism from Cursor's V6 architecture
- Full `src/harness/` package: planner-worker-watchdog hierarchy, structured handoffs, scratchpad rewriting, optimistic 3-way merge, error budgets, reconciliation, workspace isolation, context compression, idempotency guard, completion gate, signal handler with checkpoint
- 14 Rust-accelerated functions via PyO3 (blake3 hashing, aho-corasick search, parallel file I/O, serde_json, shell exec)
- 386 passing tests across layers 0-5.6
- 13 configuration sub-classes covering every tunable parameter
- Event bus with 25 typed event models + Rich CLI renderer
- Pool scaling, circuit breakers, cost tracking, resource bounds enforcement

The architecture is sound. Cursor's own finding validates this: "No major further iterations have been necessary on the harness." The V6 pattern (planner-worker split with watchdog) is stable.

**The hard problem is not architecture. It is durability, cost control, and worker capability.**

## 2. Gap Assessment: What Breaks at Multi-Day Scale

### 2.1 State Is Ephemeral (CRITICAL)

Everything lives in memory. Task board, scratchpad, handoff queue, error budgets, agent state, event history -- all gone on process death. A Python process running for days WILL die: OOM, network drop, OS update, power event, or simple segfault in a native extension.

**What you need**: Durable state store. SQLite is the right choice -- zero configuration, single-file, WAL mode handles concurrent reads, and you already have pydantic models that serialize trivially.

**Effort**: 2-3 days. Replace in-memory dicts with a thin SQLite persistence layer. TaskBoard, HandoffQueue, and EventBus become SQLite-backed. On startup, reconstruct state from DB. On crash, lose zero data.

### 2.2 Workers Cannot Actually Code (CRITICAL)

Your workers have tools (bash, read, write, edit, grep, find, submit_handoff) and an LLM loop. But building a worker that can reliably modify a codebase at production quality is a SOLVED PROBLEM. Claude Code, Cursor, Aider, Codex CLI, and OpenHands already do this. Each has spent thousands of engineering hours on:

- File editing heuristics (search/replace vs whole-file rewrite)
- Context window management for large codebases
- Build/test feedback loops
- LSP integration for type checking
- Git awareness

Your custom workers will never match these tools. More importantly, they don't need to. Your harness's unique value is ORCHESTRATION: planning, decomposition, merge, reconciliation, watchdog. Not line-by-line code editing.

**What you need**: Replace custom LLM worker loops with subprocess calls to established coding agents.

**Effort**: 1-2 days per integration. The interface is simple:
```python
async def execute_via_aider(task: Task, workspace: Path) -> Handoff:
    result = await asyncio.create_subprocess_exec(
        "aider", "--yes", "--message", task.description,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await result.communicate()
    # Parse output, compute diff, build Handoff
```

### 2.3 No Cost Ceiling (DANGEROUS)

`CostConfig` tracks costs but doesn't enforce hard limits. A multi-day autonomous loop with 10 workers making LLM calls can burn hundreds or thousands of dollars overnight. Your current config has `cost_per_input_token` and `cost_per_output_token` but no `max_total_cost` field.

**What you need**: Hard financial circuit breaker. When cumulative cost hits a configurable dollar limit, the harness must checkpoint and halt -- not just log a warning.

**Effort**: Half a day. Add `max_total_cost: float` to `CostConfig`. Check in the orchestrator loop. On breach, trigger graceful shutdown (you already have signal handler + checkpoint).

### 2.4 Workspace Drift Over Time (HIGH)

Workers get workspace copies at spawn time. In a multi-day run, `main` advances continuously as workers merge. Late-spawned workers are fine, but long-running workers on stale branches will produce unmergeable diffs.

**What you need**: Continuous rebase. A background task (natural fit for your Watchdog) that periodically fetches the latest canonical state and rebases active workspaces.

**Effort**: 1-2 days. The git machinery exists in `src/harness/git/`. Add a rebase interval config and a Watchdog task.

### 2.5 Scratchpad Poisoning (MEDIUM)

Over thousands of iterations, even with rewrite-not-append, scratchpads accumulate stale assumptions and hallucinated facts. Cursor solved this by compressing aggressively and re-injecting identity. Your harness has both mechanisms, but multi-day runs will stress them beyond what your current thresholds handle.

**What you need**: Aggressive scratchpad TTL. After a task completes, its narrative gets archived to the durable store and removed from the active scratchpad. Only in-flight work stays in working memory.

**Effort**: 1 day. Add archival logic to the reconciliation path.

### 2.6 No Human-in-the-Loop Gate (MEDIUM)

Multi-day autonomous operation without human checkpoints is irresponsible. Even Cursor's system had human oversight at the specification level. Your harness has no mechanism for pausing, reviewing, and approving before major phases.

**What you need**: A `PENDING_HUMAN_REVIEW` task status. When a sub-planner completes decomposition, optionally pause for human approval before spawning workers. When reconciliation fails all 3 fixer rounds, escalate to human instead of declaring failure.

**Effort**: 1 day. Add the status enum value, add a CLI prompt or webhook callback, gate the orchestrator loop.

### 2.7 No Long-Horizon Testing Strategy (MEDIUM)

You can't validate multi-day operation by running for days. You need time-compressed simulation.

**What you need**: A deterministic mock-LLM test harness that simulates 10,000 planner-worker-reconcile cycles in seconds. Inject random failures (crashes, merge conflicts, fixer failures, timeout violations). Assert invariants: no data loss, cost limits respected, all tasks reach terminal state, no zombie workers.

**Effort**: 2-3 days. You already have Layer 5.5 (endurance) and 5.6 (chaos) test infrastructure. Extend them with a fast-clock mock.

## 3. Build vs Integrate: The Real Decision

### Option A: Finish Building Everything In-House

**What it means**: Complete the custom worker LLM loop until it can reliably edit code across varied codebases. Build your own file-editing heuristics, LSP integration, context management for large files, etc.

**Effort**: 2-6 months of focused work
**Risk**: You're rebuilding what Aider/Claude Code already do, but worse
**Upside**: Full control, no external dependencies, deep understanding

### Option B: Orchestrator Over Existing Tools (RECOMMENDED)

**What it means**: Keep your planner, watchdog, merge, reconciliation, and event bus. Replace custom workers with subprocess calls to Aider, Claude Code, or Codex CLI. Your harness becomes a durable orchestration layer.

**Effort**: 2-3 weeks to MVP
**Risk**: Dependent on external tool stability and output format parsing
**Upside**: Immediately get production-quality code editing; focus on what's actually hard (orchestration)

### Option C: Full Protocol Integration (A2A/MCP)

**What it means**: Wrap external tools as A2A-compatible agents. Use the emerging protocol for discovery, task lifecycle, and message passing.

**Effort**: 1-2 months (protocol is still maturing)
**Risk**: A2A absorbed IBM's ACP in Aug 2025 and is still under Linux Foundation governance churn. The Python SDK exists but isn't battle-tested. You'd be an early adopter with limited community support.
**Upside**: Future-proof interop if A2A becomes the standard

### Recommendation: Option B now, Option C later

Start with subprocess wrappers. They're simple, debuggable, and give you immediate access to tool capabilities. The interface is narrow:

```
Input:  task description + workspace path + config
Output: exit code + stdout/stderr + git diff
```

This maps directly to your existing Handoff model. When A2A matures (late 2026?), you can swap subprocess wrappers for A2A client calls without touching orchestration logic.

## 4. The Protocol Landscape (Feb 2026)

| Protocol | Owner | Purpose | Status | Relevance |
|----------|-------|---------|--------|-----------|
| MCP | Anthropic | Tool/data access | Stable, widely adopted | Your tools already use this pattern |
| A2A | Google -> Linux Foundation | Agent-to-agent communication | Emerging, absorbed IBM's ACP | Future worker interop layer |
| ACP (IBM) | IBM | Agent communication | ARCHIVED (merged into A2A) | Dead end, do not adopt |
| ACP (Agntcy) | Agntcy | Remote agent invocation | Niche, 160 stars | Too small to bet on |
| AG-UI | CopilotKit | Agent-user interaction | Emerging | Frontend integration, not your concern |

**Bottom line**: MCP is stable and useful for tool access. A2A is the right bet for agent-to-agent but isn't ready for production. Subprocess wrappers are the pragmatic choice today.

## 5. MVP Closure Plan

Here is what "done" looks like, in priority order:

### Must-Have (1-2 weeks)

| Item | Effort | Why |
|------|--------|-----|
| SQLite state persistence | 2-3 days | Without this, multi-day operation is impossible |
| Hard cost ceiling | 0.5 day | Without this, multi-day operation is financially dangerous |
| One subprocess worker integration (Aider or Claude Code) | 1-2 days | Proves the orchestration-over-tools pattern |
| HITL gate (pause/resume/approve) | 1 day | Responsible multi-day operation requires human checkpoints |

### Should-Have (week 3)

| Item | Effort | Why |
|------|--------|-----|
| Continuous rebase in Watchdog | 1-2 days | Prevents workspace drift over days |
| Scratchpad archival on task completion | 1 day | Prevents context poisoning |
| Time-dilation test harness | 2-3 days | Validates long-horizon without running for days |

### Nice-to-Have (later)

| Item | Effort | Why |
|------|--------|-----|
| Second worker integration (different tool) | 1-2 days | Validates tool-agnostic orchestration |
| A2A protocol wrapper | 2-4 weeks | Future-proofing when protocol stabilizes |
| Web dashboard for monitoring | 1-2 weeks | Human oversight during multi-day runs |
| Distributed execution (multi-machine) | 1-2 months | Scale beyond single machine |

### What to Cut

- **Custom worker LLM loops for code editing**: Replace with tool integrations
- **Browser tools**: Not needed for code-focused orchestration
- **Web tools (http_fetch, url_extract)**: Workers should use their host tool's capabilities
- **Agent pool auto-scaling based on queue depth**: Fixed pool is fine for MVP
- **Multi-model role routing**: Single model is fine (your settled decision #10 already says this)

## 6. Testing Long-Horizon Without Running for Days

### Strategy 1: Deterministic Fast-Clock Simulation

Mock the LLM to return instant, deterministic responses. Run 10,000 planner-worker-reconcile cycles in seconds. Inject:
- Random worker crashes (5% failure rate)
- Merge conflicts (10% of handoffs)
- Fixer failures (30% of reconciliation rounds)
- Process restarts (kill and resume from SQLite every 500 cycles)

Assert invariants:
- Zero data loss across restarts
- All tasks reach terminal state (completed/failed/abandoned)
- Cost tracking accurate within 0.1%
- No zombie workers after watchdog sweep
- Reconciliation terminates within 3 rounds

### Strategy 2: Time-Compressed Integration Test

Use a real LLM but with a toy codebase (10 files, trivial tasks like "add a function", "fix a typo", "write a test"). Run 50-100 tasks through the full pipeline. This takes minutes, not days, but exercises the real orchestration path.

### Strategy 3: Chaos Monkey

During integration tests, randomly:
- SIGKILL the process and restart from checkpoint
- Corrupt a workspace (delete a file mid-edit)
- Return garbage from the LLM mock
- Exceed cost limits mid-run
- Timeout a worker mid-handoff

Assert the harness recovers gracefully in every case.

You already have Layer 5.5 (endurance) and 5.6 (chaos) in your testing strategy. These new strategies extend them for multi-day concerns.

## 7. Architecture After MVP

```
                    You (Human)
                        |
                   HITL Gate (approve/reject/modify)
                        |
               +--------v---------+
               |   Orchestrator   |  <-- Your harness (Python/asyncio)
               |   (Durable)      |  <-- SQLite-backed state
               +--------+---------+
                        |
          +-------------+-------------+
          |             |             |
     Root Planner   Watchdog    Cost Guard
          |         (daemon)    (circuit breaker)
          |
    +-----+-----+
    |           |
SubPlanner  SubPlanner
    |           |
 +--+--+     +--+--+
 |     |     |     |
Aider  CC   Aider  CC     <-- External tools via subprocess
(worker)(worker)(worker)(worker)
 |     |     |     |
 own   own   own   own    <-- Isolated git workspaces
 repo  repo  repo  repo

Legend: CC = Claude Code
```

The key shift: your harness owns ORCHESTRATION (planning, decomposition, merge, reconciliation, monitoring, cost control, human gates). External tools own EXECUTION (code editing, test running, file manipulation). Git is the integration layer.

## 8. What Cursor Taught Us That Matters Most

Re-reading the research with long-horizon eyes, three insights dominate:

**1. Intent specification is harder than architecture.** "The harness amplifies everything, including suboptimal and unclear instructions." Over days, bad intent compounds. Your HITL gates must include intent review, not just code review.

**2. Optimistic execution with reconciliation beats perfection.** "Requiring 100% correctness before every single commit caused major serialization and slowdowns." This is even more true over days -- you cannot afford to block on every merge. Accept drift, fix forward, reconcile periodically.

**3. The architecture doesn't need to change.** "No major further iterations have been necessary on the harness." Your V6-inspired architecture is the right foundation. What needs to change is the INFRASTRUCTURE around it: persistence, cost control, tool integration, human oversight.

## 9. Decision Matrix

| Approach | Time to Working System | Long-Horizon Viability | Effort | Risk |
|----------|----------------------|----------------------|--------|------|
| Finish custom workers | 2-6 months | Medium (still need persistence) | Very High | Rebuilding solved problems |
| **Orchestrator + subprocess tools** | **2-3 weeks** | **High** | **Medium** | **Tool output parsing** |
| Full A2A integration | 1-2 months | High (future-proof) | High | Protocol immaturity |
| Abandon harness, use existing orchestrator | 1 week | Unknown | Low | Losing everything you've built |

**The recommendation is clear: Option B (orchestrator + subprocess tools) gives you the fastest path to a working long-horizon system while preserving everything you've built.**

Your harness becomes the "brain" that plans and coordinates. Aider/Claude Code become the "hands" that write code. SQLite becomes the "memory" that survives crashes. The HITL gate becomes the "conscience" that keeps it responsible.
