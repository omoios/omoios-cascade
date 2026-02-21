# Cursor Harness Architecture Reference

> Consolidated reference for Cursor's multi-agent browser engine architecture, built with thousands of concurrent AI coding agents achieving ~1,000 commits/hour across 10M+ tool calls over one week.

## 1. Executive Summary

Cursor built a browser engine using thousands of concurrent AI coding agents operating in parallel. The system achieved approximately 1,000 commits per hour with over 10 million tool calls executed during a one-week intensive development period.

The key architectural insight driving this system: **treat models as "brilliant new hires"** — they need clear specifications, constraints, and guardrails, not step-by-step instructions. The model is capable of significant autonomous work when given the right structure and boundaries.

This reference document consolidates the evolution from failed prototypes through six major iterations to the final production architecture that enabled this scale of operation.

## 2. Evolution History

The Cursor team progressed through six distinct architectural iterations, each addressing failures observed in the previous version.

### V1 — Prototype (Failed)

The initial prototype used a single agent with a single prompt. This approach worked adequately for small tasks but failed at scale. The primary failure mode was context overflow: as the agent worked on larger problems, the context window filled up and the agent lost track of its goals. Without mechanisms for context management or goal tracking, the single-agent approach hit a fundamental ceiling.

### V2 — Context Management

Version 2 added context compression and summarization capabilities. Individual agent lifespan improved significantly — agents could work longer without losing track of their objectives. However, this version remained single-agent and serial in execution. One agent working at a time limited throughput regardless of how well the context was managed.

### V3 — First Teams

Version 3 introduced multiple agents with a shared filesystem. This was the first step toward parallelism, but the lack of coordination protocols created significant problems. Workers would overwrite each other's files without any awareness of concurrent modifications. The team needed more than just multiple agents — they needed coordination.

### V4 — Message Passing

Version 4 added mailboxes and a message bus, enabling agents to communicate with each other. The flat hierarchy created a new bottleneck: a single "lead" agent attempting to coordinate dozens of workers became the limiting factor. The lead could not efficiently delegate to so many workers simultaneously.

### V5 — Roles (Failed Complexity)

Version 5 attempted to solve the bottleneck by adding multiple roles to a single agent: plan, explore, research, spawn, check, review, edit, merge, and judge. This created pathological behaviors that emerged from role confusion. Agents would sleep randomly, refuse to plan, do work themselves instead of delegating, and claim premature completion. The fundamental lesson: **too many roles for one agent creates dysfunction**.

### V6 — Clean Split (Final)

Version 6 separated concerns into distinct agent types with clean boundaries:

- **Planner** agents decompose problems and delegate work — they never write code
- **Worker** agents execute tasks and submit handoffs — they never plan or decompose
- **SubPlanners** enable recursive delegation for complex problems
- **Watchdog** provides independent monitoring without planning authority

This separation became the production architecture that achieved 1,000 commits per hour.

## 3. Final Architecture (V6)

The production architecture uses a hierarchical tree structure with distinct agent types at each level:

```
Root Planner
├── SubPlanner A
│   ├── Worker 1
│   ├── Worker 2
│   └── Worker 3
├── SubPlanner B
│   ├── Worker 4
│   └── SubPlanner B1
│       ├── Worker 5
│       └── Worker 6
└── Watchdog (independent monitor)
```

The Root Planner owns the top-level decomposition and coordinates multiple SubPlanners. Each SubPlanner manages a delegated slice of the problem, can recursively spawn additional SubPlanners for complex sub-problems, and aggregates results from its children. Workers execute leaf-level tasks and report back through the hierarchy. The Watchdog operates as a daemon thread, monitoring for failure conditions independently of the planning hierarchy.

## 4. Agent Roles

Each agent type has a distinct lifecycle, tool set, and constraints that define its behavior.

### Root Planner

The Root Planner initiates the entire work cycle and orchestrates the top-level decomposition:

**Lifecycle**: INIT → DECOMPOSE → ORCHESTRATE (loop) → RECONCILE → DONE

The lifecycle begins with initialization, moves to decomposing the problem into sub-tasks, orchestrates work through delegating to SubPlanners, reconciles results from children, and signals completion.

