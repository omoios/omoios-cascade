# s18: Error Tolerance

> "Individual failures don't crash the system. When an agent fails, its error becomes a new task for other agents to address." — Cursor Design Principles

Error tolerance transforms failures from system-stopping events into manageable workflow data. This session covers how to build systems that absorb errors rather than halt on them.

---

## The Problem: Systems that Halt on Errors Fail

Traditional software treats errors as exceptional conditions requiring immediate attention. When an error occurs, the system stops, logs the failure, and often requires manual intervention to recover. This works fine for small-scale systems but collapses under the weight of parallel agent orchestration.

Consider a harness running 50 concurrent agents. If each agent encounters even a 5% error rate, you're looking at 2-3 failures per cycle. If the system halts on each error, you get:

- **Cascading stoppages**: One agent error stops the entire workflow
- **Manual recovery bottlenecks**: A human must inspect and restart each failure
- **Throughput collapse**: Error handling becomes the dominant operation
- **Context loss**: When the system halts, it loses track of what was in progress

The fundamental issue is philosophical: most systems treat errors as *exceptions* that break the happy path. But in a high-throughput multi-agent system, errors are *expected behavior*. The system must treat them as data, not events that require stopping.

---

## The Solution: Error Becomes Task

```
┌─────────────────────────────────────────────────────────────────┐
│                    NORMAL WORKFLOW                               │
│                                                                 │
│    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│    │ Planner │───▶│ Worker  │───▶│ Worker  │───▶│ Worker  │  │
│    │   A     │    │    1    │    │    2    │    │    3    │  │
│    └─────────┘    └─────────┘    └─────────┘    └─────────┘  │
│                              │                                  │
│                              ▼                                  │
│                        ┌───────────┐                             │
│                        │  Success  │                             │
│                        │   Merge   │                             │
│                        └───────────┘                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    ERROR WORKFLOW                                │
│                                                                 │
│    ┌─────────┐    ┌─────────┐    ┌─────────────────────────┐  │
│    │ Planner │───▶│ Worker  │───▶│    ERROR DETECTED       │  │
│    │   A     │    │    2    │    │  (build fail, conflict) │  │
│    └─────────┘    └─────────┘    └───────────┬─────────────┘  │
│                                               │                 │
│                                               ▼                 │
│                        ┌───────────────────────────────────────┐  │
│                        │  SPAWN FIX TASK                      │  │
│                        │  error_type: build_failure          │  │
│                        │  priority: high                     │  │
│                        │  parent: worker_2                   │  │
│                        └───────────────┬───────────────────────┘  │
│                                        │                         │
│                                        ▼                         │
│                        ┌───────────────────────────┐             │
│                        │     WORKER 2 CONTINUES    │             │
│                        │  (original task archived) │             │
│                        └───────────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

The key insight: errors don't halt the workflow. They *branch* it. The original task continues forward while a new task spawns to address the error. The system processes both in parallel.

---

## How It Works

### Error Budget

An error budget defines how many failures the system tolerates before escalating. Think of it like a financial budget:

```python
class ErrorBudget:
    def __init__(self, max_errors: int = 10, window_seconds: int = 300):
        self.max_errors = max_errors
        self.window_seconds = window_seconds
        self.errors: list[ErrorEvent] = []
    
    def can_continue(self) -> bool:
        self._prune_old_errors()
        return len(self.errors) < self.max_errors
    
    def record(self, error: ErrorEvent):
        self.errors.append(error)
    
    def _prune_old_errors(self):
        cutoff = time.time() - self.window_seconds
        self.errors = [e for e in self.errors if e.timestamp > cutoff]
