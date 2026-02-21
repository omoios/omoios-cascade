# Harness Architecture

A long-running multi-agent orchestration harness for autonomous multi-codebase development.

```
                         THE HARNESS
                         ===========

    Instructions ──► Root Planner ──► SubPlanners ──► Workers
                         │                              │
                         │         ◄── Handoffs ────────┘
                         │
                    Reconciliation
                         │
                    Green Branch ──► Done
```

## What This Is

A Python package (`harness`) that orchestrates many concurrent AI coding agents to make commits and reviews across one or more codebases. It implements the recursive planner-worker architecture described in [Cursor's self-driving codebases research](https://cursor.com/blog/self-driving-codebases) and formalized in sessions s12-s20 of this repository.

The harness is a **toy learning implementation** — production-quality patterns at educational scale.

## Core Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Root Planner                         │
│  Lifecycle: INIT → DECOMPOSE → ORCHESTRATE → RECONCILE  │
│  Tools: spawn_sub_planner, spawn_worker, review_handoff  │
│  Constraint: NEVER writes code                          │
├──────────────┬──────────────────────┬───────────────────┤
│  SubPlanner  │     SubPlanner       │    SubPlanner     │
│  (recursive) │     (recursive)      │    (per-repo)     │
├──────┬───────┤─────┬────────┬───────┤─────┬─────────────┤
│ W1   │  W2   │ W3  │  W4    │  W5   │ W6  │   W7        │
│      │       │     │        │       │     │             │
│ own  │ own   │ own │  own   │  own  │ own │  own        │
│ copy │ copy  │copy │  copy  │  copy │copy │  copy       │
└──────┴───────┴─────┴────────┴───────┴─────┴─────────────┘
                         │
              ┌──────────┴──────────┐
              │      Watchdog       │
              │  (daemon thread)    │
              │  zombie detection   │
              │  tunnel vision      │
              │  token burn         │
              └─────────────────────┘
```

### Agent Roles

| Role | Responsibility | Tools | Constraint |
|------|---------------|-------|------------|
| Root Planner | Owns entire scope. Decomposes, delegates, reconciles | spawn, review, scratchpad, message | NEVER writes code |
| SubPlanner | Owns a delegated slice. Can spawn sub-planners recursively | spawn, review, scratchpad, message | NEVER writes code |
| Worker | Executes a single task on its own repo copy | bash, read, write, edit, submit_handoff | NEVER decomposes or spawns |
| Watchdog | Monitors agent health. Kills stuck agents | activity logs, kill, respawn | NEVER plans or delegates |

### Hierarchy Depth

```
Root Planner (depth 0)
├── SubPlanner (depth 1) — owns "rendering subsystem"
│   ├── Worker — "implement layout engine"
│   └── SubPlanner (depth 2) — owns "CSS parsing"
│       ├── Worker — "tokenizer"
│       └── Worker — "selector matching"
└── SubPlanner (depth 1) — owns "networking"
    ├── Worker — "HTTP client"
    └── Worker — "DNS resolver"

Max depth: 3-4 (configurable)
```

## Seven Design Principles

These emerged empirically from Cursor's research and are formalized in sessions s12-s20:

1. **Anti-Fragile** — Individual agent failures become tasks, not system halts. The system absorbs failures. (s18)
2. **Throughput Over Perfection** — Accept a small stable error rate. Reconcile at the end. (s20)
3. **Fix Forward, Never Revert** — Conflicts and errors spawn fix tasks. Canonical repo never rolls back. (s16, s18)
4. **Role Separation** — One role per agent. Mixing planning and execution creates pathological behavior. (s14)
5. **Information Compression** — Each layer compresses before passing upward. Worker→Lead ~100:1, SubPlanner→Root ~20:1. (s12)
6. **Recursive Delegation** — SubPlanners can spawn SubPlanners. Scale depth, not width. (s17)
7. **Detect and Restart, Don't Debug** — Watchdog kills stuck agents and respawns. Don't reason about pathological behavior. (s19)

## Key Mechanisms

### Handoff Protocol (s12)

The fundamental unit of upward communication. Every agent reports to its parent through a structured handoff.

```python
class Handoff(BaseModel):
    agent_id: str
    task_id: str
    status: Literal["success", "partial_failure", "failed", "blocked"]
    diff: dict[str, FileDiff]
    narrative: str          # THE critical field — propagates understanding upward
    artifacts: list[str]
    metrics: HandoffMetrics # wall_time, tokens_used, attempts, files_modified
```

The narrative is not optional metadata. It is the primary mechanism for propagating understanding up the hierarchy.

### Worker Isolation (s15)

Each worker gets its own copy of the target repository:

```
.workspaces/
├── worker-a1b2/          # full repo copy
│   ├── src/
│   └── ...
├── worker-c3d4/          # full repo copy
│   ├── src/
│   └── ...
└── canonical/            # source of truth
```

Workers operate freely in their sandbox. Diffs computed against canonical at handoff time.

### Optimistic Merge (s16)

```
Worker submits handoff
        │
   3-way merge (base snapshot, canonical now, worker changes)
        │
   ┌────┴────┐
   │ Clean?  │
   ├─ yes ───► Apply to canonical
   └─ no ────► Spawn FixForwardTask (conflict is a task, not a blocker)
```

### Scratchpad Freshness (s13)

Every agent maintains `.scratchpad/{agent}.md` — REWRITTEN every N turns, never appended. Auto-summarization at 80% context capacity. Identity re-injected after every compression.

### Watchdog (s19)

Independent daemon monitoring all workers:
- **Zombie**: No heartbeat for 60s → kill + respawn
- **Tunnel Vision**: Same file edited 20+ times → kill + respawn
- **Token Burn**: 16k+ tokens without tool calls → kill + respawn

### Reconciliation (s20)

After orchestration completes, the root planner enters RECONCILE:

```
Run full test suite on canonical
        │
   ┌────┴────┐
   │ Green?  │
   ├─ yes ───► Snapshot as green branch → DONE
   └─ no ────► Parse failures → spawn targeted fixers → re-test (max N rounds)
```

## Multi-Codebase Model

The harness supports operating across multiple repositories simultaneously:

```
Instructions: "Add auth to API server and update frontend client"
        │
  Root Planner decomposes by repo boundary
        │
  ┌─────┴──────┐
  │ SubPlanner  │──► Workers operate on api-server/ copy
  │ (api-server)│
  ├─────────────┤
  │ SubPlanner  │──► Workers operate on frontend/ copy
  │ (frontend)  │
  └─────────────┘
        │
  Cross-repo reconciliation
```

Each repository gets its own workspace tree. SubPlanners own per-repo scope. Cross-repo dependencies tracked at root planner level.

## Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Models | pydantic v2 `BaseModel` | Structured I/O, validation, serialization |
| Config | pydantic-settings `BaseSettings` | .env file loading, type-safe configuration |
| LLM Client | anthropic SDK | Direct Anthropic API access |
| Concurrency | threading + asyncio | Workers in threads, I/O in async |
| VCS | git (subprocess) | Worker isolation via worktrees or copies |
| Testing | pytest + pytest-asyncio | Incremental integration testing |

## Package Structure

```
src/harness/
├── __init__.py
├── config.py              # pydantic-settings: HarnessConfig from .env
├── models/
│   ├── __init__.py
│   ├── task.py            # Task, TaskStatus, TaskBoard
│   ├── handoff.py         # Handoff, HandoffMetrics, HandoffStatus
│   ├── agent.py           # AgentRole, AgentState, AgentConfig
│   └── workspace.py       # WorkspaceConfig, RepoCopy
├── agents/
│   ├── __init__.py
│   ├── base.py            # BaseAgent — the core loop
│   ├── planner.py         # RootPlanner, SubPlanner
│   ├── worker.py          # Worker with isolated workspace
│   └── watchdog.py        # Watchdog daemon
├── orchestration/
│   ├── __init__.py
│   ├── scheduler.py       # Task scheduling, error budget tracking
│   ├── merge.py           # Optimistic 3-way merge
│   ├── reconcile.py       # Green branch reconciliation pass
│   └── scratchpad.py      # Rewrite-only scratchpad manager
├── git/
│   ├── __init__.py
│   ├── workspace.py       # Per-worker repo copies
│   └── commit.py          # Commit creation, review submission
└── tools/
    ├── __init__.py
    ├── registry.py        # Tool dispatch registry
    ├── planner_tools.py   # spawn, review, message tools
    └── worker_tools.py    # bash, read, write, edit, submit tools
```

## Session-to-Module Mapping

| Session | Pattern | Harness Module |
|---------|---------|---------------|
| s01-s02 | Agent loop + tools | `agents/base.py`, `tools/registry.py` |
| s03 | Todo/planning | `models/task.py` |
| s04 | Subagents (context isolation) | `agents/planner.py` → `agents/worker.py` |
| s05 | Skill injection | `agents/base.py` (system prompt config) |
| s06 | Context compression | `orchestration/scratchpad.py` |
| s07 | Persistent tasks | `models/task.py`, `orchestration/scheduler.py` |
| s08 | Background execution | `agents/worker.py` (threaded) |
| s12 | Structured handoffs | `models/handoff.py` |
| s13 | Scratchpad rewriting | `orchestration/scratchpad.py` |
| s14 | Planner-worker split | `agents/planner.py`, `agents/worker.py` |
| s15 | Worker isolation | `git/workspace.py` |
| s16 | Optimistic merge | `orchestration/merge.py` |
| s17 | Recursive hierarchy | `agents/planner.py` (SubPlanner) |
| s18 | Error tolerance | `orchestration/scheduler.py` |
| s19 | Failure modes | `agents/watchdog.py` |
| s20 | Reconciliation | `orchestration/reconcile.py` |

## What's Next

See [docs/architecture/design-doc.md](docs/architecture/design-doc.md) for detailed technical design including pydantic models, configuration schema, and API surface.

See [docs/architecture/testing-strategy.md](docs/architecture/testing-strategy.md) for the incremental integration testing approach.
