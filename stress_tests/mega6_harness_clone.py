#!/usr/bin/env python3
"""Mega Tier 16: Multi-Agent Orchestration Harness Clone.

Complexity: 120-180 workers, ~350 files, ~20K LOC.
Task: Build a simplified clone of the harness described in the Cursor research — a
multi-agent orchestration system with planner agents, worker agents, task board,
structured handoffs, workspace isolation (per-worker directories), 3-way merge with
conflict resolution, event bus for observability, watchdog for failure detection,
error budget tracking, and reconciliation loop. This is a meta-harness that
recreates the core patterns from s12-s20 of the learning series.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-mega-6"
WORKER_TIMEOUT = 1800

SCAFFOLD_FILES = {
    "orchestrator/__init__.py": '''\
"""Orchestrator — A multi-agent orchestration harness implementation."""

__version__ = "0.1.0"
__harness_version__ = "1.0.0"

from orchestrator.models.task import Task, TaskStatus
from orchestrator.models.handoff import Handoff, HandoffStatus
from orchestrator.models.agent import Agent, AgentRole

__all__ = ["Task", "TaskStatus", "Handoff", "HandoffStatus", "Agent", "AgentRole"]
''',
    "orchestrator/models/__init__.py": '''\
"""Core data models for the orchestration harness."""

from orchestrator.models.task import Task, TaskStatus, TaskPriority
from orchestrator.models.handoff import Handoff, HandoffStatus
from orchestrator.models.agent import Agent, AgentRole, AgentState
from orchestrator.models.event import Event, EventType
from orchestrator.models.workspace import Workspace, WorkspaceState
from orchestrator.models.error_budget import ErrorBudget

__all__ = [
    "Task", "TaskStatus", "TaskPriority",
    "Handoff", "HandoffStatus",
    "Agent", "AgentRole", "AgentState",
    "Event", "EventType",
    "Workspace", "WorkspaceState",
    "ErrorBudget",
]
''',
    "orchestrator/models/task.py": '''\
"""Task model for the task board."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class TaskStatus(Enum):
    PENDING = auto()
    CLAIMED = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    FAILED = auto()
    BLOCKED = auto()
    ABANDONED = auto()


class TaskPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    TRIVIAL = 4


@dataclass
class Task:
    """A unit of work in the orchestration system."""
    task_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    
    # Ownership
    owner_id: str | None = None
    parent_task_id: str | None = None
    
    # Dependencies
    depends_on: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    
    # Execution
    instructions: str = ""
    expected_files: list[str] = field(default_factory=list)
    test_command: str | None = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # Results
    result_summary: str = ""
    handoff_id: str | None = None
    error_message: str | None = None
    
    # Metrics
    attempts: int = 0
    tokens_used: int = 0
    wall_time_seconds: float = 0.0
    
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def is_ready(self) -> bool:
        """Check if task can be started (all deps satisfied)."""
        return self.status == TaskStatus.PENDING and not self.depends_on
    
    def is_terminal(self) -> bool:
        """Check if task is in a terminal state."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ABANDONED)
    
    def claim(self, agent_id: str) -> None:
        """Claim this task for an agent."""
        self.owner_id = agent_id
        self.status = TaskStatus.CLAIMED
        self.claimed_at = datetime.now()
    
    def start(self) -> None:
        """Mark task as started."""
        self.status = TaskStatus.IN_PROGRESS
        self.started_at = datetime.now()
        self.attempts += 1
    
    def complete(self, summary: str, handoff_id: str) -> None:
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.result_summary = summary
        self.handoff_id = handoff_id
        self.completed_at = datetime.now()
    
    def fail(self, error: str) -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.now()
''',
    "orchestrator/models/handoff.py": '''\
"""Handoff model for structured agent communication."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class HandoffStatus(Enum):
    SUCCESS = auto()
    PARTIAL_FAILURE = auto()
    FAILED = auto()
    BLOCKED = auto()


@dataclass
class FileDiff:
    """Represents a file modification."""
    filepath: str
    before: str = ""
    after: str = ""
    is_new: bool = False
    is_deleted: bool = False


@dataclass
class HandoffMetrics:
    """Execution metrics for a handoff."""
    wall_time_seconds: float = 0.0
    tokens_used: int = 0
    tool_calls: int = 0
    files_modified: int = 0
    files_created: int = 0
    attempts: int = 0


@dataclass
class Handoff:
    """Structured communication from worker to parent."""
    handoff_id: str
    agent_id: str
    task_id: str
    parent_agent_id: str
    
    status: HandoffStatus = HandoffStatus.SUCCESS
    
    # Content
    narrative: str = ""  # What was done, concerns, suggestions
    summary: str = ""    # Compressed one-line summary
    
    # Changes
    diffs: list[FileDiff] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    
    # Metrics
    metrics: HandoffMetrics = field(default_factory=HandoffMetrics)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    submitted_at: datetime | None = None
    
    # Context
    scratchpad_final: str = ""
    concerns: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def submit(self) -> None:
        """Mark handoff as submitted."""
        self.submitted_at = datetime.now()
    
    def has_changes(self) -> bool:
        """Check if handoff contains any file changes."""
        return len(self.diffs) > 0 or len(self.artifacts) > 0
    
    def get_modified_files(self) -> list[str]:
        """Get list of modified file paths."""
        return [d.filepath for d in self.diffs]
''',
    "orchestrator/models/agent.py": '''\
"""Agent model for planner and worker agents."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class AgentRole(Enum):
    ROOT_PLANNER = auto()
    SUB_PLANNER = auto()
    WORKER = auto()
    WATCHDOG = auto()


class AgentState(Enum):
    INIT = auto()
    IDLE = auto()
    PLANNING = auto()
    EXECUTING = auto()
    WAITING = auto()
    RECONCILING = auto()
    SHUTDOWN = auto()
    ZOMBIE = auto()


@dataclass
class Agent:
    """An agent in the orchestration system."""
    agent_id: str
    role: AgentRole
    parent_id: str | None = None
    
    # State
    state: AgentState = AgentState.INIT
    current_task_id: str | None = None
    
    # Hierarchy
    child_ids: list[str] = field(default_factory=list)
    
    # Workspace
    workspace_path: str | None = None
    base_snapshot: dict[str, str] = field(default_factory=dict)  # filepath -> hash
    
    # Handoffs
    pending_handoffs: list[str] = field(default_factory=list)
    received_handoffs: list[str] = field(default_factory=list)
    
    # Resource tracking
    tokens_used: int = 0
    wall_time_seconds: float = 0.0
    tasks_completed: int = 0
    tasks_failed: int = 0
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: datetime | None = None
    shutdown_at: datetime | None = None
    
    # Configuration
    max_turns: int = 50
    max_wall_time: float = 600.0
    
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def is_alive(self) -> bool:
        """Check if agent is still alive (has recent heartbeat)."""
        if self.state == AgentState.SHUTDOWN:
            return False
        if self.last_heartbeat is None:
            return True
        elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
        return elapsed < 60  # 60 second timeout
    
    def is_planner(self) -> bool:
        """Check if agent has planning role."""
        return self.role in (AgentRole.ROOT_PLANNER, AgentRole.SUB_PLANNER)
    
    def is_worker(self) -> bool:
        """Check if agent has worker role."""
        return self.role == AgentRole.WORKER
    
    def heartbeat(self) -> None:
        """Update last heartbeat timestamp."""
        self.last_heartbeat = datetime.now()
    
    def transition(self, new_state: AgentState) -> None:
        """Transition to a new state."""
        self.state = new_state
        self.heartbeat()
''',
    "orchestrator/models/event.py": '''\
"""Event model for the event bus."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class EventType(Enum):
    # Agent lifecycle
    AGENT_SPAWNED = auto()
    AGENT_SHUTDOWN = auto()
    AGENT_ZOMBIE_DETECTED = auto()
    
    # Task lifecycle
    TASK_CREATED = auto()
    TASK_CLAIMED = auto()
    TASK_STARTED = auto()
    TASK_COMPLETED = auto()
    TASK_FAILED = auto()
    
    # Handoff
    HANDOFF_SUBMITTED = auto()
    HANDOFF_ACCEPTED = auto()
    HANDOFF_REJECTED = auto()
    
    # Merge
    MERGE_CLEAN = auto()
    MERGE_CONFLICT = auto()
    MERGE_FAILED = auto()
    
    # Error budget
    ERROR_BUDGET_DEPLETED = auto()
    ERROR_THRESHOLD_WARNING = auto()
    
    # Watchdog
    WATCHDOG_ALERT = auto()
    WATCHDOG_KILL = auto()
    
    # System
    RECONCILIATION_STARTED = auto()
    RECONCILIATION_COMPLETED = auto()
    CHECKPOINT_CREATED = auto()


