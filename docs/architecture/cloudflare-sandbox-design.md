# Distributed Sandbox Pool Design

A distributed alternative to the single-box harness architecture. Uses Cloudflare Workflows (Python) for durable orchestration, Modal Sandboxes for agent execution with memory snapshots, Neon Postgres for coordination, and Cloudflare R2 for object storage. Performance-critical paths implemented in Rust via PyO3.

## Platform Rationale

Each platform handles what it does best:

| Concern | Platform | Why |
|---|---|---|
| Orchestration | CF Workflows (Python) | Durable execution with automatic step retries, state persistence between steps, DAG support. Survives crashes without losing progress. |
| Agent execution | Modal Sandboxes | Sub-second cold starts, memory snapshots for pause/resume, Python-first SDK, gVisor isolation, scales to 20,000 concurrent. |
| Merge serialization | Modal Sandbox (dedicated) | Runs git operations that need a full Linux environment. Sequential dispatch via orchestrator. |
| Coordination DB | Neon Postgres | Already running. Full Postgres features (JSONB, FOR UPDATE SKIP LOCKED, enums). Reachable from both CF (Hyperdrive) and Modal (direct psycopg). |
| Object storage / volumes | Cloudflare R2 | Zero egress fees. S3-compatible. Stores volume snapshots, repo tarballs, patches. Reachable from Modal via boto3. |
| Real-time dashboard | Modal + FastRTC | WebRTC streaming with <100ms latency for live agent progress. |

## Service Mapping

| Harness Concept | Single-Box (current) | Distributed Equivalent |
|---|---|---|
| Task board | In-memory dict | Neon Postgres |
| Handoff store | In-memory dict | Neon Postgres + R2 (metadata in PG, diffs in R2) |
| Agent heartbeats | Thread-local | Neon Postgres rows, polled by watchdog step |
| Repo copies per worker | `.workspaces/worker-*/` | R2 tarball → Modal sandbox ephemeral disk (snapshotable) |
| Canonical repo | `.workspaces/canonical/` | R2 object (tarball) |
| Merge serialization | Thread lock | Orchestrator workflow step (sequential by design) |
| Task dispatch | Thread pool | Orchestrator creates Modal sandboxes via SDK |
| Watchdog | Daemon thread | CF Workflow step (periodic check in orchestrate loop) |
| Orchestrator | Root Planner in main thread | CF Workflow (Python, durable steps) |
| Worker agent | Thread with own workspace | Modal Sandbox (Python + Rust/PyO3) |

### Database Connectivity

Two access paths to the same Neon Postgres database:

- **CF Workflows (Python on edge)** connect through Cloudflare Hyperdrive. Hyperdrive maintains a global connection pool, eliminating per-request connection setup latency. Disable Neon's built-in PgBouncer — Hyperdrive replaces it.

- **Modal Sandboxes (full Linux)** connect directly to Neon using psycopg or asyncpg. Standard Postgres drivers, no special adapters needed.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│              CF Workflow (Python, durable execution)       │
│                                                           │
│  @step.do("decompose")                                    │
│  → LLM call: instruction → task list                      │
│  → INSERT tasks into Neon Postgres                        │
│                                                           │
│  @step.do("dispatch", depends=["decompose"])              │
│  → For each task: modal.Sandbox.create(...)               │
│  → Store sandbox IDs in Postgres                          │
│                                                           │
│  @step.do("orchestrate", depends=["dispatch"])            │
│  → Poll Postgres for handoff completions                  │
│  → Watchdog: check heartbeats, kill stale sandboxes       │
│  → On handoff: merge patch into canonical (R2)            │
│  → On conflict: create fix task, dispatch new sandbox     │
│  → Loop until all tasks resolved                          │
│                                                           │
│  @step.do("reconcile", depends=["orchestrate"])           │
│  → Create Modal sandbox: pull canonical, run test suite   │
│  → If green → snapshot to R2 as green branch              │
│  → If red → parse failures, create fixer tasks (max 3)    │
│  → Re-enter orchestrate if fixers spawned                 │
└──────────┬───────────────────────────────────────────────┘
           │ Modal Python SDK
     ┌─────┴─────┬───────────┬───────────┐
     ▼           ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Modal   │ │  Modal   │ │  Modal   │ │  Modal   │
│ Sandbox  │ │ Sandbox  │ │ Sandbox  │ │ Sandbox  │
│ (worker) │ │ (worker) │ │ (worker) │ │ (merge)  │
│          │ │          │ │          │ │          │
│ Python   │ │ Python   │ │ Python   │ │ git ops  │
│ + Rust   │ │ + Rust   │ │ + Rust   │ │ + Rust   │
│ (PyO3)   │ │ (PyO3)   │ │ (PyO3)   │ │ (PyO3)   │
│          │ │          │ │          │ │          │
│ snapshot │ │ snapshot │ │ snapshot │ │          │
│ capable  │ │ capable  │ │ capable  │ │          │
└────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
     │            │            │             │
     └─────┬──────┴────────────┘             │
           ▼                                 ▼
