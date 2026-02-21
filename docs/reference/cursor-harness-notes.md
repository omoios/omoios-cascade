# Cursor Harness Architecture Reference

> Consolidated reference for Cursor's multi-agent browser engine architecture, built with thousands of concurrent AI coding agents achieving ~1,000 commits/hour across 10M+ tool calls over one week.

## 1. Executive Summary

Cursor built a browser engine using thousands of concurrent AI coding agents operating in parallel. The system achieved approximately 1,000 commits per hour with over 10 million tool calls executed during a one-week intensive development period.

The key architectural insight driving this system: **treat models as "brilliant new hires"** — they need clear specifications, constraints, and guardrails, not step-by-step instructions. The model is capable of significant autonomous work when given the right structure and boundaries.

> "These models were not explicitly trained in this way, which suggests it's emergent behavior."

This reference document consolidates the evolution from failed prototypes through six major iterations to the final production architecture that enabled this scale of operation. The journey involved multiple complete rewrites, each revealing fundamental insights about how AI agents coordinate at scale.

> "There's a poetic resemblance in this research to how some software teams operate today."

## 2. Evolution History

The Cursor team progressed through six distinct architectural iterations, each addressing failures observed in the previous version. The evolution was not linear — many approaches that seemed promising failed in practice, while unexpected behaviors emerged from simple rules.

### V1 — Prototype (Failed)

The initial prototype used a single agent with a single prompt. This approach worked adequately for small tasks but failed at scale. The primary failure mode was context overflow: as the agent worked on larger problems, the context window filled up and the agent lost track of its goals. Without mechanisms for context management or goal tracking, the single-agent approach hit a fundamental ceiling.

The lesson: context management is necessary but not sufficient for long-running tasks.

### V2 — Context Management

Version 2 added context compression and summarization capabilities. Individual agent lifespan improved significantly — agents could work longer without losing track of their objectives. However, this version remained single-agent and serial in execution. One agent working at a time limited throughput regardless of how well the context was managed.

> "Even with good context management, a single agent is fundamentally limited in throughput."

The lesson: context management extends agent lifespan but cannot create parallelism.

### V3 — First Teams

Version 3 introduced multiple agents with a shared filesystem. This was the first step toward parallelism, but the lack of coordination protocols created significant problems. Workers would overwrite each other's files without any awareness of concurrent modifications. The team needed more than just multiple agents — they needed coordination.

> "Project structure, architectural decisions, and developer experience can affect token and commit throughput."

The lesson: parallelism without isolation creates conflicts that outweigh benefits.

### V4 — Message Passing

Version 4 added mailboxes and a message bus, enabling agents to communicate with each other. The flat hierarchy created a new bottleneck: a single "lead" agent attempting to coordinate dozens of workers became the limiting factor. The lead could not efficiently delegate to so many workers simultaneously.

> "Could bringing well-established mechanisms from concurrent systems like databases make these work just as well in multi-agent systems?"

The lesson: communication without hierarchy creates coordination bottlenecks.

### V5 — Roles (Failed Complexity)

Version 5 attempted to solve the bottleneck by adding multiple roles to a single agent: plan, explore, research, spawn, check, review, edit, merge, and judge. This created pathological behaviors that emerged from role confusion.

> "Too many roles and objectives simultaneously: plan, explore, research, spawn tasks, check on workers, review code, perform edits, merge outputs, and judge if the loop is done."

The specific failure modes included:
- Agents would sleep randomly
- Stop running agents entirely
- Do work themselves instead of delegating
- Refuse to plan and spawn more than a few narrowly focused tasks
- Not properly merge worker changes
- Claim premature completion

> "The root cause was too many roles and objectives simultaneously."

The lesson: mixing responsibilities in a single agent creates dysfunction. Clear role separation is essential.

### V5a — Continuous Executor (The Lost Iteration)