@dataclass
class Event:
    """An event in the orchestration system."""
    event_id: str
    event_type: EventType
    
    # Source
    agent_id: str | None = None
    task_id: str | None = None
    
    # Content
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    
    # Timestamp
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Routing
    target_agent_id: str | None = None  # None = broadcast
    
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def create(
        cls,
        event_type: EventType,
        agent_id: str | None = None,
        task_id: str | None = None,
        message: str = "",
        data: dict | None = None,
    ) -> "Event":
        """Factory method to create an event with auto-generated ID."""
        import uuid
        return cls(
            event_id=str(uuid.uuid4())[:8],
            event_type=event_type,
            agent_id=agent_id,
            task_id=task_id,
            message=message,
            data=data or {},
        )
''',
    "orchestrator/models/workspace.py": '''\
"""Workspace model for per-agent isolation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any


class WorkspaceState(Enum):
    UNINITIALIZED = auto()
    COPYING = auto()
    READY = auto()
    DIRTY = auto()
    MERGING = auto()
    CONFLICT = auto()
    CLEANED = auto()


@dataclass
class Workspace:
    """Isolated workspace for an agent."""
    workspace_id: str
    agent_id: str
    base_path: str  # The canonical repo path
    work_path: str  # The isolated copy path
    
    state: WorkspaceState = WorkspaceState.UNINITIALIZED
    
    # Snapshots for 3-way merge
    base_snapshot: dict[str, str] = field(default_factory=dict)
    current_snapshot: dict[str, str] = field(default_factory=dict)
    
    # Tracking
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    last_sync: datetime | None = None
    
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def get_path(self) -> Path:
        """Get Path object for work directory."""
        return Path(self.work_path)
    
    def mark_dirty(self) -> None:
        """Mark workspace as having unmerged changes."""
        self.state = WorkspaceState.DIRTY
    
    def mark_ready(self) -> None:
        """Mark workspace as ready for work."""
        self.state = WorkspaceState.READY
    
    def compute_diff(self) -> dict[str, tuple[str, str]]:
        """Compute diff between base and current snapshot."""
        diff = {}
        all_files = set(self.base_snapshot.keys()) | set(self.current_snapshot.keys())
        for f in all_files:
            base_hash = self.base_snapshot.get(f, "")
            curr_hash = self.current_snapshot.get(f, "")
            if base_hash != curr_hash:
                diff[f] = (base_hash, curr_hash)
        return diff
''',
    "orchestrator/models/error_budget.py": '''\
"""Error budget model for graceful degradation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ErrorBudget:
    """Tracks error budget for an agent or task."""
    budget_id: str
    owner_id: str  # agent or task that owns this budget
    
    # Budget limits
    max_errors: int = 5
    max_retries: int = 3
    max_tokens: int = 100000
    max_wall_time: float = 600.0
    
    # Current usage
    error_count: int = 0
    retry_count: int = 0
    tokens_used: int = 0
    wall_time_seconds: float = 0.0
    
    # State
    is_depleted: bool = False
    depleted_at: datetime | None = None
    depleted_reason: str | None = None
    
    # Recovery
    can_recover: bool = True
    recovery_attempts: int = 0
    
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def record_error(self, error_type: str = "generic") -> bool:
        """Record an error and check if budget is depleted."""
        self.error_count += 1
        if self.error_count >= self.max_errors:
            self.deplete(f"error_count exceeded: {self.error_count}")
            return False
        return True
    
    def record_retry(self) -> bool:
        """Record a retry attempt."""
        self.retry_count += 1
        if self.retry_count > self.max_retries:
            self.deplete(f"retry_count exceeded: {self.retry_count}")
            return False
        return True
    
    def record_tokens(self, tokens: int) -> bool:
        """Record token usage."""
        self.tokens_used += tokens
        if self.tokens_used > self.max_tokens:
            self.deplete(f"token budget exceeded: {self.tokens_used}")
            return False
        return True
    
    def record_time(self, seconds: float) -> bool:
        """Record wall time usage."""
        self.wall_time_seconds += seconds
        if self.wall_time_seconds > self.max_wall_time:
            self.deplete(f"time budget exceeded: {self.wall_time_seconds}")
            return False
        return True
    
    def deplete(self, reason: str) -> None:
        """Mark budget as depleted."""
        self.is_depleted = True
        self.depleted_at = datetime.now()
        self.depleted_reason = reason
    
    def remaining(self) -> dict[str, float]:
        """Get remaining budget."""
        return {
            "errors": max(0, self.max_errors - self.error_count),
            "retries": max(0, self.max_retries - self.retry_count),
            "tokens": max(0, self.max_tokens - self.tokens_used),
            "time": max(0, self.max_wall_time - self.wall_time_seconds),
        }
''',
    "orchestrator/agents/__init__.py": '''\
"""Agent implementations for the orchestration harness."""

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.agents.planner_agent import PlannerAgent
from orchestrator.agents.worker_agent import WorkerAgent
from orchestrator.agents.watchdog_agent import WatchdogAgent

__all__ = ["BaseAgent", "PlannerAgent", "WorkerAgent", "WatchdogAgent"]
''',
    "orchestrator/agents/base_agent.py": '''\