**Tool Set**:
- `spawn_worker`: Create a new Worker agent with specific task
- `spawn_sub_planner`: Create a new SubPlanner with delegated scope
- `review_handoff`: Examine output from child agents
- `rewrite_scratchpad`: Update planning state
- `send_message`: Direct communication to specific agent
- `read_inbox`: Receive messages from children

**Constraint**: "You decompose and delegate. You NEVER write code."

The Root Planner never writes code — it only decomposes problems, delegates work, and reconciles results. This constraint is critical: mixing planning with execution created the pathological behaviors observed in V5.

### SubPlanner

SubPlanners provide recursive delegation capability for complex problems:

**Recursive Nature**: A SubPlanner can spawn another SubPlanner, creating arbitrary depth in the hierarchy. This enables handling problems of any complexity by decomposing them into increasingly focused sub-problems.

**Responsibilities**:
- Owns a delegated slice of the overall problem
- Decomposes its slice into tasks for Workers
- Collects ALL child handoffs and compresses them into a single aggregate narrative
- Reports to its parent (either Root Planner or another SubPlanner)

**Information Compression**: SubPlanners compress child outputs at approximately 20:1 ratio. They transform multiple detailed worker reports into a coherent narrative that preserves essential information for their parent.

### Worker

Workers execute individual tasks at the leaf level of the hierarchy:

**Tool Set**:
- `bash`: Execute shell commands
- `read_file`: Read file contents
- `write_file`: Create or overwrite files
- `edit_file`: Modify existing files
- `submit_handoff`: Report completion to parent
- `rewrite_scratchpad`: Update personal state

**Constraint**: "Execute the assigned task. Do NOT decompose or spawn."

Workers do not decompose problems or spawn sub-agents. They receive a specific task and execute it. This simplicity is intentional — workers are reliable execution engines, not planners.

**Information Compression**: Workers compress their work context and file diffs into handoff narratives at approximately 100:1 ratio. This high compression is possible because the worker is focused on a single, well-defined task.

### Watchdog

The Watchdog provides independent monitoring that operates outside the planning hierarchy:

**Detection Capabilities**:
- **Zombies**: Agents that stop sending heartbeats — no activity for extended period
- **Tunnel vision**: Agents making 50+ edits to the same file without progress
- **Token burn**: High token spend with no measurable progress
- **Scope creep**: Agent drifting beyond its delegated boundaries

**Actions**:
- Sends interrupt signals to problematic agents
- Can kill agents that exceed resource bounds
- Does NOT make planning decisions — only monitors and intervenes

The Watchdog operates as a daemon thread with independent monitoring logic. It does not participate in planning or delegation — its sole purpose is detecting and responding to failure modes.

## 5. Handoff Protocol

The handoff is the fundamental unit of upward communication in the hierarchy. Every agent reports to its parent through a structured handoff.

### Handoff Structure

```python
{
    agent_id: str,           # Unique identifier for reporting agent
    task_id: str,            # Task being reported on
    status: Success | PartialFailure | Failed | Blocked,
    diff: {                  # File modifications
        filepath: {
            before: str,    # Original content
            after: str       # Modified content
        }
    },
    narrative: str,          # Free-text: what was done, what wasn't, concerns, suggestions
    artifacts: list,         # Generated files, outputs
    metrics: {               # Execution metadata
        wall_time: float,
        tokens_used: int,
        attempts: int,
        files_modified: int
    }
}
```

### The Narrative is Critical

**Key quote**: "The narrative is not optional metadata. It is the primary mechanism for propagating understanding up the hierarchy."

The narrative field carries free-text explanation of what was accomplished, what was not accomplished, concerns about the approach, and suggestions for downstream work. This is not supplementary — it is the primary mechanism by which understanding flows upward.

Without a detailed narrative, parent agents cannot make informed decisions about whether to accept results, retry work, or escalate issues. The compression ratios achieved by the hierarchy depend on the narrative carrying sufficient context.

### Information Compression Table

| Layer       | Input                              | Output                           | Ratio   |
|-------------|-------------------------------------|----------------------------------|---------|
| Worker      | Full work context + file diffs     | Handoff narrative + diff         | ~100:1  |
| SubPlanner  | N worker handoffs                 | Aggregate narrative + merged diff | ~20:1   |
| Root        | N SubPlanner handoffs             | Final status + summary          | ~10:1   |