┌──────────────────────────────────────────────────────┐
│                    Neon Postgres                      │
│  (CF via Hyperdrive | Modal via direct psycopg)      │
│  tasks | handoffs | agents | merge_log               │
└──────────────────────────────────────────────────────┘
           │                                 │
           ▼                                 ▼
┌──────────────────────────────────────────────────────┐
│                    Cloudflare R2                      │
│  repos/{project}/canonical.tar.gz                    │
│  repos/{project}/patches/{handoff_id}.patch          │
│  repos/{project}/snapshots/{sha}.tar.gz              │
└──────────────────────────────────────────────────────┘
```

## Postgres Schema (Neon)

Single Neon Postgres database. CF Workflows access it via Hyperdrive. Modal Sandboxes access it directly via psycopg. Disable Neon's built-in PgBouncer when Hyperdrive is in use.

```sql
CREATE TYPE task_status AS ENUM (
    'pending', 'assigned', 'in_progress', 'completed', 'failed', 'blocked'
);

CREATE TYPE handoff_status AS ENUM (
    'success', 'partial_failure', 'failed', 'blocked'
);

CREATE TYPE merge_status AS ENUM (
    'pending', 'queued', 'merged', 'conflict', 'build_fail'
);

CREATE TYPE agent_status AS ENUM (
    'starting', 'active', 'completed', 'failed', 'killed'
);

CREATE TYPE agent_role AS ENUM (
    'worker', 'merge_worker'
);

CREATE TYPE merge_result AS ENUM (
    'clean', 'conflict', 'build_fail'
);

-- Task board
CREATE TABLE tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id       UUID REFERENCES tasks(id),
    project_id      TEXT NOT NULL,
    spec            JSONB NOT NULL,             -- task description, constraints, context
    status          task_status NOT NULL DEFAULT 'pending',
    assigned_to     TEXT,                       -- Modal sandbox ID (sb-xxxxx)
    priority        INTEGER NOT NULL DEFAULT 0,
    depth           INTEGER NOT NULL DEFAULT 0, -- hierarchy depth (0 = root)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_parent ON tasks(parent_id);
CREATE INDEX idx_tasks_project ON tasks(project_id, status);
CREATE INDEX idx_tasks_pending ON tasks(project_id) WHERE status = 'pending' AND assigned_to IS NULL;

-- Handoff store (metadata; actual diffs live in R2)
CREATE TABLE handoffs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES tasks(id),
    agent_id        UUID NOT NULL,
    status          handoff_status NOT NULL,
    narrative       TEXT NOT NULL,               -- the critical field
    diff_path       TEXT,                        -- R2 key for patch file
    metrics         JSONB NOT NULL,              -- wall_time, tokens_used, attempts, files_modified
    merge_status    merge_status NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_handoffs_task ON handoffs(task_id);
CREATE INDEX idx_handoffs_merge ON handoffs(merge_status);

-- Agent/sandbox registry
CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sandbox_id      TEXT,                        -- Modal sandbox ID (sb-xxxxx)
    snapshot_id     TEXT,                        -- Modal snapshot ID (if paused)
    role            agent_role NOT NULL,
    task_id         UUID REFERENCES tasks(id),
    status          agent_status NOT NULL DEFAULT 'starting',
    heartbeat_at    TIMESTAMPTZ,
    tokens_used     INTEGER DEFAULT 0,
    tool_calls      INTEGER DEFAULT 0,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    stopped_at      TIMESTAMPTZ
);

CREATE INDEX idx_agents_status ON agents(status);
CREATE INDEX idx_agents_stale ON agents(heartbeat_at) WHERE status = 'active';

-- Merge log (audit trail)
CREATE TABLE merge_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    handoff_id      UUID NOT NULL REFERENCES handoffs(id),
    result          merge_result NOT NULL,
    details         TEXT,                        -- conflict file list or build error output
    canonical_sha   TEXT,                        -- sha after merge (if clean)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Task claim uses row-level locking to prevent double-assignment.
