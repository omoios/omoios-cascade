# s19: Failure Modes

> Agents get stuck. The Watchdog detects failure modes, kills stuck agents, and triggers respawn to keep the system moving.

## The Problem: Agents Get Stuck in Failure Modes

Even well-designed agents can get stuck. In a multi-agent system running hundreds of concurrent agents, failure is inevitable. The system must detect and recover from failure automatically.

Four primary failure modes emerge in autonomous agent systems:

**Zombies** — Agents that stop sending heartbeats. No activity for an extended period. The agent appears alive (process running) but is unresponsive. Could be stuck in an infinite loop, waiting on external input, or crashed silently.

**Tunnel Vision** — Agents making 50+ edits to the same file without progress. The agent believes it is working, but is trapped in a local optimum, repeatedly trying the same approach that isn't working. No external intervention breaks the cycle.

**Token Burn** — High token spend with no measurable progress. The agent is consuming resources (API quota, compute time) while producing no useful output. Could be generating excessive logs, making redundant tool calls, or spinning in reasoning loops.

**Scope Creep** — Agent drifting beyond its delegated boundaries. A worker assigned to "fix the login button" begins refactoring the entire authentication system. The agent exceeded its scope and now works on unrequested features.

These failures cascade. One stuck agent blocks dependent tasks. Resource leaks from token burn degrade system performance. Scope creep introduces unrelated changes that break merges. Without detection and recovery, the system grinds to a halt.

## The Solution: Watchdog Monitoring

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATION LAYER                          │
│                                                                      │
│   ┌─────────────┐      ┌─────────────┐      ┌─────────────┐        │
│   │  SubPlanner │      │  SubPlanner │      │  SubPlanner │        │
│   │     A       │      │     B       │      │     C       │        │
│   └──────┬──────┘      └──────┬──────┘      └──────┬──────┘        │
│          │                    │                    │                │
│   ┌──────┴──────┐      ┌──────┴──────┐      ┌──────┴──────┐      │
│   │   Workers   │      │   Workers   │      │   Workers   │      │
│   │  A1, A2, A3│      │  B1, B2, B3│      │  C1, C2, C3│      │
│   └─────────────┘      └─────────────┘      └─────────────┘      │
│                                                                      │
│                         ╔═══════════════════╗                       │
│                         ║     WATCHDOG      ║  ← DAEMON MONITOR   │
│                         ║   (Independent)    ║    No planning      │
│                         ║                    ║    authority        │
│                         ║  • heartbeat check ║                     │
│                         ║  • progress audit  ║                     │
│                         ║  • resource track ║                     │
│                         ║  • scope validate  ║                     │
│                         ╚═══════════════════╝                       │
└─────────────────────────────────────────────────────────────────────┘
```

The Watchdog operates as an independent daemon, outside the planning hierarchy. It does not plan, delegate, or make strategic decisions. Its sole purpose is monitoring agent health and intervention when failure conditions are detected.

## How It Works: Detection → Kill → Respawn Cycle

The Watchdog operates in a continuous loop, checking each agent against failure conditions:

**1. Detection Phase**

Every N seconds, the Watchdog examines all active agents:

```
for agent_id in active_agents:
    # Zombie check: no heartbeat recently
    if time_since_last_heartbeat(agent_id) > ZOMBIE_THRESHOLD:
        mark_failure(agent_id, FailureType.ZOMBIE)
    
    # Tunnel vision check: same file edited repeatedly
    if edits_without_progress(agent_id) > TUNNEL_VISION_THRESHOLD:
        mark_failure(agent_id, FailureType.TUNNEL_VISION)
    
    # Token burn check: high spend, no output
    if token_efficiency(agent_id) < TOKEN_EFFICIENCY_MIN:
        mark_failure(agent_id, FailureType.TOKEN_BURN)
    
    # Scope creep check: working outside delegation
    if outside_scope(agent_id):
        mark_failure(agent_id, FailureType.SCOPE_CREEP)