```

The budget resets over time (the window), allowing the system to recover after absorbing errors. If errors exceed the budget, the system escalates to a higher-level handler rather than continuing to spawn fix tasks blindly.

### Error Categorization

Not all errors are equal. The system categorizes them:

| Category | Description | Response |
|----------|-------------|----------|
| `recoverable` | Build failure, missing dependency | Spawn fix task, continue original work |
| `conflict` | File modified by another agent | Spawn merge task, continue original |
| `blocked` | Requires external input | Pause task, notify human |
| `fatal` | Invalid state, security violation | Terminate agent, escalate |

Each category triggers a different workflow. Recoverable errors are handled automatically. Blocked errors wait for input. Fatal errors trigger system-level intervention.

### Fix-Forward Pattern

The core principle: never revert, always fix forward.

```python
def handle_error(agent: Agent, error: Error) -> Optional[Task]:
    if error.category == "recoverable":
        # Archive original task state
        agent.archive_current_task(error.context)
        
        # Spawn fix task
        fix_task = Task(
            type="fix_error",
            error_type=error.type,
            error_context=error.context,
            original_task_id=agent.current_task.id,
        )
        return fix_task
    
    elif error.category == "fatal":
        # Terminate and escalate
        agent.terminate()
        escalate_to_planner(error)
        return None
    
    else:
        # Blocked - wait for input
        agent.pause()
        notify_human(error)
        return None
```

This approach accepts that the repository may be in a broken state during reconciliation. That's by design. The alternative (reverting changes) loses work and creates a different problem.

---

## Key Code: ErrorPolicy Class

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import time

class ErrorSeverity(Enum):
    LOW = "low"           # Non-critical, log and continue
    MEDIUM = "medium"    # Needs fix but non-blocking
    HIGH = "high"        # Must fix before proceeding
    CRITICAL = "critical" # System-level intervention needed

class ErrorCategory(Enum):
    RECOVERABLE = "recoverable"
    CONFLICT = "conflict"
    BLOCKED = "blocked"
    FATAL = "fatal"

@dataclass
class ErrorEvent:
    timestamp: float
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    context: dict
    agent_id: str

@dataclass
class ErrorPolicy:
    max_errors_per_window: int = 10
    window_seconds: int = 300
    retry_before_escalate: int = 3
    enable_fix_forward: bool = True
    
    def should_retry(self, error: ErrorEvent) -> bool:
        """Decide if error warrants a retry attempt."""
        if error.severity == ErrorSeverity.CRITICAL:
            return False
        if error.category == ErrorCategory.FATAL:
            return False
        return True
    
    def should_spawn_fix(self, error: ErrorEvent) -> bool:
        """Decide if error should spawn a fix task."""
        if not self.enable_fix_forward:
            return False
        return error.category in (
            ErrorCategory.RECOVERABLE,
            ErrorCategory.CONFLICT,
        )
    
    def should_terminate(self, error: ErrorEvent) -> bool:
        """Decide if agent should terminate."""
        return error.category == ErrorCategory.FATAL
    
    def should_block(self, error: ErrorEvent) -> bool:
        """Decide if workflow should block for human input."""
        return error.category == ErrorCategory.BLOCKED

class ErrorBudget:
    def __init__(self, policy: ErrorPolicy):
        self.policy = policy
        self.errors: list[ErrorEvent] = []
    
    def record(self, error: ErrorEvent):
        self.errors.append(error)
    
    def is_exhausted(self) -> bool:
        cutoff = time.time() - self.policy.window_seconds
        recent = [e for e in self.errors if e.timestamp > cutoff]
        return len(recent) >= self.policy.max_errors_per_window
    
    def get_error_rate(self) -> float:
        if not self.errors:
            return 0.0
        cutoff = time.time() - self.policy.window_seconds
        recent = [e for e in self.errors if e.timestamp > cutoff]
        return len(recent) / self.policy.window_seconds * 60  # errors per minute
```

This class provides the decision logic for error handling. The `ErrorPolicy` defines *what* to do with errors. The `ErrorBudget` tracks *how many* errors have occurred.

---

## What Changed: s17 vs s18 Comparison