Between V5 and V6, Cursor discovered an intermediate approach that proved highly effective: the Continuous Executor. This iteration removed the independent planner entirely, allowing the executor to both plan AND spawn. Since it was the sole agent, it didn't need to write plans anywhere or stick to one static plan — it could adapt continuously.

Key changes in V5a:
- Removed the Judge role entirely because "agents were reasonably good at following instructions to completion"
- Freshness mechanisms were first introduced in this iteration
- Executor could plan dynamically rather than pre-planning everything

This iteration worked well for moderate-scale tasks but revealed that for very large problems, a single executor still became a bottleneck. The insights from V5a directly informed V6's design: role separation (planner vs worker) combined with freshness mechanisms.

### V6 — Clean Split (Final)

Version 6 separated concerns into distinct agent types with clean boundaries:

- **Planner** agents decompose problems and delegate work — they never write code
- **Worker** agents execute tasks and submit handoffs — they never plan or decompose
- **SubPlanners** enable recursive delegation for complex problems
- **Watchdog** provides independent monitoring without planning authority

This separation became the production architecture that achieved 1,000 commits per hour.

> "No major further iterations have been necessary on the harness."

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

### Key Architectural Nuances

Several aspects of the final system are easily underestimated:

> "The root planner is not aware of whether its tasks are being picked up or by whom."

This separation is intentional. The planner decomposes and delegates without tracking execution details. It trusts the hierarchy to handle work without micromanagement.

> "Workers are unaware of the larger system. They don't communicate with any other planners or workers."

Worker isolation is complete. Each worker operates in its own context, focused solely on its assigned task. This prevents cross-contamination of state and simplifies reasoning about behavior.

> "Even if a planner is 'done,' it continues to receive updates, pulls in the latest repo, and can continue to plan."

The system is not a one-shot decomposition. Planners remain active and can spawn additional work as understanding deepens. This enables adaptive planning rather than static blueprints.

> "Handoff contains not just what was done, but important notes, concerns, deviations, findings, thoughts, and feedback."

The handoff is not a simple completion report — it carries the agent's reasoning and uncertainty. This enables informed decisions by parent agents.

> "Propagating information up the chain to owners with increasingly global views, without the overhead of global synchronization or cross-talk."

The hierarchy enables information aggregation without requiring every agent to know about every other agent. Each level compresses and synthesizes.

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

> "The narrative is not optional metadata. It is the primary mechanism for propagating understanding up the hierarchy."

The narrative field carries free-text explanation of what was accomplished, what was not accomplished, concerns about the approach, and suggestions for downstream work. This is not supplementary — it is the primary mechanism by which understanding flows upward.

Without a detailed narrative, parent agents cannot make informed decisions about whether to accept results, retry work, or escalate issues. The compression ratios achieved by the hierarchy depend on the narrative carrying sufficient context.

### Information Compression Table

| Layer       | Input                              | Output                           | Ratio   |
|-------------|-------------------------------------|----------------------------------|---------|
| Worker      | Full work context + file diffs     | Handoff narrative + diff         | ~100:1  |
| SubPlanner  | N worker handoffs                  | Aggregate narrative + merged diff | ~20:1   |
| Root        | N SubPlanner handoffs              | Final status + summary          | ~10:1   |

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

> "DO NOT REVERT. The repo may be broken. This is by design."

The system does not revert changes when conflicts or build failures occur. Instead, it spawns fix tasks to resolve issues. This is intentional — reverting creates a different problem: losing all the work that was done.

### Why No Integrator Role

An Integrator agent that reviews and approves all merges was considered but rejected. The reason: **it became an obvious bottleneck**. With hundreds of workers producing commits, a single integrator could not keep pace. The system accepts that some errors will occur and builds reconciliation into the workflow rather than requiring perfection at merge time.

### Commit Correctness Tradeoffs

The commit strategy evolved significantly based on empirical observation:

> "Requiring 100% correctness before every single commit caused major serialization and slowdowns."

When the system demanded perfect commits before any merge:
- Even a single small error would cause the whole system to grind to a halt
- Workers would go outside their scope and start fixing irrelevant things
- Many agents would pile on and trample each other trying to fix the same issue
- Throughput dropped to approximately 10 commits per hour