```

**2. Kill Phase**

For agents flagged as failures, the Watchdog sends interrupt signals:

```
for agent_id, failure in detected_failures.items():
    # Send interrupt, allow graceful shutdown
    interrupt_agent(agent_id)
    
    # If no response in timeout, force kill
    if not graceful_shutdown(agent_id, timeout=5):
        force_kill(agent_id)
    
    # Log failure for analysis
    log_failure(agent_id, failure)
```

**3. Respawn Phase**

After termination, the Watchdog triggers task redistribution:

```
for task_id in terminated_agent.tasks:
    # Return task to queue for re-claim
    requeue_task(task_id)
    
    # Notify parent of failure
    notify_parent(terminated_agent.parent, task_id)
```

The parent agent receives notification that its child failed. It can then decide to respawn the task, adjust its approach, or escalate to its own parent. The system continues without manual intervention.

## Key Code: Watchdog Class

```python
from enum import Enum
from dataclasses import dataclass
from typing import Callable
import threading
import time

class FailureType(Enum):
    ZOMBIE = "zombie"           # No heartbeat
    TUNNEL_VISION = "tunnel"    # Repeated edits, no progress
    TOKEN_BURN = "token_burn"   # High spend, no output
    SCOPE_CREEP = "scope_creep" # Outside delegation

@dataclass
class AgentMetrics:
    agent_id: str
    last_heartbeat: float
    tokens_spent: int
    files_modified: dict[str, int]  # file -> edit count
    output_lines: int
    scope: str

