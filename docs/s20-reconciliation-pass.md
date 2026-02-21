# s20: Reconciliation Pass — The Final Sweep

> The reconciliation pass is the final verification step in the harness lifecycle. It answers the question every complex system must answer: how do we know when we're actually done?

## The Problem: How Do We Know When We're Done?

In a system with dozens of concurrent agents, each producing handoffs, each submitting merge attempts, each generating fix tasks, the fundamental question becomes: when can we declare success?

Consider what the system has accumulated by s19:

- Workers have submitted handoffs with diffs and narratives
- Optimistic merges have attempted integration, creating fix tasks for conflicts
- The error tolerance policy has tracked error rates and potentially reduced parallelism
- The watchdog has detected and handled failure modes like zombies and tunnel vision
- Recursive hierarchy has coordinated SubPlanners spawning more SubPlanners

The output of s19 is not a clean codebase. It is a **working directory with known issues**:
- Some merges succeeded
- Some merges conflicted and spawned fix tasks
- Some workers failed and their tasks were re-queued
- The canonical repo may be in a broken state (by design from s16)

Without reconciliation, you have a pile of attempted work, not a completed project. The question s20 answers is: how do we sweep up all the loose ends and arrive at a green, shippable state?

## The Solution: Reconciliation Flow

```
                    ┌─────────────────────────────────────┐
                    │        RECONCILIATION PASS          │
                    │    (Final verification & cleanup)   │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  1. Take snapshot of canonical    │
                    │     (what's the current state?)    │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  2. Run validation suite         │
                    │     (build + tests + lint)        │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  3. Collect all failures         │
                    │     (fix tasks + failed merges)   │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  4. Spawn fixer agents            │
                    │     (for each unresolved issue)   │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  5. Re-merge and re-validate    │
                    │     (iterate until green)        │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  6. Final snapshot = GREEN      │
                    │     (reconciliation complete)     │
                    └─────────────────────────────────────┘
```

The reconciliation pass is not a single pass. It is an **iterate-until-green loop** that runs after the main orchestration phase completes.

## How It Works: Snapshot → Test → Fix Loop

The reconciliation pass operates through five distinct phases:

**Phase 1: Snapshot**

Before reconciliation begins, the system captures the current state of the canonical repository. This serves as the baseline for measuring progress. The snapshot includes:
- All file contents in the canonical repo
- All pending fix tasks in the task board
- All failed merge attempts in the merge log
- Current error rate from the error policy tracker

**Phase 2: Validation**

The system runs a validation suite against the current state:
- Build check (Python: `python -m py_compile` or equivalent)
- Lint check (basic syntax validation)
- Import validation (verify dependencies resolve)

This is intentionally lightweight. Full test suites take too long for reconciliation speed. The goal is fast feedback, not comprehensive coverage.

**Phase 3: Failure Collection**

Based on validation results and the fix task queue, the system compiles a list of all issues requiring resolution:
- Failed build tasks from merge attempts
- Unresolved fix tasks from conflicts
- Partially failed handoffs that need follow-up
- Any zombie tasks that never completed

**Phase 4: Fix Spawning**

For each collected failure, the system spawns a dedicated fixer agent:
- Fixers receive the full context: what failed, why, what was attempted
- Fixers operate in isolated workspaces like regular workers
- Fixers submit their own handoffs when complete
- Fixers are high-priority and bypass normal queuing

**Phase 5: Re-Merge and Re-Validate**

After fixers complete, the system:
- Attempts to merge each fixer's handoff
- Re-runs validation suite
- If validation passes: marks the issue resolved
- If validation fails: collects new failures and loops back to Phase 3

The loop terminates when either:
- All validations pass (success)
- Maximum iterations reached (partial success with report)
- No new progress possible (failure with full accounting)

## Key Code: ReconciliationPass Class

```python
class ReconciliationPass:
    """Coordinates the final verification and cleanup phase."""
    
    def __init__(
        self,
        task_board: TaskBoard,
        merge_manager: MergeManager,
        workspace_manager: WorkspaceManager,
        error_policy: ErrorPolicy,
        max_iterations: int = 5
    ):
        self.task_board = task_board
        self.merge_manager = merge_manager
        self.workspace_manager = workspace_manager
        self.error_policy = error_policy
        self.max_iterations = max_iterations
    
    def reconcile(self) -> ReconciliationReport:
        """Execute reconciliation pass until green or max iterations."""
        
        for iteration in range(1, self.max_iterations + 1):
            # Phase 1: Snapshot current state
            snapshot = self._capture_snapshot()
            
            # Phase 2: Run validation suite
            validation_results = self._run_validation(snapshot)
            
            if validation_results.is_green:
                return ReconciliationReport(
                    success=True,
                    iterations=iteration,
                    snapshot=snapshot,
                    issues_resolved=self._count_resolved(),
                    final_state="GREEN"
                )
            
            # Phase 3: Collect failures
            failures = self._collect_failures(validation_results)
            
            # Phase 4: Spawn fixers for each failure
            fixer_ids = []
            for failure in failures:
                fixer_id = self._spawn_fixer(failure)
                fixer_ids.append(fixer_id)
            
            # Wait for all fixers to complete
            self._wait_for_fixers(fixer_ids)
            
            # Phase 5: Re-merge and re-validate (loop)
            # Continue to next iteration
        
        # Max iterations reached - return partial success
        return ReconciliationReport(
            success=False,
            iterations=self.max_iterations,
            snapshot=self._capture_snapshot(),
            issues_resolved=self._count_resolved(),
            final_state="PARTIAL",
            remaining_issues=self._collect_failures(None)
        )
    
    def _spawn_fixer(self, failure: Failure) -> str:
        """Spawn a dedicated fixer agent for a specific failure."""
        
        # Create fix task with full context
        fix_task = Task(
            title=f"Fix: {failure.description}",
            description=failure.full_context,
            priority="CRITICAL",
            assigned_agent=None  # Will be auto-claimed
        )
        
        self.task_board.create(fix_task)
        
        # Spawn worker with fix context
        fixer_id = self.workspace_manager.spawn_worker(
            task_id=fix_task.id,
            context={
                "failure": failure.to_dict(),
                "original_handoffs": failure.related_handoffs,
                "canonical_state": failure.canonical_snapshot
            }
        )
        
        return fixer_id
```