-- Sandboxes call this to atomically claim a pending task:
--
--   UPDATE tasks
--   SET    assigned_to = $1, status = 'assigned', updated_at = now()
--   WHERE  id = (
--       SELECT id FROM tasks
--       WHERE  project_id = $2
--       AND    status = 'pending'
--       AND    assigned_to IS NULL
--       ORDER BY priority DESC, created_at ASC
--       LIMIT 1
--       FOR UPDATE SKIP LOCKED
--   )
--   RETURNING *;
--
-- FOR UPDATE SKIP LOCKED ensures concurrent sandboxes don't block
-- each other and never claim the same task.
```

## R2 Layout (Volume Snapshots + Object Storage)

R2 serves as the volume snapshot layer. Zero egress fees make it practical to pull large repo tarballs into sandboxes frequently. S3-compatible, so Modal sandboxes access it via boto3/aioboto3.

```
harness-pool/
├── volumes/
│   └── {project_id}/
│       ├── canonical.tar.gz           # current canonical repo state (volume snapshot)
│       ├── canonical.sha              # content hash for cache invalidation
│       └── snapshots/
│           └── {sha}.tar.gz           # point-in-time volume snapshots (green branches)
├── patches/
│   └── {project_id}/
│       └── {handoff_id}.patch         # git-format patches from workers
├── artifacts/
│   └── {handoff_id}/
│       └── ...                        # build outputs, logs, generated files
└── config/
    └── {project_id}.json              # project-level config (repos, branches, limits)
```

The `volumes/` prefix stores complete workspace snapshots. These are the "volume mounts" for sandboxes — each worker pulls a volume snapshot at startup, works locally, and produces a patch. The merge sandbox pulls the canonical volume, applies the patch, and uploads a new volume snapshot if clean.

The `canonical.sha` file is a small object containing the content hash of the current canonical tarball. Sandboxes check this before downloading to avoid re-fetching unchanged state.

Volume snapshots in R2 complement Modal's filesystem snapshots. R2 snapshots are portable (any sandbox can pull them), persistent (no expiry), and cheap (zero egress). Modal filesystem snapshots are faster to restore but tied to Modal's infrastructure and have retention limits (30 days for directory snapshots).

## Orchestrator (CF Workflow, Python)

The orchestrator is a Cloudflare Workflow written in Python. Each step is independently retriable with state persisted between steps. If the workflow crashes, it resumes from the last completed step.

```python
from workers import WorkflowEntrypoint
from workers.workflows import step
import modal

class HarnessWorkflow(WorkflowEntrypoint):
    """Durable orchestration workflow. Each step survives crashes."""

    async def run(self, ctx, payload):
        instruction = payload["instruction"]
        project_id = payload["project_id"]

        # Step 1: Decompose instruction into tasks
        tasks = await self.decompose(ctx, instruction, project_id)

        # Step 2: Dispatch sandboxes for each task
        sandbox_ids = await self.dispatch(ctx, tasks, project_id)

        # Step 3: Orchestrate (loop until all resolved)
        await self.orchestrate(ctx, project_id)

        # Step 4: Reconcile (test suite, fixer loop)
        await self.reconcile(ctx, project_id)

    @step.do("decompose")
    async def decompose(self, ctx, instruction, project_id):
        """LLM decomposes instruction into task rows in Postgres."""
        # Connect to Neon via Hyperdrive
        tasks = await llm_decompose(instruction, project_id)
        await db_insert_tasks(ctx.env, tasks)
        return [t["id"] for t in tasks]

    @step.do("dispatch")
    async def dispatch(self, ctx, task_ids, project_id):
        """Create a Modal sandbox for each task."""
        sandbox_ids = []
        for task_id in task_ids:
            sb = modal.Sandbox.create(
                "python", "-m", "harness.sandbox_worker",
                image=worker_image,
                secrets=[modal.Secret.from_name("harness-secrets")],
                timeout=300,
                _experimental_enable_snapshot=True,
            )
            await db_assign_task(ctx.env, task_id, sb.object_id)
            sandbox_ids.append(sb.object_id)
        return sandbox_ids

    @step.do("orchestrate")
    async def orchestrate(self, ctx, project_id):
        """Poll for completions, merge, handle conflicts, watchdog."""
        while True:
            # Check for new handoffs
            handoffs = await db_pending_handoffs(ctx.env, project_id)
            for h in handoffs:
                await self.merge_handoff(ctx, h)

            # Watchdog: kill stale sandboxes
            stale = await db_stale_agents(ctx.env)
            for agent in stale:
                sb = modal.Sandbox.from_id(agent["sandbox_id"])
                sb.terminate()
                await db_requeue_task(ctx.env, agent["task_id"])

            # Check completion
            remaining = await db_incomplete_tasks(ctx.env, project_id)
            if not remaining:
                break

            await ctx.sleep("10s")

    @step.do("reconcile")
    async def reconcile(self, ctx, project_id):
        """Run test suite on canonical. Spawn fixers if needed."""
        for round in range(3):  # Hard cap: 3 fixer rounds
            sb = modal.Sandbox.create(
                "bash", "-c", "cd /work && tar xzf canonical.tar.gz && make test",
                image=worker_image,
                timeout=600,
            )
            sb.wait()
            if sb.returncode == 0:
                # Green branch -- snapshot canonical
                await r2_snapshot_canonical(ctx.env, project_id)
                return
            # Parse failures, create fixer tasks
            failures = parse_test_output(sb.stderr.read())
            fixer_tasks = await llm_generate_fixers(failures)
            await db_insert_tasks(ctx.env, fixer_tasks)
            await self.dispatch(ctx, [t["id"] for t in fixer_tasks], project_id)
            await self.orchestrate(ctx, project_id)
        raise Exception(f"Reconciliation failed after 3 rounds for {project_id}")

    async def merge_handoff(self, ctx, handoff):
        """Apply a worker's patch to canonical. Sequential by design."""
        sb = modal.Sandbox.create(
            "python", "-m", "harness.merge_worker",
            image=worker_image,
            environment={
                "HANDOFF_ID": handoff["id"],
                "PATCH_KEY": handoff["diff_path"],
                "PROJECT_ID": handoff["project_id"],
            },
            timeout=120,
        )
        sb.wait()
        # Merge worker writes result to merge_log in Postgres