| Aspect | s17 (Recursive Hierarchy) | s18 (Error Tolerance) |
|--------|-------------------------|----------------------|
| Error response | Not handled | Spawns fix tasks |
| Failed task | Agent halts | Archives, continues |
| Error tracking | None | Error budget + categorization |
| Recovery | Manual restart | Automatic fix-forward |
| Throughput | Limited by failures | Absorbs failures gracefully |
| State on error | Stopped | Broken but processing |

The key difference: s17 builds the hierarchical structure for delegation, but it assumes tasks succeed. s18 adds the failure absorber that makes the hierarchy resilient.

In s17, when a Worker fails, the SubPlanner waits for human intervention or retry. In s18, the Worker archives its failed state and spawns a fix task, then continues with other work. The SubPlanner sees the error as a completed task (with a spawned child) rather than a blocked state.

---

## Production Reference: Cursor's Anti-Fragile Principle

Primary source: docs/reference/cursor-harness-notes.md (Section 10: Design Principles -> Anti-Fragile).

> **Anti-Fragile**: Individual failures don't crash the system. When an agent fails, its error becomes a new task for other agents to address. The system absorbs failures rather than being derailed by them.

The production implementation adds:

- **Circuit breakers**: Throttle new work when error rates spike
- **Real-time metrics**: Error rate dashboards
- **Dynamic scaling**: Reduce agent pools when error rates climb
- **Audit logging**: Track error provenance for debugging

The fundamental insight: don't try to prevent all errors. Instead, build a system that treats errors as expected data and processes them through the same workflow as successful work.

---

## Try It: How to Test Error Handling

### Test 1: Build Failure Absorption

```python
def test_build_failure_absorption():
    """Verify that build failures spawn fix tasks without halting."""
    policy = ErrorPolicy(enable_fix_forward=True)
    budget = ErrorBudget(policy)
    
    # Simulate build failure
    error = ErrorEvent(
        timestamp=time.time(),
        category=ErrorCategory.RECOVERABLE,
        severity=ErrorSeverity.MEDIUM,
        message="Build failed: missing import",
        context={"file": "main.py", "error": "ImportError"},
        agent_id="worker_1"
    )
    
    assert policy.should_spawn_fix(error) is True
    assert policy.should_terminate(error) is False
    budget.record(error)
    
    print("Build failure correctly spawns fix task")
```

### Test 2: Error Budget Exhaustion

```python
def test_error_budget_exhaustion():
    """Verify system escalates when error budget is exceeded."""
    policy = ErrorPolicy(max_errors_per_window=3)
    budget = ErrorBudget(policy)
    
    for i in range(3):
        error = ErrorEvent(
            timestamp=time.time(),
            category=ErrorCategory.RECOVERABLE,
            severity=ErrorSeverity.MEDIUM,
            message=f"Error {i+1}",
            context={},
            agent_id="worker_1"
        )
        budget.record(error)
    
    assert budget.is_exhausted() is True
    print("Error budget correctly triggers escalation")
```

### Test 3: Fix-Forward Workflow

```python
def test_fix_forward_workflow():
    """Verify original task continues after spawning fix."""
    policy = ErrorPolicy(enable_fix_forward=True)
    
    error = ErrorEvent(
        timestamp=time.time(),
        category=ErrorCategory.CONFLICT,
        severity=ErrorSeverity.HIGH,
        message="Merge conflict in api.py",
        context={"file": "api.py", "conflict": True},
        agent_id="worker_2"
    )
    
    # Should spawn fix, not terminate
    assert policy.should_spawn_fix(error) is True
    assert policy.should_terminate(error) is False
    
    print("Conflict spawns merge task, worker continues")
```

Run these tests to verify error handling works as expected before deploying to production.

---

## Summary

Error tolerance transforms failures from system-stopping exceptions into manageable workflow data. The key mechanisms:

1. **Error budget** — Track errors over time, escalate when threshold exceeded
2. **Error categorization** — Route different errors through appropriate handlers
3. **Fix-forward** — Never revert, always spawn fix tasks and continue
4. **Anti-fragile design** — Individual failures don't crash the system

This pattern enables the high throughput (1,000+ commits/hour) that makes parallel agent orchestration viable.