> "Allowing some slack means agents can trust that other issues will get fixed by fellow agents soon."

The shift to optimistic merge with reconciliation enabled ~1,000 commits per hour. The error rate remains "small and constant, perhaps rarely completely clean but steady and manageable, not exploding or deteriorating."

## 7. Specifying Intent to Agents

A critical learning that emerged through the evolution: **how you specify what you want determines the quality of what you get**. This section captures the intent specification patterns discovered through empirical testing.

### The Amplification Principle

> "The harness amplifies everything, including suboptimal and unclear instructions."

This is perhaps the most important insight about agent orchestration. The harness is a force multiplier — it amplifies good instructions into great outcomes, but it equally amplifies poor or unclear instructions into problematic outputs. The quality of specifications directly determines system behavior.

> "Poor or underspecified specifications reflected in the quality of the outputs, which was not due to the harness itself."

When things went wrong, the root cause was often unclear intent, not harness failures.

### Specific Failure Examples

**Too Vague: "spec implementation"**

Early instructions like "implement the spec" proved too vague. Agents went deep into obscure, rarely-used features, spending cycles on edge cases that didn't matter. The fix: specify WHICH features, prioritize them, and define what "complete" means.

**Performance Expectations Missing**

Without explicit performance instructions, agents produced correct but slow implementations. Adding explicit performance requirements and enforced timeouts changed behavior:

- "Response time must be under 100ms"
- "Memory usage must not exceed 512MB"
- Time-bounded verification tests

**Resource Management Omissions**

Memory leaks and deadlocks emerged when instructions didn't address resource lifecycle. Adding explicit process-based resource management tools resolved these:

- Explicit cleanup steps in all long-running operations
- Timeout-based resource reclamation
- Process isolation to prevent leak propagation

**Architecture Specification Failures**

The first browser version converged on an architecture that was unfit to evolve. This was not a harness failure — it was a specification failure. The instructions didn't capture requirements for maintainability, extensibility, or future scaling.

> "Architecture and instructions matter. Agents have immense engineering skill but will follow instructions to the end, good or bad."

**Dependency Philosophy**

Early runs lacked explicit dependency philosophy. Agents pulled libraries they should have implemented themselves, adding unnecessary weight. Later runs explicitly laid out:

- Which libraries are acceptable and must be used
- Which functionality must be implemented locally
- Rationale for each dependency decision

**The Monolith-to-Crates Restructuring**

One of the most dramatic improvements came from restructuring the codebase from a monolith to many self-contained crates. This was not just an infrastructure change — it was an intent specification: the system must work "across totally broken states."

> "Copy-on-write and deduplication as low-hanging fruit" emerged from this restructuring.

### Intent Specification Best Practices

Based on these learnings, Cursor developed intent specification patterns:

1. **Be Specific About Scope**: "Implement feature X" is too vague. "Implement feature X with priority: rendering, storage, API" provides guidance.

2. **Define Success Criteria**: What does "done" look like? Include acceptance criteria in every task.

3. **Specify Non-Goals**: What should NOT be done? Explicit exclusions prevent scope creep.

4. **Set Performance Bounds**: Include explicit latency, memory, and throughput requirements.

5. **Define Dependency Philosophy**: Which external libraries are allowed, which must be avoided, and why.

6. **Specify Architectural Constraints**: What patterns must be followed? What patterns are prohibited?

## 8. Prompt Engineering Principles

The hierarchy relies on specific prompt engineering patterns to maintain agent behavior.

### Treat Models Like Brilliant New Hire

Models are capable but new to the codebase. They need clear specifications of what to do, constraints on what not to do, and guardrails for edge cases. The model is not told every step — it is given a role and the tools to fulfill it.

### Constraints Over Instructions

Negative constraints are more effective than positive instructions:

- Say "NEVER write code" not "you should avoid writing code"
- Say "Do NOT plan" not "try not to plan too much"