```

### Why CF Workflows Instead of a Modal Function

The orchestrator needs durable execution — if it crashes mid-run (network error, timeout, OOM), it must resume from the last completed step without re-doing work. CF Workflows provides this natively: each `@step.do` boundary is a checkpoint. Modal functions don't have built-in durable execution with step-level persistence.

The orchestrator also doesn't need a full Linux environment. It makes LLM calls and database queries — both are HTTP. CF Workflows runs Python on the edge (via Pyodide), which is sufficient for this control-plane logic.

### API Surface

The workflow is triggered via CF Workers HTTP handler:

```
POST /projects/{id}/run     -- start a workflow instance
GET  /projects/{id}/status  -- current workflow state + task board
POST /projects/{id}/cancel  -- cancel workflow and terminate sandboxes
GET  /handoffs/{id}         -- read handoff with narrative
```

## Modal Sandbox Lifecycle

### Worker Sandbox

Each sandbox runs a Python agent with the harness agent loop. The Modal image includes Python, git, the harness package, and the Rust core extension.

```python
# Modal image definition (built once, reused across all workers)
worker_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install_from_pyproject("pyproject.toml")
    .copy_local_file("harness-core/dist/harness_core-0.1.0-cp312-linux_x86_64.whl", "/tmp/")
    .pip_install("/tmp/harness_core-0.1.0-cp312-linux_x86_64.whl")
)
```

```
Sandbox startup:
  1. Read task_id and project_id from environment
  2. Connect to Neon Postgres (direct psycopg, no Hyperdrive)
  3. Read task spec from tasks table
  4. Pull canonical.tar.gz from R2 (boto3, S3-compatible) → extract to /work

Sandbox execution:
  5. Agent loop: LLM calls → tool use → file modifications on /work
  6. Heartbeat: UPDATE agents SET heartbeat_at=now() every 15 seconds

Sandbox completion:
  7. Generate patch: harness_core.diff_trees(/work_original, /work) → patch bytes
  8. Upload patch to R2 as repos/{project}/patches/{handoff_id}.patch
  9. INSERT handoff row (narrative, metrics, diff_path)
  10. UPDATE task status to 'completed'
  11. Exit (sandbox terminates or sleeps)
```

### Memory Snapshots (Pause/Resume)

Modal's memory snapshot feature solves the ephemeral disk problem. A sandbox's entire state — memory, filesystem, running processes — can be snapshotted and later restored as a new sandbox.

Use cases in the harness:

```python
# Snapshot a long-running agent before idle timeout
sb = modal.Sandbox.from_id(sandbox_id)
snapshot = sb._experimental_snapshot()
await db_update_agent(agent_id, snapshot_id=snapshot.object_id, status="paused")

# Resume from snapshot when work is available
snapshot = modal.SandboxSnapshot.from_id(snapshot_id)
sb = snapshot.restore(timeout=300)
await db_update_agent(agent_id, sandbox_id=sb.object_id, status="active")
```

This enables:
- **Cost savings.** Pause idle sandboxes instead of keeping them running. Resume only when the orchestrator has work for them.
- **Long-running agents.** Agents that exceed Modal's 24-hour sandbox limit can be snapshotted, then restored into a fresh sandbox with full state preserved.
- **Warm pools.** Pre-create sandboxes with the repo extracted and dependencies loaded, snapshot them, then restore from snapshot for sub-second "cold" starts.

### Filesystem Snapshots (Cheaper Alternative)

When full memory state isn't needed (e.g., the agent has exited and only the workspace matters), filesystem snapshots are lighter:

```python
# Snapshot just the filesystem (diff-based, persists indefinitely)
fs_snapshot = sb._experimental_filesystem_snapshot()