The ReconciliationReport includes:
- Success flag (true if green achieved)
- Iteration count
- Initial and final snapshots
- Count of issues resolved
- Final state (GREEN, PARTIAL, or FAILED)
- List of remaining unresolved issues

## What Changed: Full s12-s20 Progression Summary

The Phase 5 sessions (s12-s20) represent an evolution from a flat autonomous team to a full hierarchical multi-agent harness. Here is the complete progression:

| Session | Mechanism | LOC Range | What It Added |
|---------|-----------|-----------|---------------|
| s12 | Structured Handoffs | ~550 | Workers submit diffs + narratives instead of silent completion |
| s13 | Scratchpad Rewriting | ~600 | REWRITE not APPEND, auto-summarization at 80%, self-reflection |
| s14 | Planner-Worker Split | ~650 | Separate roles with distinct tool sets, no code for planners |
| s15 | Worker Isolation | ~700 | Per-worker workspace copies, no filesystem conflicts |
| s16 | Optimistic Merge | ~750 | Fix-forward merge strategy, never revert |
| s17 | Recursive Hierarchy | ~800 | SubPlanners can spawn SubPlanners, unbounded depth |
| s18 | Error Tolerance | ~800 | Accept small error rate, errors become tasks |
| s19 | Failure Modes | ~850 | Zombie detection, tunnel vision, token burn monitoring |
| s20 | Reconciliation Pass | ~900 | Final sweep to achieve green state |

Each session builds on the previous:
- s12 provides the handoff format that s13-s20 use
- s13 provides the scratchpad that keeps long-running agents coherent
- s14 establishes the role separation that enables hierarchy
- s15 provides the isolation that enables safe parallel work
- s16 provides the merge strategy that integrates work
- s17 provides the hierarchy that scales coordination
- s18 provides the error policy that keeps the system moving
- s19 provides the watchdog that detects pathological behavior
- s20 provides the final verification that declares completion

The LOC progression (550→900) reflects increasing complexity as the system accumulates mechanisms. The final s20 agent combines all nine mechanisms into a single coherent system.

## Production Reference: Cursor's Root Planner Lifecycle

Primary source: docs/reference/cursor-harness-notes.md (Section 4: Root Planner lifecycle).

From the Cursor harness architecture, the Root Planner follows a five-phase lifecycle:

```
INIT → DECOMPOSE → ORCHESTRATE → RECONCILE → DONE
```

**INIT**: Initialize, load problem description, establish canonical repo state

**DECOMPOSE**: Break the problem into scopes, delegate to SubPlanners

**ORCHESTRATE** (loop): Coordinate work, receive handoffs, spawn more agents as needed

**RECONCILE**: The final sweep. After orchestration completes, verify all work, fix remaining issues, achieve green state

**DONE**: Report final status, output metrics, clean up resources

The reconciliation phase in Cursor is not optional. It is the mechanism that transforms "a bunch of attempted work" into "a completed project." Without reconciliation, you have a repository with unmerged handoffs, unresolved fix tasks, and unknown build status.

The key insight from Cursor: reconciliation is where the "small error rate" from the error tolerance policy gets resolved. The system deliberately accepts errors during orchestration (for throughput), then systematically resolves them during reconciliation.

## Try It: Full System Test

Test the complete harness with all mechanisms:

```bash
# Run the full s20 agent with verbose logging
python agents/s20_reconciliation.py --task "build a REST API"

# Or use the combined full agent
python agents/s_full.py --task "build a REST API"
```

**Verification checklist:**

1. Root Planner enters INIT phase and loads problem
2. Root Planner enters DECOMPOSE and spawns SubPlanners
3. SubPlanners spawn Workers for different scopes
4. Workers execute in isolated workspaces
5. Workers submit structured handoffs with diffs
6. Optimistic merge attempts integrate worker output
7. Conflicts spawn fix-forward tasks
8. Error policy tracks rate and adapts parallelism
9. Watchdog monitors for failure modes
10. After orchestration, RECONCILE phase begins
11. Validation suite runs against current state
12. Failures spawn dedicated fixers
13. Fixers submit their own handoffs
14. Re-merge and re-validate loop runs
15. Final state achieves GREEN or PARTIAL with report

**Expected output:**

- Initial decomposition creates multiple scopes
- Workers produce handoffs at varying rates
- Merge attempts show clean/conflict/failure distributions
- Reconciliation iterates until validation passes
- Final report shows issues resolved, iteration count, final state

## Key Takeaway

s20 represents the culmination of the Phase 5 journey. It answers the fundamental question: how do we know when we're done?

The answer is not "when all tasks are marked complete." The answer is "when the final validation passes." This distinction matters because in a concurrent system with error tolerance, "task complete" does not mean "work is integrated and verified."

The reconciliation pass is the final sweep that transforms attempted work into delivered value. It is the difference between "we tried" and "we succeeded."
