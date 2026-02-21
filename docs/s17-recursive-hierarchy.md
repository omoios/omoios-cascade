# s17: Recursive Hierarchy

> SubPlanners can spawn SubPlanners. This enables the hierarchy to scale to arbitrary problem complexity by adding depth rather than width.

## The Problem: Flat Hierarchies Bottleneck at the Lead

In a flat team hierarchy, one lead agent attempts to coordinate dozens of workers. This creates a fundamental bottleneck: the lead becomes the limiting factor for throughput.

Consider a team with one Root Planner coordinating 20 Workers directly. The Root must:

- Track 20 parallel work streams
- Decompose problems into 20 distinct tasks
- Review 20 handoffs simultaneously
- Make delegation decisions for each worker

This breaks down at scale. The Root cannot efficiently manage more than a handful of workers before quality degrades. Each worker handoff requires attention, and the Root's context floods with details from all directions.

The V4 architecture in the Cursor harness demonstrated this failure mode: a single lead agent coordinating dozens of workers became the bottleneck. The solution requires more hierarchy, not more workers.

## The Solution: Recursive Delegation Tree

```
Root Planner
├── SubPlanner A (delegated slice: frontend)
│   ├── Worker A1 (header component)
│   ├── Worker A2 (footer component)
│   └── Worker A3 (navigation)
├── SubPlanner B (delegated slice: backend)
│   ├── Worker B1 (API routes)
│   ├── Worker B2 (database schema)
│   └── SubPlanner B1 (delegated: auth)
│       ├── Worker B3 (login endpoint)
│       └── Worker B4 (session management)
└── SubPlanner C (delegated slice: testing)
    ├── Worker C1 (unit tests)
    └── Worker C2 (integration tests)
```

The hierarchy grows deeper, not wider. Each SubPlanner manages a bounded number of children, typically 3-5. When a SubPlanner encounters a complex sub-problem, it spawns another SubPlanner rather than attempting to coordinate more workers directly.

This recursive pattern scales to handle problems of arbitrary complexity. A deeply nested tree can tackle massive engineering efforts while keeping each agent's coordination load manageable.

## How It Works: Recursive Delegation with Depth Limit

The recursive hierarchy operates through three mechanisms:

**1. Delegation by Scope**

A Root Planner receives a problem and decomposes it into high-level scopes. Each scope becomes a SubPlanner with a clear boundary: "you own the frontend" or "you own authentication." The SubPlanner does not know about other scopes, only its own delegated slice.

**2. Recursive Spawning**

A SubPlanner can spawn another SubPlanner when it encounters a sub-problem complex enough to warrant its own coordinator. The child SubPlanner reports to its parent, who aggregates the results and passes a compressed narrative upward.

**3. Depth Limiting**

To prevent infinite recursion, the system enforces a maximum depth, typically 3-4 levels. At the maximum depth, SubPlanners are prohibited from spawning further SubPlanners and must delegate directly to Workers. This prevents runaway hierarchy growth and ensures the system terminates.

```
depth 0: Root Planner
depth 1: SubPlanner (max 5 children)
depth 2: SubPlanner (max 5 children)  
depth 3: Workers only (leaf level)
```

## Key Code: RecursiveHierarchy Class