Each layer compresses before passing upward. The high compression ratio at the Worker level is possible because workers are focused on specific, narrow tasks. The lower ratio at higher levels reflects the increasing complexity of aggregating diverse work.

## 6. Merge & Conflict Strategy

The system uses copy-on-write filesystem isolation to enable parallel work without interference.

### Isolation Model

Each worker gets its own copy of the repository. The filesystem provides copy-on-write semantics, so modifications to one worker's copy do not affect others. When a worker completes, the diff between its copy and the canonical repository represents its contribution.

### Merge Approaches

When a worker submits its handoff, the system attempts to merge changes into the canonical repository:

1. **Clean merge**: Changes apply cleanly → quick build verification → success
2. **Conflict**: File was modified by another worker → spawn CRITICAL fix task with both versions + full context
3. **Build break**: Merge succeeds but build fails → spawn CRITICAL recovery task

**Key quote**: "DO NOT REVERT. The repo may be broken. This is by design."

The system does not revert changes when conflicts or build failures occur. Instead, it spawns fix tasks to resolve issues. This is intentional — reverting creates a different problem: losing all the work that was done.

### Why No Integrator Role

An Integrator agent that reviews and approves all merges was considered but rejected. The reason: **it became an obvious bottleneck**. With hundreds of workers producing commits, a single integrator could not keep pace. The system accepts that some errors will occur and builds reconciliation into the workflow rather than requiring perfection at merge time.

## 7. Prompt Engineering Principles

The hierarchy relies on specific prompt engineering patterns to maintain agent behavior.

### Treat Models Like Brilliant New Hire

Models are capable but new to the codebase. They need clear specifications of what to do, constraints on what not to do, and guardrails for edge cases. The model is not told every step — it is given a role and the tools to fulfill it.

### Constraints Over Instructions

Negative constraints are more effective than positive instructions:

- Say "NEVER write code" not "you should avoid writing code"
- Say "Do NOT plan" not "try not to plan too much"

Constraints are clearer and less subject to interpretation.

### Identity Persistence

After every context compression, the system re-injects the agent's identity and constraints. This ensures the agent remembers who it is and what its role entails even after summarization has removed details from the message history.

### Self-Reflection Prompts

Periodic prompts encourage self-assessment:
- "Are you making progress or going in circles?"
- "Is your current approach working?"

These prompts help agents recognize when they are stuck and should try a different approach.

### Alignment Reminders

After summarization, the system injects alignment reminders to reinforce the agent's role:
- "Remember: you are a Worker. Execute the task. Do not plan or decompose."
- "Remember: you are a Planner. Decompose and delegate. Never write code."

### Pivot Encouragement

When approaches fail repeatedly, the system encourages pivoting:
- "If approach X hasn't worked after 3 attempts, try a completely different approach"

This prevents agents from persisting with ineffective strategies.

## 8. Freshness Mechanisms

Maintaining agent awareness over long-running tasks requires explicit freshness mechanisms.

### Scratchpad Rewriting

**Key quote**: "The scratchpad must be REWRITTEN, not appended to"

Appending creates unbounded growth and loses the signal in noise. Rewriting forces the agent to distill the current state into essential information. The scratchpad is rewritten every N turns with only the critical current state.

### Auto-Summarization

When context reaches 80% of capacity, the system automatically triggers summarization. This compresses the conversation history while preserving key facts, decisions, and progress.

### Self-Reflection Injection

Every N turns, the system injects a self-reflection prompt. This is independent of the normal message flow — it is a deliberate intervention to ensure the agent assesses its own progress.

### Identity Re-Injection

After every compression event (summarization or compaction), the system inserts the identity block at the start of the compressed context. This ensures the agent immediately knows its role and constraints after context reconstruction.

## 9. Infrastructure

The system requires specific infrastructure to support the hierarchy.

### Copy-on-Write Filesystem

Each agent receives its own copy of the repository. Modifications are isolated until merge time. This is fundamental — without isolation, concurrent work would create conflicts in real-time.

### Resource Bounds