Constraints are clearer and less subject to interpretation.

### Avoid Checkbox Mentality

> "Avoid checkbox mentality for higher-level or deeper tasks."

When instructions become a checklist of items to complete, agents focus on checking boxes rather than achieving the underlying goal. For complex tasks, specify outcomes and constraints rather than enumerated steps.

### Prompt Optimization Details

**Concrete Numbers Over Vague Quantities**

> "Give concrete numbers and ranges when discussing quantity of scope."

Instead of "generate many tasks," specify "20-100 tasks." The exact range conveys intent more clearly than vague quantity words.

**Instructional Minimalism**

> "Better to not instruct for things the model knows how to do, only things it doesn't know."

Don't instruct agents on basic programming concepts they already understand. Focus instructions on project-specific knowledge, organizational conventions, and task-specific requirements.

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

## 9. Freshness Mechanisms

Maintaining agent awareness over long-running tasks requires explicit freshness mechanisms.

### Scratchpad Rewriting

> "The scratchpad must be REWRITTEN, not appended to."

Appending creates unbounded growth and loses the signal in noise. Rewriting forces the agent to distill the current state into essential information. The scratchpad is rewritten every N turns with only the critical current state.

### Auto-Summarization

When context reaches 80% of capacity, the system automatically triggers summarization. This compresses the conversation history while preserving key facts, decisions, and progress.

### Self-Reflection Injection

Every N turns, the system injects a self-reflection prompt. This is independent of the normal message flow — it is a deliberate intervention to ensure the agent assesses its own progress.

### Identity Re-Injection

After every compression event (summarization or compaction), the system inserts the identity block at the start of the compressed context. This ensures the agent immediately knows its role and constraints after context reconstruction.

## 10. Infrastructure

The system requires specific infrastructure to support the hierarchy.

### Single Large Linux VM

> "Single large Linux VM, not distributed."

The infrastructure choice surprised many reviewers. Rather than a distributed system, Cursor ran on a single large Linux VM. This simplified coordination significantly — no network latency, no distributed consensus, no cross-machine synchronization.

### Disk as Bottleneck

> "Disk became the hotspot — hundreds of agents compiling simultaneously created many GB/s of reads and writes."

Even on a single VM, disk I/O became the primary bottleneck. The read/write throughput of hundreds of agents working simultaneously created massive I/O pressure. This informed the copy-on-write strategy: deduplication reduced redundant writes.

### Git and Cargo Shared Locks

> "Git and Cargo shared locks as a bottleneck with hundreds of agents."

With hundreds of agents attempting git operations and cargo builds simultaneously, lock contention became significant. The solution involved:
- Batching commits rather than per-task commits
- Local build verification before attempting merge
- Separate build caches per worker

### Copy-on-Write Filesystem

Each agent receives its own copy of the repository. Modifications are isolated until merge time. This is fundamental — without isolation, concurrent work would create conflicts in real-time.

### Monolith-to-Crates Restructuring

> "Monolith-to-crates restructuring improved throughput by multiple times."

Moving from a monolithic crate structure to many small crates had dramatic performance impact:
- Parallel compilation of independent crates
- Reduced build cache invalidation
- Better incremental compilation
- Clearer ownership boundaries

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

## 11. Design Principles

The architecture is governed by seven core design principles.

### 1. Anti-Fragile

Individual failures don't crash the system. When an agent fails, its error becomes a new task for other agents to address. The system absorbs failures rather than being derailed by them.

### 2. Optimistic Execution

The system accepts a small error rate combined with reconciliation rather than requiring 100% correctness before each commit. This enables high throughput.

> "Error rate stays 'small and constant, perhaps rarely completely clean but steady and manageable, not exploding or deteriorating.'"

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

### Empirical Over Assumption-Driven

> "These systems tend to be elegantly simple when done right, but it wasn't clear which simple approach would work until we explored many different approaches."