# Restore into a new sandbox with that filesystem state
new_sb = modal.Sandbox.create(
    "python", "-m", "harness.sandbox_worker",
    image=worker_image.from_snapshot(fs_snapshot),
    timeout=300,
)
```

### Merge Sandbox

A dedicated sandbox type that only handles merge operations:

```
Sandbox startup:
  1. Read environment: HANDOFF_ID, PATCH_KEY, PROJECT_ID
  2. Connect to Neon Postgres (direct psycopg)
  3. Pull canonical.tar.gz from R2 → extract to /canonical
  4. Pull patch from R2

Merge execution:
  5. Apply patch: harness_core.patch_apply(canonical_path, patch_bytes)
  6. If conflict → INSERT merge_log(result='conflict', details=...), exit
  7. If clean → run build/test command (from project config in R2)
  8. If build fails → INSERT merge_log(result='build_fail', details=...), exit
  9. If green → tar /canonical → upload to R2 as new canonical.tar.gz
  10. INSERT merge_log(result='clean', canonical_sha=new_sha)
  11. Exit
```

Merges are sequential by design — the orchestrator's `merge_handoff` method processes one handoff at a time within the `orchestrate` step.

## Rust Core (harness-core)

A Rust crate with PyO3 bindings, built with maturin. Installed as a Python wheel in the Modal sandbox image.

### Module Structure

```
harness-core/
├── Cargo.toml
├── pyproject.toml              # maturin build config
└── src/
    ├── lib.rs                  # PyO3 module definition
    ├── patch.rs                # diff generation and patch application
    ├── graph.rs                # task dependency resolution
    ├── hash.rs                 # content-addressable hashing (blake3)
    └── watch.rs                # watchdog metric computation
```

### Exposed Functions

```python
import harness_core

# -- patch.rs --
# Generate a unified diff between two directory trees
diff: bytes = harness_core.diff_trees(base_path: str, modified_path: str)

# Apply a patch to a directory tree, return list of conflicting files
conflicts: list[str] = harness_core.patch_apply(
    target_path: str,
    patch_bytes: bytes,
    strategy: str = "3way"  # "3way" | "ours" | "theirs"
)

# Three-way merge of a single file
result: MergeResult = harness_core.merge_file(
    base: bytes,
    ours: bytes,
    theirs: bytes
)

# -- graph.rs --
# Topological sort with cycle detection
order: list[str] = harness_core.topo_sort(
    edges: list[tuple[str, str]]  # (from, to) dependency edges
)

# Critical path through task graph (longest weighted path)
path: list[str] = harness_core.critical_path(
    nodes: dict[str, float],       # task_id → estimated duration
    edges: list[tuple[str, str]]
)

# -- hash.rs --
# Blake3 hash of a file or directory tree (content-addressable)
sha: str = harness_core.hash_file(path: str)
sha: str = harness_core.hash_tree(path: str)

# -- watch.rs --
# Compute watchdog metrics from agent activity log
metrics: WatchMetrics = harness_core.compute_watch_metrics(
    heartbeats: list[dict],  # timestamp, tokens_used, tool_calls, files_modified
    thresholds: dict         # zombie_timeout, token_burn_limit, tunnel_vision_limit
)
# Returns: is_zombie, is_burning, is_tunneling, idle_seconds, burn_rate
```

### Why These Functions

| Function | Why Rust | Frequency |
|---|---|---|
| `diff_trees` | CPU-bound tree walk + diff algorithm on potentially large repos | Every worker completion |
| `patch_apply` | Must be fast and correct; merge conflicts need precise detection | Every merge attempt |
| `merge_file` | 3-way merge is algorithmically intensive | Per-file during conflicts |
| `topo_sort` | Called frequently during scheduling; graph can be large | Every scheduling cycle |
| `critical_path` | Weighted graph traversal; informs priority ordering | Every scheduling cycle |
| `hash_tree` | Walks entire repo tree; blake3 is Rust-native and fast | Every canonical update |
| `compute_watch_metrics` | Runs every watchdog cycle across all active agents | Every orchestrate loop |

Everything else (LLM calls, Postgres I/O, R2 I/O, handoff serialization, narrative generation) stays in Python. The Rust boundary is strictly compute-intensive operations where Python's interpreter overhead is measurable.

### Build and Distribution

```bash
# Build for linux/x86_64 (Modal sandbox target)
cd harness-core
maturin build --release --target x86_64-unknown-linux-gnu

# Build for local development (macOS ARM)
maturin develop --release
```

CI builds both wheels. The linux wheel is baked into the Modal image. The macOS wheel is used for local development and testing.

## Concurrency Model

Four layers of parallelism, each handling a different concern:

```
┌─────────────────────────────────────────────────────────┐
│                      asyncio                             │
│  (top-level event loop in orchestrator + each sandbox)   │
│                                                          │
│  All network I/O is async:                               │
│  - LLM API calls (httpx / anthropic async client)        │
│  - Postgres queries (asyncpg)                            │
│  - R2 operations (aioboto3)                              │
│  - Agent Protocol HTTP calls (httpx)                     │
│  - Heartbeat writes                                      │
│                                                          │
│  Handles 90% of concurrency. No GIL contention           │
│  because everything is I/O-bound.                        │
└────────┬────────────────────────────────┬────────────────┘
         │                                │
         ▼                                ▼