The Watchdog enforces resource limits:
- Wall time limits per task
- Token budgets per agent
- Maximum file modifications before review

Agents that exceed these bounds are terminated.

### Shared Task Board

A centralized task board tracks:
- All tasks in the system
- Dependencies between tasks
- Task ownership
- Task status (pending, in_progress, completed, blocked)

The task board enables the hierarchy to coordinate work and understand dependencies.

### Activity Logging

Each agent writes to an activity log:
```
.activity/{agent_name}.jsonl
```

Each line records:
- Timestamp
- Event type (spawn, tool_use, handoff, shutdown)
- Metrics (tokens, time, files modified)

These logs enable post-hoc analysis and debugging.

## 10. Design Principles

The architecture is governed by seven core design principles.

### 1. Anti-Fragile

Individual failures don't crash the system. When an agent fails, its error becomes a new task for other agents to address. The system absorbs failures rather than being derailed by them.

### 2. Optimistic Execution

The system accepts a small error rate combined with reconciliation rather than requiring 100% correctness before each commit. This enables high throughput.

**Key quote**: "Error rate stays 'small and constant, perhaps rarely completely clean but steady and manageable, not exploding or deteriorating'"

### 3. Information Compression

Each hierarchy layer compresses before passing upward. This keeps higher-level agents from drowning in detail while preserving essential information.

### 4. Role Separation

One role per agent. No mixing planning with execution. This prevents the pathological behaviors observed in V5 when multiple roles were assigned to single agents.

### 5. Fix Forward

When errors or conflicts occur, the system spawns fix tasks. It never halts for manual intervention and never reverts changes. Problems are solved, not undone.

### 6. Throughput Over Perfection

The system prioritizes steady progress over perfect results. The throughput tradeoffs are explicit:

| Strategy                          | Correctness            | Throughput             |
|-----------------------------------|----------------------|-----------------------|
| 100% correct per commit           | Very high            | Very low (~10/hr)     |
| Accept small error + reconciliation| High (after recon)   | ~1,000 commits/hr     |
| No error checking                 | Unpredictable        | Maximum theoretical   |

### 7. Recursive Delegation

SubPlanners can spawn SubPlanners. This enables the hierarchy to scale to arbitrary problem complexity by adding depth rather than width.

## 11. Session Mapping Table

The following table maps each learning session to the Cursor mechanism it teaches:

| Session | Cursor Mechanism           | Key Quote                                                      | Reference Section |
|---------|---------------------------|----------------------------------------------------------------|------------------|
| s12     | Structured Handoffs       | "The narrative is not optional metadata. It is the primary mechanism for propagating understanding up the hierarchy." | §5 Handoff Protocol |
| s13     | Scratchpad Rewriting      | "The scratchpad must be REWRITTEN, not appended to"            | §8 Freshness Mechanisms |
| s14     | Planner-Worker Split      | "Too many roles for one agent" (V5 lesson)                     | §4 Agent Roles |
| s15     | Worker Isolation          | "Each agent gets its own copy of the repo"                     | §9 Infrastructure |
| s16     | Optimistic Merge          | "DO NOT REVERT. The repo may be broken. This is by design."    | §6 Merge Strategy |
| s17     | Recursive Hierarchy       | "SubPlanner: Recursive — can spawn another SubPlanner"          | §4 Agent Roles |
| s18     | Error Tolerance           | "Errors become new tasks"                                       | §10 Design Principles |
| s19     | Failure Modes            | "Detects: zombies, tunnel vision, token burn"                  | §4 Watchdog |
| s20     | Reconciliation Pass      | "INIT → DECOMPOSE → ORCHESTRATE → RECONCILE → DONE"            | §4 Root Planner |

## Production Reference

This document serves as the architectural reference for the Cursor harness system. The production implementation extends these principles with:

- Real-time metrics dashboarding
- Dynamic scaling of agent pools based on queue depth
- Circuit breakers that throttle new work when error rates spike
- Comprehensive audit logging for compliance and debugging

The fundamental insight remains: treat models as capable agents that need clear roles, constraints, and coordination mechanisms rather than step-by-step instructions. The hierarchy enables scale by decomposing problems, delegating work, and compressing information at each level.