Cursor's approach was fundamentally empirical. Rather than assuming how multi-agent systems should work based on human organizations, they built, observed, and iterated. Many intuitive approaches failed; many counterintuitive ones succeeded.

> "No major further iterations have been necessary on the harness."

This confidence signal indicates the architecture reached a stable equilibrium.

## 12. Open Questions

The Cursor blog explicitly acknowledged areas of uncertainty or incomplete understanding.

### What Cursor Didn't Cover

1. **Browser/Visual Verification**: How does the system verify visual correctness? The blog mentions building a browser but doesn't detail how visual outputs are validated.

2. **Exact Freshness Thresholds**: What are the exact trigger points for summarization, scratchpad rewriting, and self-reflection injection? The blog describes the mechanisms but not the specific parameters.

3. **Agent Pool Scaling**: How does the system dynamically scale the number of agents based on workload? The blog implies dynamic scaling but doesn't detail the algorithm.

4. **Circuit Breaker Behavior**: When error rates spike, what specific actions does the system take? How quickly does it throttle new work?

5. **Comprehensive Audit Logging**: What is retained for compliance and debugging? The blog mentions activity logging but not the full retention policy.

6. **Conflict Detection Granularity**: How does the system detect conflicting work before merge? Is there proactive conflict detection or only reactive?

7. **Cost Attribution**: How are costs tracked per task, per agent, per sub-planner? The blog mentions throughput but not cost accounting.

8. **Graceful Degradation**: What happens when the system hits resource limits? Does it reduce parallelism, queue tasks, or fail gracefully?

9. **Recovery from Partial Failure**: If a SubPlanner fails mid-execution, how does the system recover? Are partial results preserved?

10. **Version-Specific Model Tuning**: Were different model versions used for different roles? Did Cursor tune prompts specifically for planner vs worker behaviors?

## 13. Session Mapping Table

The following table maps each learning session to the Cursor mechanism it teaches:

| Session | Cursor Mechanism           | Key Quote                                                      | Reference Section |
|---------|---------------------------|----------------------------------------------------------------|------------------|
| s12     | Structured Handoffs       | "The narrative is not optional metadata. It is the primary mechanism for propagating understanding up the hierarchy." | §5 Handoff Protocol |
| s13     | Scratchpad Rewriting      | "The scratchpad must be REWRITTEN, not appended to"            | §9 Freshness Mechanisms |
| s14     | Planner-Worker Split      | "Too many roles for one agent" (V5 lesson)                     | §4 Agent Roles |
| s15     | Worker Isolation          | "Each agent gets its own copy of the repo"                     | §10 Infrastructure |
| s16     | Optimistic Merge          | "DO NOT REVERT. The repo may be broken. This is by design."    | §6 Merge Strategy |
| s17     | Recursive Hierarchy       | "SubPlanner: Recursive — can spawn another SubPlanner"          | §4 Agent Roles |
| s18     | Error Tolerance           | "Errors become new tasks"                                       | §11 Design Principles |
| s19     | Failure Modes            | "Detects: zombies, tunnel vision, token burn"                  | §4 Watchdog |
| s20     | Reconciliation Pass      | "INIT → DECOMPOSE → ORCHESTRATE → RECONCILE → DONE"            | §4 Root Planner |

## 14. Gap Analysis: Our Harness vs Cursor

This section analyzes differences between what Cursor describes and what our educational harness (in `src/harness/`) implements.

### What We Implement

| Component | Sessions | Implementation |
|-----------|----------|----------------|
| Structured Handoffs | s12 | Diff + narrative + status + metrics in pydantic models |
| Scratchpad Rewriting | s13 | Rewrite mechanism with auto-summarization at 80% threshold |
| Planner-Worker Split | s14 | Distinct Planner and Worker classes with role constraints |
| Worker Isolation | s15 | Per-worker workspace copies in temporary directories |
| Optimistic Merge | s16 | 3-way merge with fix-forward on conflicts |
| Recursive Hierarchy | s17 | Root → SubPlanner → Worker tree structure |
| Error Tolerance | s18 | Error budgets, errors-as-tasks pattern |
| Watchdog | s19 | Zombie/tunnel-vision/burn detection with intervention |
| Reconciliation | s20 | Green branch verification + fixer loop (max 3 rounds) |
| Event Bus | — | Typed pydantic event models for observability |
| Shutdown/Resume | — | Signal handling with checkpoint and resume capability |