class Watchdog:
    """Independent failure detection and recovery for agent teams."""
    
    def __init__(
        self,
        check_interval: float = 10.0,
        zombie_threshold: float = 120.0,
        tunnel_threshold: int = 50,
        token_efficiency_threshold: float = 0.1,
        on_failure: Callable[[str, FailureType], None] | None = None
    ):
        self.check_interval = check_interval
        self.zombie_threshold = zombie_threshold
        self.tunnel_threshold = tunnel_threshold
        self.token_efficiency_threshold = token_efficiency_threshold
        self.on_failure = on_failure
        
        self.agents: dict[str, AgentMetrics] = {}
        self.running = False
        self._thread: threading.Thread | None = None
    
    def register_agent(self, agent_id: str, scope: str) -> None:
        """Register a new agent for monitoring."""
        self.agents[agent_id] = AgentMetrics(
            agent_id=agent_id,
            last_heartbeat=time.time(),
            tokens_spent=0,
            files_modified={},
            output_lines=0,
            scope=scope
        )
    
    def heartbeat(self, agent_id: str) -> None:
        """Agent calls this to signal continued activity."""
        if agent_id in self.agents:
            self.agents[agent_id].last_heartbeat = time.time()
    
    def record_activity(
        self,
        agent_id: str,
        tokens: int = 0,
        file: str | None = None,
        output_lines: int = 0
    ) -> None:
        """Record agent activity for failure detection."""
        if agent_id not in self.agents:
            return
        
        metrics = self.agents[agent_id]
        metrics.tokens_spent += tokens
        metrics.output_lines += output_lines
        
        if file:
            metrics.files_modified[file] = metrics.files_modified.get(file, 0) + 1
    
    def _check_failures(self) -> list[tuple[str, FailureType]]:
        """Check all agents for failure conditions."""
        failures = []
        now = time.time()
        
        for agent_id, metrics in self.agents.items():
            # Zombie: no heartbeat
            if now - metrics.last_heartbeat > self.zombie_threshold:
                failures.append((agent_id, FailureType.ZOMBIE))
                continue
            
            # Tunnel vision: same file edited too many times
            for file, count in metrics.files_modified.items():
                if count > self.tunnel_threshold:
                    failures.append((agent_id, FailureType.TUNNEL_VISION))
                    break
            
            # Token burn: high spend, minimal output
            if metrics.output_lines > 0:
                efficiency = metrics.output_lines / max(metrics.tokens_spent, 1)
                if efficiency < self.token_efficiency_threshold:
                    failures.append((agent_id, FailureType.TOKEN_BURN))
        
        return failures
    
    def _run_loop(self) -> None:
        """Main Watchdog monitoring loop."""
        while self.running:
            failures = self._check_failures()
            
            for agent_id, failure_type in failures:
                print(f"[Watchdog] Detected {failure_type.value} for {agent_id}")
                
                if self.on_failure:
                    self.on_failure(agent_id, failure_type)
                
                # Remove from monitoring
                self.agents.pop(agent_id, None)
            
            time.sleep(self.check_interval)
    
    def start(self) -> None:
        """Start the Watchdog daemon."""
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop the Watchdog daemon."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
```

## What Changed: s18 vs s19 Comparison

| Aspect | s18 Error Tolerance | s19 Failure Modes |
|--------|---------------------|-------------------|
| Failure view | Errors as tasks to solve | Agents stuck and unresponsive |
| Response | Spawn fix tasks | Kill stuck agents, respawn |
| Monitoring | Post-hoc analysis | Real-time detection |
| Recovery | Human-mediated | Automatic via Watchdog |
| Scope | System-level resilience | Individual agent health |

S18 introduced error tolerance: when errors occur, they become new tasks for other agents. S19 builds on this by detecting when agents themselves are failing, not just their outputs. The Watchdog provides continuous health monitoring rather than relying on post-hoc error discovery.

**Key insight**: The Watchdog acts as an independent health monitor. It does not participate in planning or delegation. It watches for specific failure patterns and intervenes when detected, enabling the system to recover without human oversight.

## Production Reference: Cursor's Watchdog Agent

Primary source: docs/reference/cursor-harness-notes.md (Section 4: Agent Roles -> Watchdog).

From the Cursor harness architecture, the Watchdog role provides independent monitoring:

> **Watchdog**: Detects zombies (agents that stop sending heartbeats), tunnel vision (agents making 50+ edits to the same file without progress), token burn (high token spend with no measurable progress), and scope creep (agent drifting beyond its delegated boundaries). Actions: sends interrupt signals to problematic agents, can kill agents that exceed resource bounds, does NOT make planning decisions — only monitors and intervenes.

The Watchdog operates as a daemon thread with independent monitoring logic. It does not participate in planning or delegation — its sole purpose is detecting and responding to failure modes.

The production implementation monitors heartbeat intervals, tracks file edit counts per agent, measures token efficiency ratios, validates scope boundaries, and can trigger graceful shutdown or force kill based on failure severity.

## Try It: How to Test Failure Detection

Test the Watchdog with scenarios that trigger each failure mode:

```python
# Test 1: Zombie detection
# Run an agent that never calls heartbeat()
# After zombie_threshold (120s default), Watchdog should detect and kill

# Test 2: Tunnel vision
# Create agent that edits same file 50+ times without progress
# Watchdog should intervene at threshold

# Test 3: Token burn
# Create agent that spends tokens but produces no output
# Low efficiency ratio triggers failure

# Test 4: Scope creep
# Agent working outside its delegated scope
# Scope validation catches drift
```

Run the test harness:

```bash
# Run the s19 agent with Watchdog logging
python agents/s19_failure_modes.py --verbose

# Watch for detection messages:
# [Watchdog] Detected zombie for agent_123
# [Watchdog] Detected tunnel_vision for agent_456
```

**Verification checklist:**

1. Zombie detection triggers after heartbeat timeout
2. Tunnel vision catches repeated file edits
3. Token burn flags low-efficiency agents
4. Respawn returns tasks to queue
5. Parent agents receive failure notifications
6. System continues without manual intervention

The Watchdog transforms failure from a system-stopping event into a routine recovery scenario. Agents can fail, and the system automatically detects, cleans up, and respawns to keep work moving.