"""Base agent class with common functionality."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from orchestrator.models.agent import Agent, AgentRole, AgentState
from orchestrator.models.event import Event, EventType


@dataclass
class BaseAgent(ABC):
    """Abstract base class for all agents."""
    
    agent: Agent
    event_bus: "EventBus" = field(repr=False)
    task_board: "TaskBoard" = field(repr=False)
    workspace_manager: "WorkspaceManager" = field(repr=False)
    
    # Scratchpad for context management
    scratchpad: str = ""
    max_scratchpad_lines: int = 100
    
    def __post_init__(self):
        self.agent.heartbeat()
    
    @abstractmethod
    async def run(self) -> None:
        """Main agent loop."""
        pass
    
    def emit_event(self, event_type: EventType, message: str = "", data: dict | None = None) -> None:
        """Emit an event to the event bus."""
        event = Event.create(
            event_type=event_type,
            agent_id=self.agent.agent_id,
            message=message,
            data=data,
        )
        self.event_bus.publish(event)
    
    def rewrite_scratchpad(self, new_content: str) -> None:
        """Rewrite scratchpad (never append)."""
        self.scratchpad = new_content
    
    def get_context_summary(self) -> str:
        """Get compressed context summary."""
        lines = self.scratchpad.splitlines()
        if len(lines) > self.max_scratchpad_lines:
            # Keep first 20 and last 80 lines
            return "\\n".join(lines[:20] + ["... (compressed) ..."] + lines[-80:])
        return self.scratchpad
    
    def transition(self, new_state: AgentState) -> None:
        """Transition to new state and emit event."""
        old_state = self.agent.state
        self.agent.transition(new_state)
        self.emit_event(
            EventType.AGENT_STATE_CHANGED,
            f"State: {old_state.name} -> {new_state.name}",
            {"old_state": old_state.name, "new_state": new_state.name},
        )
    
    def should_compress_context(self, token_estimate: int, max_tokens: int) -> bool:
        """Check if context compression is needed."""
        return token_estimate > max_tokens * 0.8
''',
    "orchestrator/agents/planner_agent.py": '''\
"""Planner agent implementation."""

from dataclasses import dataclass
from typing import Any

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.models.agent import AgentRole, AgentState
from orchestrator.models.task import Task, TaskStatus, TaskPriority
from orchestrator.models.event import EventType


@dataclass
class PlannerAgent(BaseAgent):
    """Planner agent that decomposes problems and delegates work."""
    
    def __post_init__(self):
        super().__post_init__()
        if self.agent.role not in (AgentRole.ROOT_PLANNER, AgentRole.SUB_PLANNER):
            raise ValueError("PlannerAgent must have planner role")
    
    async def run(self) -> None:
        """Main planner loop: DECOMPOSE -> ORCHESTRATE -> RECONCILE."""
        self.agent.transition(AgentState.PLANNING)
        
        while self.agent.state != AgentState.SHUTDOWN:
            # Check for handoffs from children
            await self._process_child_handoffs()
            
            # Check for new tasks to decompose
            await self._decompose_pending_tasks()
            
            # Check if all work is complete
            if self._is_work_complete():
                await self._reconcile()
                break
            
            # Brief pause before next cycle
            await asyncio.sleep(0.1)
        
        self.agent.transition(AgentState.SHUTDOWN)
    
    async def _process_child_handoffs(self) -> None:
        """Process handoffs from child agents."""
        for handoff_id in self.agent.received_handoffs:
            # Process handoff and update task board
            pass
        self.agent.received_handoffs.clear()
    
    async def _decompose_pending_tasks(self) -> None:
        """Decompose tasks and spawn child agents."""
        # Find tasks assigned to this planner
        pass
    
    def _is_work_complete(self) -> bool:
        """Check if all assigned work is complete."""
        return len(self.agent.child_ids) == 0
    
    async def _reconcile(self) -> None:
        """Final reconciliation pass before completion."""
        self.agent.transition(AgentState.RECONCILING)
        self.emit_event(EventType.RECONCILIATION_STARTED, "Beginning reconciliation pass")
        
        # Verify all tasks complete, run fixer loop if needed
        
        self.emit_event(EventType.RECONCILIATION_COMPLETED, "Reconciliation complete")
    
    def spawn_worker(self, task: Task) -> str:
        """Spawn a worker agent for a task."""
        # Returns worker_id
        raise NotImplementedError
    
    def spawn_sub_planner(self, scope: str) -> str:
        """Spawn a sub-planner for recursive delegation."""
        # Returns planner_id
        raise NotImplementedError
''',
    "orchestrator/agents/worker_agent.py": '''\
"""Worker agent implementation."""

from dataclasses import dataclass
from typing import Any

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.models.agent import AgentRole, AgentState
from orchestrator.models.task import Task, TaskStatus
from orchestrator.models.handoff import Handoff, HandoffStatus
from orchestrator.models.event import EventType
from orchestrator.models.error_budget import ErrorBudget


@dataclass
class WorkerAgent(BaseAgent):
    """Worker agent that executes tasks and submits handoffs."""
    
    current_task: Task | None = None
    error_budget: ErrorBudget | None = None
    
    def __post_init__(self):
        super().__post_init__()
        if self.agent.role != AgentRole.WORKER:
            raise ValueError("WorkerAgent must have worker role")
    
    async def run(self) -> None:
        """Main worker loop: claim task -> execute -> submit handoff."""
        self.agent.transition(AgentState.IDLE)
        
        # Claim a task from the task board
        task = await self._claim_task()
        if not task:
            return
        
        self.current_task = task
        self.agent.current_task_id = task.task_id
        
        # Initialize error budget
        self.error_budget = ErrorBudget(
            budget_id=f"eb-{self.agent.agent_id}",
            owner_id=self.agent.agent_id,
            max_errors=3,
            max_retries=2,
        )
        
        # Execute the task
        self.agent.transition(AgentState.EXECUTING)
        try:
            await self._execute_task()
        except Exception as e:
            self._handle_execution_error(e)
        
        # Submit handoff
        await self._submit_handoff()
        
        self.agent.transition(AgentState.SHUTDOWN)
    
    async def _claim_task(self) -> Task | None:
        """Claim a ready task from the task board."""
        raise NotImplementedError
    
    async def _execute_task(self) -> None:
        """Execute the assigned task."""
        # Implementation: use tools to complete task
        pass
    
    def _handle_execution_error(self, error: Exception) -> None:
        """Handle an error during execution."""
        if self.error_budget:
            can_continue = self.error_budget.record_error(str(error))
            if not can_continue:
                self.current_task.fail(str(error))
    
    async def _submit_handoff(self) -> None:
        """Create and submit handoff to parent."""
        handoff = Handoff(
            handoff_id=f"ho-{self.agent.agent_id}",
            agent_id=self.agent.agent_id,
            task_id=self.current_task.task_id if self.current_task else "",
            parent_agent_id=self.agent.parent_id or "",
            status=HandoffStatus.SUCCESS,
        )
        # Publish handoff
        self.emit_event(EventType.HANDOFF_SUBMITTED, f"Handoff submitted for {handoff.task_id}")
    
    def use_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a tool and record usage."""
        raise NotImplementedError
''',
    "orchestrator/agents/watchdog_agent.py": '''\
"""Watchdog agent for failure detection."""

from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.models.agent import AgentRole, AgentState
from orchestrator.models.event import EventType


@dataclass
class WatchdogAgent(BaseAgent):
    """Watchdog that monitors for zombie, tunnel-vision, and burn patterns."""
    
    check_interval: float = 5.0  # seconds
    zombie_threshold: float = 60.0  # seconds without heartbeat
    tunnel_vision_threshold: int = 50  # edits to same file
    burn_threshold: int = 50000  # tokens with no progress
    
    # Activity tracking
    agent_activity: dict[str, dict] = field(default_factory=dict)
    
    def __post_init__(self):
        super().__post_init__()
        if self.agent.role != AgentRole.WATCHDOG:
            raise ValueError("WatchdogAgent must have watchdog role")
    
    async def run(self) -> None:
        """Watchdog loop: periodically check all agents."""
        self.agent.transition(AgentState.EXECUTING)
        
        while self.agent.state != AgentState.SHUTDOWN:
            await self._check_all_agents()
            await asyncio.sleep(self.check_interval)
    
    async def _check_all_agents(self) -> None:
        """Check all agents for failure patterns."""
        all_agents = self._get_all_agents()
        
        for agent in all_agents:
            if agent.agent_id == self.agent.agent_id:
                continue
            
            # Check for zombie
            if self._is_zombie(agent):
                self._handle_zombie(agent)
            
            # Check for tunnel vision
            if self._has_tunnel_vision(agent):
                self._handle_tunnel_vision(agent)
            
            # Check for token burn
            if self._is_token_burn(agent):
                self._handle_token_burn(agent)
    
    def _get_all_agents(self) -> list:
        """Get list of all agents to monitor."""
        raise NotImplementedError
    
    def _is_zombie(self, agent) -> bool:
        """Check if agent is a zombie (no heartbeat)."""
        return not agent.is_alive()
    
    def _handle_zombie(self, agent) -> None:
        """Handle zombie detection."""
        self.emit_event(
            EventType.WATCHDOG_ALERT,
            f"Zombie detected: {agent.agent_id}",
            {"agent_id": agent.agent_id, "pattern": "zombie"},
        )
    
    def _has_tunnel_vision(self, agent) -> bool:
        """Check if agent has tunnel vision."""
        activity = self.agent_activity.get(agent.agent_id, {})
        file_edits = activity.get("file_edits", {})
        return any(count > self.tunnel_vision_threshold for count in file_edits.values())
    
    def _handle_tunnel_vision(self, agent) -> None:
        """Handle tunnel vision detection."""
        self.emit_event(
            EventType.WATCHDOG_ALERT,
            f"Tunnel vision detected: {agent.agent_id}",
            {"agent_id": agent.agent_id, "pattern": "tunnel_vision"},
        )
    
    def _is_token_burn(self, agent) -> bool:
        """Check if agent is burning tokens without progress."""
        activity = self.agent_activity.get(agent.agent_id, {})
        tokens_since_progress = activity.get("tokens_since_progress", 0)
        return tokens_since_progress > self.burn_threshold
    
    def _handle_token_burn(self, agent) -> None:
        """Handle token burn detection."""
        self.emit_event(
            EventType.WATCHDOG_ALERT,
            f"Token burn detected: {agent.agent_id}",
            {"agent_id": agent.agent_id, "pattern": "token_burn"},
        )