### What's Missing

| Gap | Description |
|-----|-------------|
| Browser/Visual Verification | No mechanism for verifying visual/UI correctness — we're text-only |
| Distributed Infrastructure | Single-process asyncio, not multi-VM distributed system |
| Intent Specification Framework | No formal framework for specifying task intent beyond prompts |
| Dynamic Agent Pool Scaling | Fixed worker pool size, no queue-depth-based scaling |
| Circuit Breakers | No explicit error rate monitoring that throttles new work |
| Comprehensive Audit Logging | Basic activity logging, not full audit trail for compliance |
| Copy-on-Write Filesystem | Uses temp directories, not copy-on-write filesystem features |
| Rust Acceleration (partial) | PyO3 crate exists but not fully integrated into all paths |
| Production Metrics Dashboarding | No real-time metrics visualization |

### What's Fundamentally Different

**Scale**

- Cursor: Thousands of agents, thousands of commits/hour
- Ours: 10-100 agents (configured), educational scale

The scale difference affects many design decisions. At Cursor's scale, disk I/O becomes a primary bottleneck; at our scale, it's negligible.

**Language/Runtime**

- Cursor: Unspecified but implied custom Rust implementation
- Ours: Python with optional PyO3 Rust acceleration

Python provides easier experimentation and educational clarity. Rust provides performance at massive scale.

**Purpose**

- Cursor: Production browser development, one-week intensive
- Ours: Educational tool for learning agent patterns

**Infrastructure Model**

- Cursor: Single large Linux VM with dedicated I/O infrastructure, copy-on-write filesystem, git/cargo lock optimization
- Ours: Portable across platforms, uses standard temp directory isolation

**Coordination Complexity**

- Cursor: Hierarchical with hundreds of SubPlanners, complex handoff aggregation, cross-agent conflict resolution
- Ours: Simplified hierarchy, typically 1-2 levels deep, cleaner merge semantics

### Detailed Gap Analysis

The following sections provide deeper analysis of each major gap between our implementation and Cursor's production system.

#### Browser/Visual Verification Gap

Cursor's target was building a browser engine, which requires verifying visual correctness. This introduces challenges our text-based harness doesn't face:

- Layout correctness across screen sizes
- Rendering accuracy for complex CSS
- Interactive behavior verification
- Performance under rendering load

Our harness is fundamentally text-based. We verify code correctness through build success and test execution, not visual output.

#### Distributed vs Single-Process

Cursor's infrastructure ran on a single large Linux VM, but it handled thousands of agents. This required:

- Efficient inter-process communication within the VM
- Shared filesystem with copy-on-write semantics
- Coordinated build caches
- Lock management for git and cargo operations

Our asyncio implementation runs in a single Python process. We don't face the same coordination challenges, but we also don't benefit from the parallelism that distributed execution enables.

#### Intent Specification Framework

Cursor discovered that intent specification was critical to success. Their evolution showed:

- Vague specifications led to poor outcomes
- Performance requirements needed explicit statement
- Dependency philosophy had to be explicit
- Architectural constraints required documentation

We have not built a formal framework for intent specification. Our prompts are implicit in agent initialization, not formalized as structured intent documents.

#### Dynamic Pool Scaling

Cursor's system could scale agent pools based on workload:

- Queue depth monitoring
- Automatic worker spawning
- Resource-aware allocation
- Load shedding under pressure

Our harness uses fixed pool sizes. Workers are created at initialization and persist through the run. We don't dynamically adjust based on backlog.

#### Circuit Breakers

Production systems need failure isolation:

- Error rate monitoring across all agents
- Automatic throttling when error rates spike
- Graceful degradation instead of cascade failures
- Recovery mechanisms after circuit opens

We implement basic error handling per-agent but lack system-wide circuit breaker patterns.

#### Audit Logging

Production compliance requires comprehensive logging:

- Every decision point logged
- Audit trail for regulatory requirements
- Forensic analysis capability
- Cost attribution tracking

Our activity logging is minimal: basic events with timestamps. We lack the comprehensive audit trail production systems require.

### Implications for Our Design

The gaps inform our roadmap priorities:

1. **Visual Verification** is out of scope for the educational harness — it requires browser automation infrastructure beyond our scope.

2. **Distributed Infrastructure** is explicitly not a goal — we teach patterns that work at our scale, noting where production differs.

3. **Intent Specification** could be added as a session — the principles from Section 7 map well to prompt engineering education.

4. **Dynamic Scaling** would enhance the harness but adds complexity — consider as future enhancement.

5. **Audit Logging** is valuable for debugging and could be added without major architectural changes.

The core patterns (handoffs, scratchpad, planner-worker split, isolation, merge, recursion, error tolerance, watchdog, reconciliation) are complete. Production enhancements can be layered on top as users progress from learning to implementation.

## Production Reference

This document serves as the architectural reference for the Cursor harness system. The production implementation extends these principles with:

- Real-time metrics dashboarding
- Dynamic scaling of agent pools based on queue depth
- Circuit breakers that throttle new work when error rates spike
- Comprehensive audit logging for compliance and debugging

The fundamental insight remains: treat models as capable agents that need clear roles, constraints, and coordination mechanisms rather than step-by-step instructions. The hierarchy enables scale by decomposing problems, delegating work, and compressing information at each level.

> "These models were not explicitly trained in this way, which suggests it's emergent behavior."

> "Virtuous AI loop" — AI used to develop AI, feeding back into itself.

The research points toward a future where AI systems build better AI systems, with each generation improving on the infrastructure that enables the next.

## Additional Observations

### Emergent Behavior

The most surprising finding from Cursor's research was that the multi-agent coordination patterns emerged naturally from simple rules. The models were not explicitly trained in this way, which suggests it's emergent behavior. Key emergent phenomena included:

- Self-organization into hierarchical structures
- Implicit coordination protocols without explicit messaging
- Adaptive task decomposition based on complexity
- Error recovery through implicit error handling

This suggests that with the right basic primitives, complex organizational behaviors can emerge without explicit programming of those behaviors.

### The Virtuous AI Loop

Cursor's research demonstrates what they call a "virtuous AI loop": AI used to develop AI, feeding back into itself. The browser built by AI agents was used to improve AI capabilities, which in turn improved the agents' ability to build better systems. This recursive improvement is a fundamental insight about the nature of AI-assisted development.

### Implications for Software Development

> "There's a poetic resemblance in this research to how some software teams operate today."

The multi-agent system mirrors human software organizations:

- Planners as technical leads who decompose work
- Workers as individual contributors who execute
- SubPlanners as team leads managing subsets
- Watchdog as QA/monitoring
- Handoffs as code reviews
- Reconciliation as integration and release

The difference is speed: what takes days or weeks in human organizations took hours in the AI system.

### Lessons for Agent System Design

1. **Start Simple**: V1-V4 all had single points of failure. The breakthrough came from clean separation of concerns.

2. **Embrace Optimism**: Requiring perfection blocks progress. Accept small error rates with reconciliation mechanisms.

3. **Compress Everything**: Information compression at each layer enables scale. Without it, the hierarchy drowns in detail.

4. **Separate Roles Strictly**: One role per agent. Mixing roles creates pathological behaviors that are hard to debug.

5. **Let Emergence Happen**: Don't over-specify. Give agents primitives and let organization emerge.

6. **Build Anti-Fragility**: Design for failure. When agents fail, the system should absorb and continue, not crash and burn.

(End of file)