┌────────────────────┐     ┌──────────────────────────────┐
│  ThreadPoolExecutor │     │  PyO3 + Rayon                 │
│  (GIL-releasing)    │     │  (true CPU parallelism)       │
│                     │     │                               │
│  For mixed I/O:     │     │  CPU-bound, GIL-free:         │
│  - git subprocess   │     │  - diff_trees (rayon par_iter)│
│  - file watchers    │     │  - patch_apply                │
│  - agent loops      │     │  - merge_file                 │
│    (each agent is   │     │  - hash_tree (rayon par_iter) │
│     a thread with   │     │  - topo_sort                  │
│     its own async   │     │  - critical_path              │
│     event loop)     │     │                               │
│                     │     │  PyO3 releases GIL on entry.  │
│  run_in_executor()  │     │  Rayon parallelizes across    │
│  bridges async →    │     │  all CPU cores automatically. │
│  sync boundaries.   │     │  A diff that takes 2s in      │
│                     │     │  Python takes ~50ms in Rust.   │
└────────────────────┘     └──────────────────────────────┘
         │
         ▼
┌────────────────────┐
│  multiprocessing    │
│  (NOT needed)       │
│                     │
│  Modal provides     │
│  process isolation  │
│  across machines.   │
│  No local process   │
│  pools required.    │
└────────────────────┘
```

### How They Compose

**Inside the orchestrator (CF Workflow):**
- asyncio event loop handles all HTTP calls (LLM, Postgres, Modal SDK)
- No threads or processes needed — orchestrator is pure I/O

**Inside a worker sandbox (Modal):**
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
import harness_core  # Rust/PyO3

executor = ThreadPoolExecutor(max_workers=4)

async def agent_loop():
    while True:
        # Async: LLM call
        response = await anthropic_client.messages.create(...)

        # Async: tool execution (most tools are I/O)
        if tool == "bash":
            result = await asyncio.to_thread(subprocess.run, cmd, ...)
        elif tool == "read_file":
            result = await aiofiles.open(path).read()

        # Rust/PyO3: CPU-bound diff at handoff time (GIL released)
        patch = harness_core.diff_trees(original_path, work_path)

        # Async: upload patch to R2
        await r2_client.put_object(Key=patch_key, Body=patch)

        # Async: heartbeat (runs concurrently via task)
        # (started once, runs in background)

async def heartbeat_loop(agent_id: str):
    while True:
        await asyncpg_pool.execute(
            "UPDATE agents SET heartbeat_at=now(), tokens_used=$1 WHERE id=$2",
            token_count, agent_id
        )
        await asyncio.sleep(15)

async def main():
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        await asyncio.gather(
            agent_loop(),
            heartbeat_loop(agent_id),
        )
```

### PyO3 + Rayon Pattern

The Rust crate uses `pyo3` with `allow_threads` to release the GIL during computation, and `rayon` for automatic work-stealing parallelism:

```rust
use pyo3::prelude::*;
use rayon::prelude::*;

#[pyfunction]
fn diff_trees(py: Python, base: &str, modified: &str) -> PyResult<Vec<u8>> {
    // Release the GIL — Python can run other threads while this executes
    py.allow_threads(|| {
        let base_files = walk_tree(base);
        let modified_files = walk_tree(modified);

        // Rayon parallelizes across CPU cores automatically
        let diffs: Vec<FileDiff> = modified_files
            .par_iter()  // parallel iterator
            .filter_map(|f| compute_diff(base, f))
            .collect();

        serialize_patch(diffs)
    })
}

#[pyfunction]
fn hash_tree(py: Python, path: &str) -> PyResult<String> {
    py.allow_threads(|| {
        let files = walk_tree(path);
        // Hash all files in parallel, then combine
        let hashes: Vec<blake3::Hash> = files
            .par_iter()
            .map(|f| blake3::hash(&std::fs::read(f).unwrap()))
            .collect();
        combine_hashes(hashes).to_hex().to_string()
    })
}
```

## Layering Other Agents (Post-MVP, via ACP)

The MVP uses a custom agent loop inside Modal sandboxes. Once the harness works end-to-end, a natural extension is layering existing coding agents (Claude Code, Codex CLI, goose, etc.) as alternative workers.

Two protocols exist for this:

| Protocol | Focus | Transport | Agents That Support It |
|---|---|---|---|
| [Agent Client Protocol (ACP)](https://agentclientprotocol.com/) | IDE ↔ coding agent | JSON-RPC over stdio (local), HTTP/WebSocket (remote) | Claude Code, Codex CLI, Gemini, goose, StackPack |
| [Agent Protocol](https://agentprotocol.ai/) | Universal agent API | REST (OpenAPI 3.0) | Generic; fewer coding agents natively |

ACP is the more relevant one. It's purpose-built for coding agents and the agents you'd want to layer already speak it. It was created by Zed Industries and JetBrains as "LSP but for AI agents."

### How It Would Work

Each Modal sandbox runs one coding agent with an ACP-compatible interface. The orchestrator dispatches tasks to sandboxes the same way it does for custom workers — the only difference is what runs inside the sandbox.

```python
# Future: agent routing by task type
AGENT_ROUTING = {
    "implement_feature": "claude-code",
    "bulk_tests":        "codex",
    "refactor":          "goose",
    "long_refactor":     "harness",      # custom loop for coherence-sensitive tasks
}
```

Each non-harness agent gets a thin wrapper (~50-100 lines) that:
1. Starts the agent process inside the sandbox
2. Passes the task instruction via ACP
3. Collects the output (modified files, diffs)
4. Formats it as a harness handoff (narrative + patch + metrics)

The custom harness agent handles tasks that benefit from scratchpad rewriting, context compression, and structured handoffs. Existing agents handle everything else.

### Why Not Now

Build the harness first. The custom agent loop is where the learning happens — coherence mechanisms, handoff protocol, scratchpad rewriting, watchdog behavior. Layering existing agents is a scaling optimization, not a prerequisite. Once the harness works, adding ACP wrappers for Claude Code or Codex is a small incremental step.

## Real-Time Dashboard (Optional, Post-MVP)

Modal's FastRTC integration enables WebRTC streaming of agent progress to a browser dashboard with <100ms latency.

```python
# Stream agent activity to dashboard via WebRTC
@modal.function(image=dashboard_image)
async def agent_dashboard(sandbox_ids: list[str]):
    """WebRTC stream of live agent progress."""
    while sandbox_ids:
        for sid in sandbox_ids:
            sb = modal.Sandbox.from_id(sid)
            # Read agent's stdout/stderr
            output = sb.stdout.read()
            # Stream to connected WebRTC peer
            await rtc_send(output)
        await asyncio.sleep(0.1)
```

This is not needed for MVP but becomes valuable when running 20+ agents and wanting visibility into what each one is doing.

## MVP Definition

The minimum viable system that demonstrates the hybrid architecture end-to-end.

### MVP Scope

```
CF Workflow (Python)
  - Single workflow: decompose → dispatch → orchestrate → done
  - Decomposes instruction into 3-5 leaf tasks (no sub-planners)
  - Flat task list, no recursive hierarchy
  - Single LLM call for decomposition
  - Sequential merge in orchestrate loop
  - Zombie-only watchdog (heartbeat staleness check)

Neon Postgres
  - tasks + handoffs + agents tables
  - No merge_log (merges logged as handoff status updates)

Cloudflare R2
  - canonical.tar.gz (single project)
  - patches/{handoff_id}.patch

Modal Sandboxes
  - Worker sandboxes: Python agent loop, no scratchpad, no compression
  - Pull canonical from R2, do work, push patch, write handoff to Postgres
  - Heartbeat every 15s (direct psycopg)
  - No memory snapshots (sandboxes run to completion)

Rust Core
  - diff_trees + patch_apply + hash_tree only
  - Other functions stay Python until profiling shows need
```

### MVP Does NOT Include

- Recursive sub-planners (flat task decomposition only)
- Handoff review by LLM (auto-accept all completions)
- Build/test verification in merge pipeline
- Scratchpad rewriting or context compression
- Multi-project support
- Memory snapshots or warm pools
- Green branch reconciliation pass
- Error budgets or tunnel-vision detection
- Real-time dashboard / WebRTC streaming

### MVP File Structure

```
harness-distributed/
├── orchestrator/                  # CF Workflow (Python)
│   ├── src/
│   │   ├── workflow.py            # HarnessWorkflow (decompose, dispatch, orchestrate)
│   │   ├── llm.py                 # Anthropic API calls for decomposition
│   │   ├── db.py                  # Postgres queries (via Hyperdrive)
│   │   └── r2.py                  # R2 operations
│   └── wrangler.toml              # Hyperdrive binding, R2 binding
├── harness-core/                  # Rust crate (PyO3)
│   ├── Cargo.toml
│   ├── pyproject.toml             # maturin config
│   └── src/
│       ├── lib.rs
│       ├── patch.rs
│       └── hash.rs
├── src/harness/                   # Python package (runs in Modal sandboxes)
│   ├── sandbox_worker.py          # Worker sandbox entrypoint
│   ├── merge_worker.py            # Merge sandbox entrypoint
│   ├── agent_loop.py              # Core agent loop (LLM + tools)
│   ├── tools.py                   # bash, read, write, edit
│   ├── db.py                      # psycopg Neon connection (direct)
│   └── r2_client.py               # R2 via boto3 (S3-compatible)
├── modal_app.py                   # Modal image definitions + sandbox helpers
├── schema.sql                     # Postgres schema (Neon)
└── pyproject.toml
```

## Scaling Path (Post-MVP)

Once the MVP works end-to-end with flat task decomposition and sequential merge:

**Phase 1: Memory Snapshots.** Enable `_experimental_enable_snapshot` on worker sandboxes. Snapshot idle agents instead of killing them. Maintain a warm pool of pre-snapshotted sandboxes with the repo already extracted for near-instant dispatch.

**Phase 2: Recursive Hierarchy.** Add sub-planner support. A sub-planner is a sandbox that decomposes its slice and creates sub-tasks in Postgres. The orchestrator tracks hierarchy depth and enforces max depth.

**Phase 3: Handoff Review.** Orchestrator uses LLM to review handoff narratives before accepting. Failed reviews create retry tasks with feedback in the spec.

**Phase 4: Reconciliation.** After all tasks complete, run the reconciliation step: pull canonical, run full test suite in a sandbox, parse failures, spawn targeted fixer tasks. Hard cap of 3 fixer rounds.

**Phase 5: Coherence.** Add scratchpad rewriting, context compression, and state reconstruction for long-running agents. Use memory snapshots to persist agent state across compression events. Add error budgets and tunnel-vision detection to the watchdog.

**Phase 6: Real-Time Dashboard.** WebRTC streaming via Modal FastRTC for live agent progress. Browser-based dashboard showing task board, active sandboxes, and streaming agent output.

## Cost Model (Rough Estimates)

Based on current pricing for a run of 50 tasks:

| Resource | Usage | Cost |
|---|---|---|
| Neon Postgres | ~5,000 queries, ~50 MB storage | Free tier or ~$0.10 on Scale |
| Hyperdrive | Included with Workers paid plan | $0 (bundled) |
| R2 storage | ~500 MB (canonical + patches + snapshots) | ~$0.0075 |
| R2 operations | ~200 Class A + ~500 Class B | ~$0.001 |
| CF Workflows | ~50 step executions | ~$0.015 |
| Modal Sandboxes | 50 workers x ~2 min each = 100 min CPU | ~$0.16 (at $0.047/vCPU-hr) |
| Modal Merge | ~50 merges x ~30s each = 25 min CPU | ~$0.02 |
| Anthropic API | 50 agent runs + decomposition + review | Dominant cost |

**Total infrastructure: ~$0.40 per 50-task run** (excluding LLM costs).

The infrastructure cost is negligible compared to LLM API costs. A 50-task run costs under $1 in infrastructure vs $50-200 in Anthropic API calls depending on model and context length. Modal is cheaper than CF Containers for this workload because of per-second billing and the ability to scale to zero between runs.

Since you already have a Neon instance, the database cost is effectively zero.

## Open Questions

1. **CF Workflow + Modal SDK compatibility.** CF Python Workflows run on Pyodide (WebAssembly). The Modal Python SDK may not work inside Pyodide due to native dependencies. If not, the workflow would need to call a thin HTTP API that wraps Modal SDK operations, or use Modal's REST API directly. Alternative: run the orchestrator as a Modal function with manual checkpointing to Postgres instead of CF Workflows.

2. **Neon connection limits.** Neon free tier allows 100 concurrent connections (5 per endpoint on autoscale). With 50 sandboxes each holding a psycopg connection, that is 50 connections. At 200+ workers, need connection pooling at the sandbox level (psycopg pool) or accept connection churn.

3. **R2 access from Modal.** Modal sandboxes have outbound network access. R2 is S3-compatible, so boto3 works. But R2 authentication requires Cloudflare API tokens, which need to be passed as Modal Secrets. Latency between Modal's infrastructure and R2 depends on region placement.

4. **Rust core for Pyodide.** The orchestrator runs on Pyodide (WASM). If orchestrator-side code needs Rust functions (e.g., `topo_sort` for scheduling), the Rust crate would need a WASM build in addition to the linux/x86_64 build for Modal. For MVP, keep graph operations in pure Python in the orchestrator and Rust only in sandboxes.

5. **Modal snapshot stability.** Memory snapshots are marked `_experimental`. If the API changes or snapshots become unreliable, fall back to filesystem snapshots (stable) or treat sandboxes as fully ephemeral (like the original CF Containers design).

6. **Merge serialization without Durable Objects.** The orchestrator's `orchestrate` step processes merges sequentially in a loop. If the workflow step times out mid-merge, the step retries and the merge must be idempotent. The merge worker should check `merge_log` before applying to avoid double-merging.