```python
class RecursiveHierarchy:
    """Manages recursive agent spawning with depth limits."""
    
    def __init__(self, max_depth: int = 3):
        self.max_depth = max_depth
        self.agents: dict[str, Agent] = {}
        self.parent_child: dict[str, list[str]] = {}
    
    def spawn_agent(
        self,
        agent_type: AgentType,
        scope: str,
        parent_id: str | None = None,
        current_depth: int = 0
    ) -> str:
        """Spawn an agent with recursive depth tracking."""
        
        # Enforce depth limit at leaf level
        if agent_type == AgentType.SUBPLANNER:
            if current_depth >= self.max_depth:
                agent_type = AgentType.WORKER
        
        agent_id = self._create_agent(agent_type, scope)
        
        # Establish parent-child relationship
        if parent_id:
            if parent_id not in self.parent_child:
                self.parent_child[parent_id] = []
            self.parent_child[parent_id].append(agent_id)
        
        self.agents[agent_id] = agent
        return agent_id
    
    def delegate_task(self, agent_id: str, task: Task) -> str:
        """Delegate task to appropriate agent type based on complexity."""
        
        agent = self.agents[agent_id]
        
        if self._is_complex_task(task) and self._can_spawn(agent_id):
            # Complex task: spawn SubPlanner
            child_id = self.spawn_agent(
                AgentType.SUBPLANNER,
                scope=task.description[:100],
                parent_id=agent_id,
                current_depth=self._get_depth(agent_id) + 1
            )
            return child_id
        else:
            # Simple task: spawn Worker
            child_id = self.spawn_agent(
                AgentType.WORKER,
                scope=task.description,
                parent_id=agent_id
            )
            return child_id
    
    def aggregate_handoffs(self, parent_id: str) -> Handoff:
        """Aggregate multiple child handoffs into single narrative."""
        
        children = self.parent_child.get(parent_id, [])
        handoffs = [self.agents[cid].submit_handoff() for cid in children]
        
        # Compress at ~20:1 ratio
        narrative = self._compress_narratives(handoffs)
        
        return Handoff(
            agent_id=parent_id,
            narrative=narrative,
            diff=self._merge_diffs(handoffs),
            status=self._resolve_status(handoffs)
        )
```

## What Changed: s16 vs s17 Comparison

| Aspect | s16 Optimistic Merge | s17 Recursive Hierarchy |
|--------|---------------------|------------------------|
| Structure | Flat Root → Workers | Tree Root → SubPlanner → Worker |
| Coordination | Root manages all workers | Each SubPlanner manages subset |
| Scale limit | ~10 workers per Root | Unlimited via recursion |
| Bottleneck | Lead agent overloaded | Depth-bounded coordination |
| Delegation | Direct Root → Worker | Recursive at each level |
| Complexity handling | Single level only | Arbitrary depth |

In s16, the system used optimistic merging to handle concurrent work. However, the flat hierarchy still bottlenecked at the lead. S17 introduces recursive delegation, allowing the system to scale horizontally by adding depth rather than requiring a single agent to manage everything.

**Key insight**: Adding hierarchy is the solution to coordination overload. A SubPlanner can spawn another SubPlanner, creating a tree that can handle problems of any size while keeping each agent's coordination load bounded.

## Production Reference: Cursor's SubPlanner Pattern

Primary source: docs/reference/cursor-harness-notes.md (Section 4: Agent Roles -> SubPlanner).

From the Cursor harness architecture, the SubPlanner role demonstrates recursive delegation in production:

> **SubPlanner**: Recursive — can spawn another SubPlanner, creating arbitrary depth in the hierarchy. Owns a delegated slice of the overall problem, decomposes its slice into tasks for Workers, collects ALL child handoffs and compresses them into a single aggregate narrative, reports to its parent (either Root Planner or another SubPlanner).

The Cursor system achieved ~1,000 commits per hour using this recursive hierarchy. The SubPlanner role enables:

- Bounded coordination load (3-5 children per SubPlanner)
- Information compression (~20:1 ratio at SubPlanner level)
- Independent sub-problem solving
- Clean aggregation of results upward

The production implementation includes depth tracking, automatic complexity assessment for delegation decisions, and narrative compression at each level.

## Try It: How to Test

Test the recursive hierarchy with a multi-component problem:

```bash
# Run the s17 agent with verbose logging
python agents/s17_recursive_hierarchy.py --task "build full-stack app"

# Observe the hierarchy spawn
# - Root decomposes into scopes
# - SubPlanners spawn for complex slices
# - Workers execute leaf tasks
# - Handoffs aggregate upward
```

**Verification checklist:**

1. Root spawns SubPlanners, not directly to Workers
2. SubPlanners can spawn other SubPlanners
3. Depth limit prevents infinite recursion
4. Handoffs compress at each level
5. Complex tasks trigger SubPlanner spawn
6. Simple tasks go directly to Workers

The recursive hierarchy transforms a coordination bottleneck into a scalable tree. Each SubPlanner manages a bounded subset, and the tree depth matches problem complexity.