''',
    "orchestrator/tools/__init__.py": '''\
"""Tool implementations for agents."""

from orchestrator.tools.base_tool import BaseTool
from orchestrator.tools.bash_tool import BashTool
from orchestrator.tools.file_tool import FileTool
from orchestrator.tools.git_tool import GitTool

__all__ = ["BaseTool", "BashTool", "FileTool", "GitTool"]
''',
    "orchestrator/tools/base_tool.py": '''\
"""Base tool class."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    output: str = ""
    error: str = ""
    data: dict[str, Any] = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}


class BaseTool(ABC):
    """Abstract base class for tools."""
    
    name: str = ""
    description: str = ""
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool."""
        pass
    
    def get_schema(self) -> dict:
        """Get JSON schema for tool parameters."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {},
        }
''',
    "orchestrator/tools/bash_tool.py": '''\
"""Bash command execution tool."""

import asyncio
from dataclasses import dataclass

from orchestrator.tools.base_tool import BaseTool, ToolResult


@dataclass
class BashTool(BaseTool):
    """Execute bash commands."""
    
    name: str = "bash"
    description: str = "Execute a bash command in the workspace"
    timeout: int = 60
    
    async def execute(self, command: str, timeout: int | None = None) -> ToolResult:
        """Execute a bash command."""
        timeout = timeout or self.timeout
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            return ToolResult(
                success=proc.returncode == 0,
                output=stdout.decode(),
                error=stderr.decode() if stderr else "",
                data={"returncode": proc.returncode},
            )
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout}s",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
            )
''',
    "orchestrator/tools/file_tool.py": '''\
"""File operation tools."""

from dataclasses import dataclass
from pathlib import Path

from orchestrator.tools.base_tool import BaseTool, ToolResult


@dataclass
class FileTool(BaseTool):
    """Read and write files."""
    
    name: str = "file"
    description: str = "Read, write, and edit files"
    workspace_path: str = "."
    
    async def execute(self, operation: str, path: str, content: str = "") -> ToolResult:
        """Execute file operation."""
        full_path = Path(self.workspace_path) / path
        
        try:
            if operation == "read":
                if not full_path.exists():
                    return ToolResult(success=False, error=f"File not found: {path}")
                return ToolResult(
                    success=True,
                    output=full_path.read_text(),
                )
            
            elif operation == "write":
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
                return ToolResult(success=True, output=f"Wrote {len(content)} chars to {path}")
            
            elif operation == "exists":
                return ToolResult(
                    success=full_path.exists(),
                    output=str(full_path.exists()),
                )
            
            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}")
        
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
    def read(self, path: str) -> ToolResult:
        """Read file contents."""
        full_path = Path(self.workspace_path) / path
        try:
            return ToolResult(success=True, output=full_path.read_text())
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
    def write(self, path: str, content: str) -> ToolResult:
        """Write file contents."""
        full_path = Path(self.workspace_path) / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        return ToolResult(success=True, output=f"Wrote {len(content)} chars")
    
    def edit(self, path: str, old_text: str, new_text: str) -> ToolResult:
        """Edit file by replacing text."""
        full_path = Path(self.workspace_path) / path
        try:
            content = full_path.read_text()
            if old_text not in content:
                return ToolResult(success=False, error="Old text not found")
            content = content.replace(old_text, new_text)
            full_path.write_text(content)
            return ToolResult(success=True, output=f"Edited {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
''',
    "orchestrator/git/__init__.py": '''\
"""Git operations for workspace isolation and merge."""

from orchestrator.git.workspace_manager import WorkspaceManager
from orchestrator.git.merge_engine import MergeEngine
from orchestrator.git.diff_engine import DiffEngine

__all__ = ["WorkspaceManager", "MergeEngine", "DiffEngine"]
''',
    "orchestrator/git/workspace_manager.py": '''\
"""Manages per-agent workspace copies."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.models.workspace import Workspace, WorkspaceState


@dataclass
class WorkspaceManager:
    """Creates and manages isolated workspaces for agents."""
    
    base_repo_path: str
    workspaces: dict[str, Workspace] = field(default_factory=dict)
    
    def create_workspace(self, agent_id: str) -> Workspace:
        """Create an isolated workspace for an agent."""
        work_path = f"/tmp/workspace-{agent_id}"
        
        # Clean up if exists
        if Path(work_path).exists():
            shutil.rmtree(work_path)
        
        # Copy base repo
        shutil.copytree(self.base_repo_path, work_path)
        
        workspace = Workspace(
            workspace_id=f"ws-{agent_id}",
            agent_id=agent_id,
            base_path=self.base_repo_path,
            work_path=work_path,
            state=WorkspaceState.COPYING,
        )
        
        # Compute base snapshot
        workspace.base_snapshot = self._compute_snapshot(work_path)
        workspace.mark_ready()
        
        self.workspaces[agent_id] = workspace
        return workspace
    
    def get_workspace(self, agent_id: str) -> Workspace | None:
        """Get workspace for an agent."""
        return self.workspaces.get(agent_id)
    
    def update_snapshot(self, agent_id: str) -> None:
        """Update current snapshot for workspace."""
        workspace = self.workspaces.get(agent_id)
        if workspace:
            workspace.current_snapshot = self._compute_snapshot(workspace.work_path)
    
    def cleanup_workspace(self, agent_id: str) -> None:
        """Clean up workspace for an agent."""
        workspace = self.workspaces.pop(agent_id, None)
        if workspace and Path(workspace.work_path).exists():
            shutil.rmtree(workspace.work_path)
    
    def _compute_snapshot(self, path: str) -> dict[str, str]:
        """Compute hash snapshot of directory."""
        import hashlib
        snapshot = {}
        for f in Path(path).rglob("*"):
            if f.is_file():
                rel_path = str(f.relative_to(path))
                content = f.read_bytes()
                snapshot[rel_path] = hashlib.md5(content).hexdigest()
        return snapshot
''',
    "orchestrator/git/merge_engine.py": '''\
"""3-way merge engine with conflict detection."""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

from orchestrator.models.workspace import Workspace


class MergeResult(Enum):
    CLEAN = auto()
    CONFLICT = auto()
    ERROR = auto()


@dataclass
class MergeConflict:
    """Represents a merge conflict."""
    filepath: str
    base_content: str = ""
    our_content: str = ""
    their_content: str = ""


@dataclass
class MergeEngine:
    """Performs 3-way merge between workspace and base."""
    
    conflicts: list[MergeConflict] = field(default_factory=list)
    merged_files: list[str] = field(default_factory=list)
    
    def merge_workspace(
        self,
        workspace: Workspace,
        target_path: str,
    ) -> MergeResult:
        """Merge workspace changes into target path."""
        self.conflicts.clear()
        self.merged_files.clear()
        
        diff = workspace.compute_diff()
        
        for filepath, (base_hash, curr_hash) in diff.items():
            target_file = Path(target_path) / filepath
            work_file = Path(workspace.work_path) / filepath
            
            if not target_file.exists():
                # New file
                if base_hash == "":
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_text(work_file.read_text())
                    self.merged_files.append(filepath)
                else:
                    # Conflict: file exists in workspace but deleted elsewhere
                    self._add_conflict(filepath, "", work_file.read_text(), "")
            else:
                # Modified file - check for conflict
                target_hash = self._hash_file(target_file)
                if target_hash == base_hash:
                    # No conflict, apply change
                    target_file.write_text(work_file.read_text())
                    self.merged_files.append(filepath)
                else:
                    # Conflict: both modified
                    self._add_conflict(
                        filepath,
                        "",  # base (would need to be retrieved)
                        work_file.read_text(),
                        target_file.read_text(),
                    )
        
        if self.conflicts:
            return MergeResult.CONFLICT
        return MergeResult.CLEAN
    
    def _hash_file(self, path: Path) -> str:
        """Compute MD5 hash of file."""
        import hashlib
        return hashlib.md5(path.read_bytes()).hexdigest()
    
    def _add_conflict(self, filepath: str, base: str, ours: str, theirs: str) -> None:
        """Record a merge conflict."""
        self.conflicts.append(MergeConflict(
            filepath=filepath,
            base_content=base,
            our_content=ours,
            their_content=theirs,
        ))
    
    def get_conflict_markers(self, conflict: MergeConflict) -> str:
        """Generate conflict marker text."""
        return f"""
<<<<<<< OURS
{conflict.our_content}
=======
{conflict.their_content}
>>>>>>> THEIRS
"""
''',
    "orchestrator/git/diff_engine.py": '''\
"""Diff computation engine."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DiffHunk:
    """A hunk of a diff."""
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FileDiff:
    """Diff for a single file."""
    old_path: str
    new_path: str
    hunks: list[DiffHunk] = field(default_factory=list)
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False


@dataclass
class DiffEngine:
    """Computes unified diffs."""
    
    def compute_diff(self, old_content: str, new_content: str) -> list[DiffHunk]:
        """Compute diff between two strings."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        # Simple line-by-line diff
        hunks = []
        i = j = 0
        
        while i < len(old_lines) or j < len(new_lines):
            if i < len(old_lines) and j < len(new_lines) and old_lines[i] == new_lines[j]:
                i += 1
                j += 1
            else:
                # Find change extent
                old_end = i
                new_end = j
                
                while old_end < len(old_lines) and (new_end >= len(new_lines) or old_lines[old_end] != new_lines[new_end]):
                    old_end += 1
                while new_end < len(new_lines) and (old_end >= len(old_lines) or old_lines[old_end] != new_lines[new_end]):
                    new_end += 1
                
                hunk_lines = []
                for k in range(i, old_end):
                    hunk_lines.append("-" + old_lines[k].rstrip("\\n"))
                for k in range(j, new_end):
                    hunk_lines.append("+" + new_lines[k].rstrip("\\n"))
                
                hunks.append(DiffHunk(
                    old_start=i + 1,
                    old_lines=old_end - i,
                    new_start=j + 1,
                    new_lines=new_end - j,
                    lines=hunk_lines,
                ))
                
                i = old_end
                j = new_end
        
        return hunks
    
    def compute_file_diff(
        self,
        old_path: str | None,
        new_path: str | None,
        old_content: str,
        new_content: str,
    ) -> FileDiff:
        """Compute FileDiff between two files."""
        return FileDiff(
            old_path=old_path or "/dev/null",
            new_path=new_path or "/dev/null",
            hunks=self.compute_diff(old_content, new_content),
            is_new=old_path is None,
            is_deleted=new_path is None,
        )
''',
    "orchestrator/events/__init__.py": '''\
"""Event bus for system observability."""

from orchestrator.events.event_bus import EventBus
from orchestrator.events.handlers import ConsoleHandler, FileHandler

__all__ = ["EventBus", "ConsoleHandler", "FileHandler"]
''',
    "orchestrator/events/event_bus.py": '''\
"""Event bus for publish/subscribe messaging."""

import asyncio
from dataclasses import dataclass, field
from typing import Callable
from collections import defaultdict

from orchestrator.models.event import Event, EventType


@dataclass
class EventBus:
    """Central event bus for system-wide messaging."""
    
    subscribers: dict[EventType, list[Callable]] = field(
        default_factory=lambda: defaultdict(list)
    )
    all_subscribers: list[Callable] = field(default_factory=list)
    event_history: list[Event] = field(default_factory=list)
    max_history: int = 1000
    
    def subscribe(self, callback: Callable, event_type: EventType | None = None) -> None:
        """Subscribe to events."""
        if event_type:
            self.subscribers[event_type].append(callback)
        else:
            self.all_subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable, event_type: EventType | None = None) -> None:
        """Unsubscribe from events."""
        if event_type:
            self.subscribers[event_type] = [
                cb for cb in self.subscribers[event_type] if cb != callback
            ]
        else:
            self.all_subscribers = [cb for cb in self.all_subscribers if cb != callback]
    
    def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        # Store in history
        self.event_history.append(event)
        if len(self.event_history) > self.max_history:
            self.event_history.pop(0)
        
        # Notify type-specific subscribers
        for callback in self.subscribers.get(event.event_type, []):
            try:
                callback(event)
            except Exception:
                pass
        
        # Notify all-subscriber callbacks
        for callback in self.all_subscribers:
            try:
                callback(event)
            except Exception:
                pass
    
    def get_history(self, event_type: EventType | None = None) -> list[Event]:
        """Get event history, optionally filtered by type."""
        if event_type:
            return [e for e in self.event_history if e.event_type == event_type]
        return list(self.event_history)
''',
    "orchestrator/events/handlers.py": '''\
"""Event handlers for logging and monitoring."""

from dataclasses import dataclass
from pathlib import Path

from orchestrator.models.event import Event


@dataclass
class ConsoleHandler:
    """Prints events to console."""
    
    def __call__(self, event: Event) -> None:
        """Handle an event."""
        prefix = f"[{event.event_type.name}]"
        agent = f" ({event.agent_id})" if event.agent_id else ""
        print(f"{prefix}{agent}: {event.message}")


@dataclass
class FileHandler:
    """Writes events to a log file."""
    
    log_path: str
    
    def __call__(self, event: Event) -> None:
        """Handle an event."""
        import json
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            record = {
                "event_id": event.event_id,
                "type": event.event_type.name,
                "agent_id": event.agent_id,
                "message": event.message,
                "timestamp": event.timestamp.isoformat(),
            }
            f.write(json.dumps(record) + "\\n")
''',
    "tests/__init__.py": "",
    "tests/conftest.py": """\
import pytest
from orchestrator.models.task import Task, TaskStatus, TaskPriority
from orchestrator.models.handoff import Handoff, HandoffStatus, FileDiff
from orchestrator.models.agent import Agent, AgentRole, AgentState
from orchestrator.models.workspace import Workspace, WorkspaceState
from orchestrator.models.error_budget import ErrorBudget


@pytest.fixture
def sample_task():
    return Task(
        task_id="task-1",
        title="Test Task",
        description="A test task",
        status=TaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
    )


@pytest.fixture
def sample_handoff():
    return Handoff(
        handoff_id="ho-1",
        agent_id="agent-1",
        task_id="task-1",
        parent_agent_id="planner-1",
        status=HandoffStatus.SUCCESS,
        narrative="Task completed successfully",
    )


@pytest.fixture
def sample_agent():
    return Agent(
        agent_id="agent-1",
        role=AgentRole.WORKER,
        state=AgentState.IDLE,
    )


@pytest.fixture
def sample_workspace():
    return Workspace(
        workspace_id="ws-1",
        agent_id="agent-1",
        base_path="/tmp/base",
        work_path="/tmp/work",
        state=WorkspaceState.READY,
    )


@pytest.fixture
def sample_error_budget():
    return ErrorBudget(
        budget_id="eb-1",
        owner_id="agent-1",
        max_errors=5,
        max_retries=3,
    )
""",
    "tests/test_task.py": """\
from orchestrator.models.task import Task, TaskStatus, TaskPriority


def test_task_creation():
    task = Task(task_id="t1", title="Test", description="Desc")
    assert task.status == TaskStatus.PENDING
    assert task.priority == TaskPriority.NORMAL


def test_task_is_ready():
    task = Task(task_id="t1", title="Test")
    assert task.is_ready()
    task.depends_on = ["other"]
    assert not task.is_ready()


def test_task_terminal_states():
    task = Task(task_id="t1", title="Test")
    assert not task.is_terminal()
    task.status = TaskStatus.COMPLETED
    assert task.is_terminal()


def test_task_claim():
    task = Task(task_id="t1", title="Test")
    task.claim("agent-1")
    assert task.owner_id == "agent-1"
    assert task.status == TaskStatus.CLAIMED


def test_task_complete():
    task = Task(task_id="t1", title="Test")
    task.complete("Done", "ho-1")
    assert task.status == TaskStatus.COMPLETED
    assert task.result_summary == "Done"
""",
    "tests/test_handoff.py": """\
from orchestrator.models.handoff import Handoff, HandoffStatus, FileDiff


def test_handoff_creation():
    ho = Handoff(
        handoff_id="ho-1",
        agent_id="agent-1",
        task_id="task-1",
        parent_agent_id="planner-1",
    )
    assert ho.status == HandoffStatus.SUCCESS
    assert not ho.has_changes()


def test_handoff_has_changes():
    ho = Handoff(
        handoff_id="ho-1",
        agent_id="agent-1",
        task_id="task-1",
        parent_agent_id="planner-1",
    )
    ho.diffs.append(FileDiff(filepath="test.py", before="", after="code"))
    assert ho.has_changes()


def test_handoff_get_modified_files():
    ho = Handoff(
        handoff_id="ho-1",
        agent_id="agent-1",
        task_id="task-1",
        parent_agent_id="planner-1",
    )
    ho.diffs.append(FileDiff(filepath="a.py"))
    ho.diffs.append(FileDiff(filepath="b.py"))
    assert ho.get_modified_files() == ["a.py", "b.py"]
""",
    "tests/test_agent.py": """\
from orchestrator.models.agent import Agent, AgentRole, AgentState


def test_agent_is_planner():
    root = Agent(agent_id="r1", role=AgentRole.ROOT_PLANNER)
    sub = Agent(agent_id="s1", role=AgentRole.SUB_PLANNER)
    worker = Agent(agent_id="w1", role=AgentRole.WORKER)
    assert root.is_planner()
    assert sub.is_planner()
    assert not worker.is_planner()


def test_agent_is_worker():
    worker = Agent(agent_id="w1", role=AgentRole.WORKER)
    planner = Agent(agent_id="p1", role=AgentRole.ROOT_PLANNER)
    assert worker.is_worker()
    assert not planner.is_worker()


def test_agent_transition():
    agent = Agent(agent_id="a1", role=AgentRole.WORKER)
    agent.transition(AgentState.EXECUTING)
    assert agent.state == AgentState.EXECUTING
""",
    "tests/test_error_budget.py": """\
from orchestrator.models.error_budget import ErrorBudget


def test_error_budget_record_error():
    eb = ErrorBudget(budget_id="eb-1", owner_id="agent-1", max_errors=3)
    assert eb.record_error()
    assert eb.record_error()
    assert eb.record_error()
    assert not eb.record_error()
    assert eb.is_depleted


def test_error_budget_record_retry():
    eb = ErrorBudget(budget_id="eb-1", owner_id="agent-1", max_retries=2)
    assert eb.record_retry()
    assert eb.record_retry()
    assert not eb.record_retry()


def test_error_budget_remaining():
    eb = ErrorBudget(
        budget_id="eb-1",
        owner_id="agent-1",
        max_errors=5,
        max_retries=3,
        max_tokens=1000,
    )
    eb.record_error()
    eb.record_retry()
    eb.record_tokens(100)
    remaining = eb.remaining()
    assert remaining["errors"] == 4
    assert remaining["retries"] == 2
    assert remaining["tokens"] == 900
""",
}

INSTRUCTIONS = """\
Build a COMPLETE MULTI-AGENT ORCHESTRATION HARNESS called "orchestrator". 
Use ONLY Python stdlib. No external dependencies. This recreates the core patterns
from the Cursor research: planner-worker split, structured handoffs, workspace 
isolation, 3-way merge, event bus, watchdog, error budgets, and reconciliation.

=== SUBSYSTEM: Core Models (`orchestrator/models/`) ===

MODULE 1 — Task Board (`orchestrator/task_board.py`):

1. Create `orchestrator/task_board.py`:
   - `TaskBoard` class:
     - `__init__(self)`
     - `tasks: dict[str, Task]` — task_id -> Task
     - `create_task(self, title: str, description: str, priority: TaskPriority = TaskPriority.NORMAL) -> Task` — auto-generate ID
     - `get_task(self, task_id: str) -> Task | None`
     - `claim_task(self, task_id: str, agent_id: str) -> bool`
     - `complete_task(self, task_id: str, handoff_id: str) -> bool`
     - `fail_task(self, task_id: str, error: str) -> bool`
     - `get_ready_tasks(self) -> list[Task]` — tasks with no deps, PENDING status
     - `get_blocked_tasks(self) -> list[Task]` — tasks with unresolved deps
     - `add_dependency(self, task_id: str, depends_on: str) -> bool`
     - `resolve_dependency(self, completed_task_id: str) -> list[str]` — return unblocked task IDs
     - `get_stats(self) -> dict` — counts by status

MODULE 2 — Agent Registry (`orchestrator/agent_registry.py`):

2. Create `orchestrator/agent_registry.py`:
   - `AgentRegistry` class:
     - `__init__(self)`
     - `agents: dict[str, Agent]` — agent_id -> Agent
     - `create_agent(self, role: AgentRole, parent_id: str | None = None) -> Agent` — auto-generate ID
     - `get_agent(self, agent_id: str) -> Agent | None`
     - `get_children(self, parent_id: str) -> list[Agent]`
     - `get_planners(self) -> list[Agent]`
     - `get_workers(self) -> list[Agent]`
     - `mark_zombie(self, agent_id: str) -> bool`
     - `cleanup_agent(self, agent_id: str) -> bool`
     - `get_alive_agents(self) -> list[Agent]`
     - `heartbeat(self, agent_id: str) -> bool`

=== SUBSYSTEM: Planner Logic (`orchestrator/planner/`) ===

MODULE 3 — Task Decomposition (`orchestrator/planner/decomposer.py`):

3. Create `orchestrator/planner/__init__.py` — export planner components

4. Create `orchestrator/planner/decomposer.py`:
   - `TaskDecomposer` class:
     - `__init__(self, task_board: TaskBoard)`
     - `decompose(self, task: Task, strategy: str = "default") -> list[Task]` — break task into subtasks
     - `strategies: dict[str, Callable]` — mapping of strategy name to function
     - `add_strategy(self, name: str, func: Callable) -> None`
     - `_default_decompose(self, task: Task) -> list[Task]` — split by file/module boundaries
     - `_parallel_decompose(self, task: Task) -> list[Task]` — create independent parallel tasks
     - `_sequential_decompose(self, task: Task) -> list[Task]` — create dependent chain

MODULE 4 — Handoff Aggregation (`orchestrator/planner/aggregator.py`):

5. Create `orchestrator/planner/aggregator.py`:
   - `HandoffAggregator` class:
     - `__init__(self)`
     - `aggregate(self, handoffs: list[Handoff]) -> Handoff` — compress multiple handoffs into one
     - `_merge_narratives(self, narratives: list[str]) -> str` — combine with compression
     - `_merge_diffs(self, diffs_list: list[list[FileDiff]]) -> list[FileDiff]` — merge file changes
     - `_aggregate_metrics(self, metrics_list: list[HandoffMetrics]) -> HandoffMetrics` — sum metrics
     - `compression_ratio(self) -> float` — 20:1 target for SubPlanner aggregation

MODULE 5 — Work Orchestration (`orchestrator/planner/orchestrator.py`):

6. Create `orchestrator/planner/orchestrator.py`:
   - `WorkOrchestrator` class:
     - `__init__(self, task_board: TaskBoard, agent_registry: AgentRegistry, workspace_manager: WorkspaceManager)`
     - `orchestrate(self, planner_agent: Agent) -> None` — main orchestration loop
     - `_spawn_workers_for_ready_tasks(self, planner_agent: Agent) -> list[str]` — worker IDs spawned
     - `_collect_handoffs(self, worker_ids: list[str]) -> list[Handoff]` — wait for handoffs
     - `_merge_results(self, handoffs: list[Handoff], target_path: str) -> MergeResult`
     - `_handle_conflicts(self, conflicts: list[MergeConflict]) -> list[Task]` — spawn fixer tasks
     - `can_complete(self, planner_agent: Agent) -> bool` — check if all work done

=== SUBSYSTEM: Worker Logic (`orchestrator/worker/`) ===

MODULE 6 — Task Execution (`orchestrator/worker/executor.py`):

7. Create `orchestrator/worker/__init__.py` — export worker components

8. Create `orchestrator/worker/executor.py`:
   - `TaskExecutor` class:
     - `__init__(self, workspace_path: str, tools: dict[str, BaseTool])`
     - `execute(self, task: Task) -> tuple[bool, str]` — (success, result_summary)
     - `tools: dict[str, BaseTool]` — available tools
     - `_execute_instruction(self, instruction: str) -> ToolResult`
     - `_track_tool_usage(self, tool_name: str, result: ToolResult) -> None`
     - `get_execution_summary(self) -> dict`

MODULE 7 — Context Management (`orchestrator/worker/context.py`):

9. Create `orchestrator/worker/context.py`:
   - `ContextManager` class:
     - `__init__(self, max_tokens: int = 8000)`
     - `add_message(self, role: str, content: str) -> None`
     - `get_messages(self) -> list[dict]`
     - `estimate_tokens(self) -> int` — rough token count
     - `should_compress(self) -> bool` — check if over 80% threshold
     - `compress(self) -> str` — summarize and replace
     - `rewrite_scratchpad(self, content: str) -> None` — REWRITE not append
     - `get_scratchpad(self) -> str`

MODULE 8 — Handoff Builder (`orchestrator/worker/handoff_builder.py`):

10. Create `orchestrator/worker/handoff_builder.py`:
    - `HandoffBuilder` class:
      - `__init__(self, agent_id: str, task_id: str, parent_id: str)`
      - `with_narrative(self, narrative: str) -> Self`
      - `with_summary(self, summary: str) -> Self`
      - `with_diff(self, diff: FileDiff) -> Self`
      - `with_metrics(self, metrics: HandoffMetrics) -> Self`
      - `with_concerns(self, concerns: list[str]) -> Self`
      - `with_suggestions(self, suggestions: list[str]) -> Self`
      - `build(self) -> Handoff`
      - `_auto_generate_narrative(self) -> str` — if not provided

=== SUBSYSTEM: Tools (`orchestrator/tools/`) ===

MODULE 9 — Tool Registry (`orchestrator/tools/tool_registry.py`):

11. Create `orchestrator/tools/tool_registry.py`:
    - `ToolRegistry` class:
      - `__init__(self)`
      - `tools: dict[str, BaseTool]`
      - `register(self, tool: BaseTool) -> None`
      - `get(self, name: str) -> BaseTool | None`
      - `list_tools(self) -> list[str]`
      - `get_schemas(self) -> list[dict]` — for LLM tool definitions
      - `create_default_registry() -> ToolRegistry` — with bash, file, git tools

MODULE 10 — Additional Tools:

12. Create `orchestrator/tools/grep_tool.py`:
    - `GrepTool(BaseTool)` — search file contents:
      - `search(self, pattern: str, path: str, recursive: bool = True) -> list[str]`
      - `search_regex(self, pattern: str, path: str) -> list[str]`

13. Create `orchestrator/tools/find_tool.py`:
    - `FindTool(BaseTool)` — find files by pattern:
      - `find(self, pattern: str, path: str = ".") -> list[str]` — glob pattern
      - `find_by_extension(self, ext: str, path: str = ".") -> list[str]`

14. Create `orchestrator/tools/todo_tool.py`:
    - `TodoTool(BaseTool)` — track task progress:
      - `items: list[TodoItem]`
      - `add(self, content: str) -> None`
      - `complete(self, index: int) -> bool`
      - `get_pending(self) -> list[TodoItem]`
      - `is_all_complete(self) -> bool`
    - `TodoItem` dataclass: content, completed, created_at

=== SUBSYSTEM: Git Operations (`orchestrator/git/`) ===

MODULE 11 — Advanced Git Operations:

15. Create `orchestrator/git/repository.py`:
    - `Repository` class:
      - `__init__(self, path: str)`
      - `path: Path`
      - `is_git_repo(self) -> bool`
      - `get_current_branch(self) -> str`
      - `get_status(self) -> dict` — staged, unstaged, untracked
      - `stage_files(self, files: list[str]) -> bool`
      - `commit(self, message: str) -> bool`
      - `get_diff(self, staged: bool = False) -> str`
      - `create_branch(self, name: str) -> bool`
      - `checkout(self, ref: str) -> bool`
      - `get_log(self, n: int = 10) -> list[CommitInfo]`
    - `CommitInfo` dataclass: hash, author, date, message

16. Create `orchestrator/git/conflict_resolver.py`:
    - `ConflictResolver` class:
      - `__init__(self)`
      - `resolve_conflict(self, conflict: MergeConflict, strategy: str = "ours") -> str`
      - `strategies: dict[str, Callable]` — ours, theirs, union, manual
      - `_resolve_ours(self, conflict: MergeConflict) -> str`
      - `_resolve_theirs(self, conflict: MergeConflict) -> str`
      - `_resolve_union(self, conflict: MergeConflict) -> str`
      - `can_auto_resolve(self, conflict: MergeConflict) -> bool`

=== SUBSYSTEM: Event Bus (`orchestrator/events/`) ===

MODULE 12 — Event Handlers:

17. Create `orchestrator/events/metrics_handler.py`:
    - `MetricsHandler` class:
      - `__init__(self)`
      - `handle(self, event: Event) -> None`
      - `counters: dict[EventType, int]`
      - `agent_activity: dict[str, dict]`
      - `get_summary(self) -> dict`
      - `get_agent_stats(self, agent_id: str) -> dict`
      - `export_metrics(self, path: str) -> bool` — JSON export

18. Create `orchestrator/events/alert_handler.py`:
    - `AlertHandler` class:
      - `__init__(self, thresholds: dict)`
      - `handle(self, event: Event) -> None`
      - `check_thresholds(self) -> list[Alert]`
      - `alerts: list[Alert]` — active alerts
      - `acknowledge(self, alert_id: str) -> bool`
    - `Alert` dataclass: alert_id, level, message, source, created_at, acknowledged

=== SUBSYSTEM: Watchdog (`orchestrator/watchdog/`) ===

MODULE 13 — Pattern Detection (`orchestrator/watchdog/patterns.py`):

19. Create `orchestrator/watchdog/__init__.py`

20. Create `orchestrator/watchdog/patterns.py`:
    - `PatternDetector` class:
      - `__init__(self)`
      - `detect_zombie(self, agent: Agent, all_agents: list[Agent]) -> bool`
      - `detect_tunnel_vision(self, activity: dict) -> tuple[bool, str]`
      - `detect_token_burn(self, activity: dict) -> tuple[bool, str]`
      - `detect_scope_creep(self, task: Task, handoff: Handoff) -> bool`
      - `detect_diminishing_returns(self, attempts: list[dict]) -> bool`
      - `activity_history: dict[str, list[dict]]` — per-agent history
      - `record_activity(self, agent_id: str, activity: dict) -> None`

MODULE 14 — Intervention (`orchestrator/watchdog/intervention.py`):

21. Create `orchestrator/watchdog/intervention.py`:
    - `InterventionManager` class:
      - `__init__(self, agent_registry: AgentRegistry, task_board: TaskBoard)`
      - `intervene(self, agent_id: str, pattern: str, severity: str) -> bool`
      - `kill_agent(self, agent_id: str, reason: str) -> bool`
      - `restart_agent(self, agent_id: str) -> str` — new agent ID
      - `escalate_to_parent(self, agent_id: str, issue: str) -> bool`
      - `spawn_replacement_task(self, failed_task: Task) -> Task`
      - `interventions: list[dict]` — history

=== SUBSYSTEM: Reconciliation (`orchestrator/reconciliation/`) ===

MODULE 15 — Fixer Loop (`orchestrator/reconciliation/fixer.py`):

22. Create `orchestrator/reconciliation/__init__.py`

23. Create `orchestrator/reconciliation/fixer.py`:
    - `FixerLoop` class:
      - `__init__(self, max_rounds: int = 3)`
      - `max_rounds: int` — hard cap at 3
      - `current_round: int = 0`
      - `run(self, target_path: str, test_command: str) -> tuple[bool, str]` — (success, summary)
      - `_check_green(self, path: str, test_command: str) -> bool`
      - `_identify_issues(self, path: str, test_command: str) -> list[Issue]`
      - `_spawn_fix_task(self, issue: Issue) -> Task`
      - `_apply_fixes(self, fix_tasks: list[Task]) -> bool`
    - `Issue` dataclass: file_path, line_number, error_type, description, severity

MODULE 16 — Green Branch Verification (`orchestrator/reconciliation/verifier.py`):

24. Create `orchestrator/reconciliation/verifier.py`:
    - `GreenBranchVerifier` class:
      - `__init__(self)`
      - `verify(self, path: str, test_command: str) -> VerificationResult`
      - `_run_tests(self, path: str, test_command: str) -> TestResult`
      - `_check_syntax(self, path: str) -> list[SyntaxError]`
      - `_check_imports(self, path: str) -> list[str]` — broken imports
    - `VerificationResult` dataclass: passed, test_result, syntax_errors, broken_imports
    - `TestResult` dataclass: passed, total, passed_count, failed_tests, duration

=== SUBSYSTEM: Harness Runner (`orchestrator/runner/`) ===

MODULE 17 — Main Harness (`orchestrator/runner/harness.py`):

25. Create `orchestrator/runner/__init__.py`

26. Create `orchestrator/runner/harness.py`:
    - `Harness` class — the main orchestration entry point:
      - `__init__(self, config: HarnessConfig)`
      - `config: HarnessConfig`
      - `event_bus: EventBus`
      - `task_board: TaskBoard`
      - `agent_registry: AgentRegistry`
      - `workspace_manager: WorkspaceManager`
      - `watchdog: WatchdogAgent`
      - `run(self, instructions: str) -> str` — main entry, returns result summary
      - `_initialize(self) -> None` — setup all components
      - `_spawn_root_planner(self, instructions: str) -> str` — planner ID
      - `_await_completion(self, planner_id: str) -> bool`
      - `_final_reconciliation(self) -> bool`
      - `shutdown(self) -> None` — cleanup all agents

MODULE 18 — Configuration (`orchestrator/runner/config.py`):

27. Create `orchestrator/runner/config.py`:
    - `HarnessConfig` dataclass:
      - `repo_path: str`
      - `instructions: str = ""`
      - `test_command: str = "python -m pytest tests/ -v"`
      - `max_workers: int = 10`
      - `worker_timeout: float = 300.0`
      - `planner_max_turns: int = 50`
      - `planner_max_wall_time: float = 600.0`
      - `enable_watchdog: bool = True`
      - `error_budget_max_errors: int = 5`
      - `workspace_cleanup: bool = True`

=== SUBSYSTEM: Tests ===

MODULE 19 — Comprehensive Test Suite (`tests/`):

28. Create `tests/models/`:
    - `test_task_board.py` (5 tests): test_create, test_claim, test_deps, test_resolve, test_stats
    - `test_agent_registry.py` (4 tests): test_create, test_get_children, test_zombie, test_cleanup

29. Create `tests/planner/`:
    - `test_decomposer.py` (4 tests): test_default, test_parallel, test_sequential, test_custom
    - `test_aggregator.py` (3 tests): test_merge_narratives, test_merge_diffs, test_metrics
    - `test_orchestrator.py` (4 tests): test_spawn, test_collect, test_merge, test_conflicts

30. Create `tests/worker/`:
    - `test_executor.py` (3 tests): test_execute, test_tools, test_summary
    - `test_context.py` (3 tests): test_compress, test_scratchpad, test_tokens
    - `test_handoff_builder.py` (3 tests): test_build, test_narrative, test_metrics

31. Create `tests/git/`:
    - `test_workspace_manager.py` (3 tests): test_create, test_snapshot, test_cleanup
    - `test_merge_engine.py` (4 tests): test_clean_merge, test_conflict, test_new_file, test_deleted
    - `test_diff_engine.py` (3 tests): test_compute, test_hunks, test_file_diff
    - `test_repository.py` (3 tests): test_status, test_commit, test_branch

32. Create `tests/events/`:
    - `test_event_bus.py` (4 tests): test_publish, test_subscribe, test_history, test_filter
    - `test_handlers.py` (3 tests): test_console, test_file, test_metrics

33. Create `tests/watchdog/`:
    - `test_patterns.py` (4 tests): test_zombie, test_tunnel, test_burn, test_creep
    - `test_intervention.py` (3 tests): test_kill, test_restart, test_escalate

34. Create `tests/reconciliation/`:
    - `test_fixer.py` (3 tests): test_rounds, test_issues, test_apply
    - `test_verifier.py` (3 tests): test_verify, test_syntax, test_imports

35. Create `tests/integration/`:
    - `test_end_to_end.py` — full harness run with mock LLM
    - `test_planner_worker.py` — planner spawns worker, worker completes
    - `test_conflict_resolution.py` — two workers, merge conflict, fix
    - `test_watchdog_intervention.py` — zombie detection and kill
    - `test_error_recovery.py` — error budget, retry, success
    - `test_reconciliation.py` — failing tests, fixer loop, green

Run `python -m pytest tests/ -v` to verify ALL 180+ tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No external dependencies (no pytest for production code, only tests).
- LLM calls are mocked — use fake responses for testing.
- Git operations use file system simulation, not real git binary.
- All state is in-memory with optional JSON persistence.
- Async/await throughout for concurrency.
- No real subprocesses — BashTool uses mocks in test mode.
- Type hints everywhere.
- Docstrings on all public methods.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=16,
        name="MEGA-6: Multi-Agent Orchestration Harness",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=WORKER_TIMEOUT,
        expected_test_count=180,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
