# Distributed Sandbox Pool Design

A distributed execution layer for the harness. The harness (Python, running locally or on any host) controls orchestration. Modal Sandboxes execute agent work with memory snapshots for multi-day runs. Neon Postgres coordinates state. Cloudflare R2 provides volume mounts for workspace storage. Performance-critical paths implemented in Rust via PyO3.

Designed for long-horizon runs spanning multiple days.

## Platform Rationale

Each platform handles what it does best:

| Concern | Platform | Why |
|---|---|---|
| Orchestration | Harness (Python process) | The harness you're building. Runs locally or anywhere. Postgres is the durable state — if it crashes, restart and read the database. No platform lock-in. |
| Agent execution | Modal Sandboxes | Sub-second cold starts, memory snapshots for pause/resume across days, Python-first SDK, gVisor isolation, scales to 20,000 concurrent. |
| Merge serialization | Modal Sandbox (dedicated) | Runs git operations that need a full Linux environment. Sequential dispatch via harness. |
| Coordination DB | Neon Postgres (pooled) | Already running. Full Postgres features (JSONB, FOR UPDATE SKIP LOCKED, enums). Sandboxes use the pooled endpoint (PgBouncer, 10K concurrent) to avoid clogging direct connections. |
| Volume storage | Cloudflare R2 (mounted) | Zero egress fees. S3-compatible. Mounted directly into Modal sandboxes via [CloudBucketMount](https://modal.com/docs/guide/cloud-bucket-mounts). No tarball pull/push needed. |
| Real-time dashboard | Modal + FastRTC | WebRTC streaming with <100ms latency for live agent progress. (Post-MVP) |

## Service Mapping

| Harness Concept | Single-Box (current) | Distributed Equivalent |
|---|---|---|
| Task board | In-memory dict | Neon Postgres |
| Handoff store | In-memory dict | Neon Postgres + R2 (metadata in PG, diffs in R2) |
| Agent heartbeats | Thread-local | Neon Postgres rows, polled by harness watchdog loop |
| Repo copies per worker | `.workspaces/worker-*/` | R2 volume mount in Modal sandbox (snapshotable) |
| Canonical repo | `.workspaces/canonical/` | R2 volume mount (shared, writable by merge sandbox only) |
| Merge serialization | Thread lock | Harness dispatches merge sandboxes sequentially |
| Task dispatch | Thread pool | Harness creates Modal sandboxes via SDK |
| Watchdog | Daemon thread | Harness async loop (poll heartbeats, kill stale sandboxes) |
| Orchestrator | Root Planner in main thread | Harness (the package you're building) |
| Worker agent | Thread with own workspace | Modal Sandbox (Python + Rust/PyO3) |

### Database Connectivity

Two access paths to the same Neon Postgres database:

- **Harness (orchestrator)** connects directly to Neon. Single long-lived connection. Uses asyncpg with the direct connection string (`*.neon.tech:5432`).

- **Modal Sandboxes (workers)** connect through Neon's [pooled endpoint](https://neon.com/docs/connect/choose-connection) (`*-pooler.neon.tech:5432`). This goes through Neon's built-in PgBouncer, which handles up to 10,000 concurrent connections. Sandboxes are short-lived and numerous — the pooler prevents them from exhausting direct connection slots.

```
Harness (1 connection)  ──► Neon direct endpoint  ──► Postgres
                                                           ▲
Sandbox 1 ─┐                                               │
Sandbox 2 ─┤── Neon pooled endpoint ── PgBouncer (10K) ────┘
Sandbox N ─┘
```

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│              Harness (Python, runs anywhere)              │
│                                                          │
│  Your orchestrator. Async Python process.                │
│                                                          │
│  1. Decompose: LLM call → task list → INSERT into PG    │
│  2. Dispatch: modal.Sandbox.create() per task            │
│  3. Orchestrate: poll PG for handoffs, merge, watchdog   │
│     Loop until all tasks resolved.                       │
│     Runs for days. Postgres is the durable state.        │
│     If harness crashes: restart, read PG, continue.      │
│  4. Reconcile: test suite sandbox, fixer loop            │
│                                                          │
│  Connects to:                                            │
│  - Neon Postgres (asyncpg, direct)                       │
│  - Modal SDK (sandbox create/terminate/snapshot)         │
│  - R2 (boto3, for config and patch metadata)             │
└──────────┬───────────────────────────────────────────────┘
           │ Modal Python SDK
     ┌─────┴─────┬───────────┬───────────┐
     ▼           ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Modal   │ │  Modal   │ │  Modal   │ │  Modal   │
│ Sandbox  │ │ Sandbox  │ │ Sandbox  │ │ Sandbox  │
│ (worker) │ │ (worker) │ │ (worker) │ │ (merge)  │
│          │ │          │ │          │ │          │
│ R2 mount │ │ R2 mount │ │ R2 mount │ │ R2 mount │
│ /vol     │ │ /vol     │ │ /vol     │ │ /vol     │
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
│  (harness via direct | sandboxes via pooled/PgBouncer)│
│  tasks | handoffs | agents | merge_log               │
└──────────────────────────────────────────────────────┘
           │                                 │
           ▼                                 ▼
┌──────────────────────────────────────────────────────┐
│                    Cloudflare R2                      │
│  Mounted into sandboxes via CloudBucketMount         │
│  volumes/{project}/canonical/                        │
│  volumes/{project}/workers/{sandbox_id}/             │
│  patches/{project}/{handoff_id}.patch                │
└──────────────────────────────────────────────────────┘
```

## Postgres Schema (Neon)

Single Neon Postgres database. Harness connects directly (asyncpg). Modal Sandboxes connect through the pooled endpoint (PgBouncer, up to 10K concurrent).

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
    'starting', 'active', 'completed', 'failed', 'killed', 'paused'
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

## R2 Volume Mounts

R2 is mounted directly into Modal sandboxes via [CloudBucketMount](https://modal.com/docs/guide/cloud-bucket-mounts). No tarball pull/push — sandboxes read and write files on the R2 mount as if they were local disk. Zero egress fees make this practical even for large repos.

```python
r2_secret = modal.Secret.from_name("r2-credentials")
# Contains: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
# (R2 uses S3-compatible auth)

r2_mount = modal.CloudBucketMount(
    bucket_name="harness-pool",
    bucket_endpoint_url="https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
    secret=r2_secret,
)

# Mount into sandbox at /vol
sb = modal.Sandbox.create(
    "python", "-m", "harness.sandbox_worker",
    image=worker_image,
    cloud_bucket_mounts={"/vol": r2_mount},
    timeout=300,
)
# Sandbox sees /vol/volumes/{project}/canonical/ as a local directory
```

### R2 Layout

```
harness-pool/                              # R2 bucket
├── volumes/
│   └── {project_id}/
│       ├── canonical/                     # current canonical repo (live directory, not tarball)
│       └── snapshots/
│           └── {sha}/                     # point-in-time snapshots (green branches)
├── patches/
│   └── {project_id}/
│       └── {handoff_id}.patch             # git-format patches from workers
├── artifacts/
│   └── {handoff_id}/
│       └── ...                            # build outputs, logs, generated files
└── config/
    └── {project_id}.json                  # project-level config (repos, branches, limits)
```

With CloudBucketMount, canonical is a live directory on R2 — not a tarball. The merge sandbox writes directly to `volumes/{project}/canonical/` on the mount. Worker sandboxes read from it at startup to copy into their local workspace (workers write to local disk, not to the R2 mount, to avoid write contention).

Snapshots are full copies of canonical at green-branch points. Cheap to store on R2 (zero egress, $0.015/GB/month).

## Orchestration (Harness)

The harness is the orchestrator. It's the Python package you're building (`src/harness/`). It runs as a long-lived async Python process — locally, on a VM, wherever. Postgres is the durable state. If the harness crashes, restart it and it picks up from the database.

```python
import asyncio
import asyncpg
import modal

async def run_harness(instruction: str, project_id: str):
    pool = await asyncpg.create_pool(NEON_DIRECT_URL)

    # 1. Decompose
    tasks = await llm_decompose(instruction, project_id)
    await db_insert_tasks(pool, tasks)

    # 2. Dispatch
    for task in tasks:
        sb = modal.Sandbox.create(
            "python", "-m", "harness.sandbox_worker",
            image=worker_image,
            cloud_bucket_mounts={"/vol": r2_mount},
            secrets=[modal.Secret.from_name("harness-secrets")],
            timeout=300,
            _experimental_enable_snapshot=True,
        )
        await db_assign_task(pool, task["id"], sb.object_id)

    # 3. Orchestrate (runs for hours/days)
    while True:
        # Merge completed handoffs
        handoffs = await db_pending_handoffs(pool, project_id)
        for h in handoffs:
            await dispatch_merge(h)

        # Watchdog: kill stale sandboxes, snapshot idle ones
        stale = await db_stale_agents(pool)
        for agent in stale:
            sb = modal.Sandbox.from_id(agent["sandbox_id"])
            sb.terminate()
            await db_requeue_task(pool, agent["task_id"])

        # Check completion
        remaining = await db_incomplete_tasks(pool, project_id)
        if not remaining:
            break

        await asyncio.sleep(10)

    # 4. Reconcile
    await run_reconciliation(pool, project_id)

    await pool.close()
```

### Why Not a Managed Workflow Service

The harness needs to run for **days**. CF Workflows, Temporal, and similar platforms have execution time limits and add complexity for what is fundamentally a polling loop. Postgres is already the durable state — every task, handoff, and agent status is persisted. If the harness process dies:

1. Restart the harness
2. It reads the task board from Postgres
3. It reconnects to running sandboxes via their IDs (stored in Postgres)
4. It continues the orchestration loop

No checkpointing framework needed. The database IS the checkpoint.

### API Surface (Optional)

The harness can optionally expose an HTTP API for external control:

```
POST /projects/{id}/run     -- start a run
GET  /projects/{id}/status  -- current task board + active sandboxes
POST /projects/{id}/cancel  -- cancel run, terminate all sandboxes
GET  /handoffs/{id}         -- read handoff with narrative
```

This is not required for MVP — the harness can run as a CLI tool.

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
  2. Connect to Neon Postgres via pooled endpoint (asyncpg + PgBouncer)
  3. Read task spec from tasks table
  4. Copy canonical from R2 mount (/vol/volumes/{project}/canonical/) → /work
     (local copy for isolated modifications)

Sandbox execution:
  5. Agent loop: LLM calls → tool use → file modifications on /work
  6. Heartbeat: UPDATE agents SET heartbeat_at=now() every 15 seconds

Sandbox completion:
  7. Generate patch: harness_core.diff_trees(/vol/.../canonical, /work) → patch bytes
  8. Write patch to R2 mount: /vol/patches/{project}/{handoff_id}.patch
  9. INSERT handoff row (narrative, metrics, diff_path)
  10. UPDATE task status to 'completed'
  11. Exit (sandbox terminates) or snapshot if pausing
```

### Memory Snapshots (Multi-Day Runs)

For runs spanning multiple days, memory snapshots are essential. A sandbox's entire state — memory, filesystem, running processes — can be snapshotted and later restored as a new sandbox. This is how agents survive across days without losing context.

```python
# End of day / idle timeout: snapshot the agent
sb = modal.Sandbox.from_id(sandbox_id)
snapshot = sb._experimental_snapshot()
await db_update_agent(agent_id, snapshot_id=snapshot.object_id, status="paused")

# Next day / work available: resume from snapshot
snapshot = modal.SandboxSnapshot.from_id(snapshot_id)
sb = snapshot.restore(timeout=300)
await db_update_agent(agent_id, sandbox_id=sb.object_id, status="active")
```

This enables:
- **Multi-day agents.** Agents that exceed Modal's 24-hour sandbox limit get snapshotted and restored into fresh sandboxes with full state preserved. The agent doesn't know it was paused.
- **Cost savings.** Pause idle sandboxes instead of keeping them running. Resume only when the harness has work for them.
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
    cloud_bucket_mounts={"/vol": r2_mount},
    timeout=300,
)
```

### Merge Sandbox

A dedicated sandbox type that only handles merge operations:

```
Sandbox startup:
  1. Read environment: HANDOFF_ID, PATCH_KEY, PROJECT_ID
  2. Connect to Neon Postgres via pooled endpoint
  3. Read canonical from R2 mount: /vol/volumes/{project}/canonical/
  4. Read patch from R2 mount: /vol/patches/{project}/{handoff_id}.patch

Merge execution:
  5. Apply patch: harness_core.patch_apply(canonical_path, patch_bytes)
  6. If conflict → INSERT merge_log(result='conflict', details=...), exit
  7. If clean → run build/test command (from project config)
  8. If build fails → INSERT merge_log(result='build_fail', details=...), exit
  9. If green → write updated files to R2 mount canonical directory
  10. INSERT merge_log(result='clean', canonical_sha=new_sha)
  11. Exit
```

Merges are sequential by design — the harness dispatches one merge sandbox at a time.

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

Three layers of parallelism, each handling a different concern:

```
┌─────────────────────────────────────────────────────────┐
│                      asyncio                             │
│  (top-level event loop in harness + each sandbox)        │
│                                                          │
│  All network I/O is async:                               │
│  - LLM API calls (httpx / anthropic async client)        │
│  - Postgres queries (asyncpg)                            │
│  - R2 operations (aioboto3 or via mount)                 │
│  - Modal SDK calls (sandbox create/terminate/snapshot)   │
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
```

Note: `multiprocessing` is not needed. Modal provides process isolation across machines. No local process pools required.

### How They Compose

**Inside the harness (orchestrator):**
- asyncio event loop handles all I/O (Postgres, Modal SDK, LLM calls for decomposition)
- No threads or processes needed — the harness is pure I/O
- Runs for days; the event loop just keeps polling

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

        # Write patch to R2 mount (local filesystem write via CloudBucketMount)
        Path("/vol/patches/{project}/{handoff_id}.patch").write_bytes(patch)

async def heartbeat_loop(agent_id: str):
    while True:
        await asyncpg_pool.execute(
            "UPDATE agents SET heartbeat_at=now(), tokens_used=$1 WHERE id=$2",
            token_count, agent_id
        )
        await asyncio.sleep(15)

async def main():
    # Sandboxes use pooled endpoint to avoid clogging direct connections
    async with asyncpg.create_pool(NEON_POOLED_URL) as pool:
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

Each Modal sandbox runs one coding agent with an ACP-compatible interface. The harness dispatches tasks to sandboxes the same way it does for custom workers — the only difference is what runs inside the sandbox.

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

The minimum viable system that proves the distributed loop works end-to-end. The harness controls everything.

### MVP Scope

```
Harness (Python, local)
  - Async Python process: decompose → dispatch → orchestrate → done
  - Decomposes instruction into 3-5 leaf tasks
  - Flat task list, no recursive hierarchy
  - Single LLM call for decomposition
  - Sequential merge dispatch
  - Zombie-only watchdog (heartbeat staleness check)
  - Connects to Neon direct, Modal SDK, R2 via boto3

Neon Postgres
  - tasks + handoffs + agents tables
  - Harness: direct connection (asyncpg)
  - Sandboxes: pooled endpoint (PgBouncer, up to 10K)

Cloudflare R2
  - CloudBucketMount into sandboxes at /vol
  - volumes/{project}/canonical/ (live directory)
  - patches/{project}/{handoff_id}.patch

Modal Sandboxes
  - Worker sandboxes: Python agent loop, R2 mount, no scratchpad
  - Copy canonical from /vol mount to /work, do work, write patch to /vol
  - Heartbeat every 15s (asyncpg, pooled endpoint)
  - No memory snapshots yet (sandboxes run to completion)

Rust Core
  - diff_trees + patch_apply + hash_tree only
  - Other functions stay Python until profiling shows need
```

### MVP Does NOT Include

- Memory snapshots (sandboxes run to completion for MVP)
- Reconciliation pass (test suite, fixer loop)
- Scratchpad rewriting or context compression
- Multi-project support
- Warm pools
- Error budgets or tunnel-vision detection
- Real-time dashboard / WebRTC streaming
- ACP / layering other agents

### MVP File Structure

```
src/harness/                           # The harness package (orchestrator + worker code)
├── __init__.py
├── config.py                          # pydantic-settings: config from .env
├── orchestrator.py                    # Main async loop (decompose, dispatch, orchestrate)
├── sandbox_worker.py                  # Worker sandbox entrypoint (runs in Modal)
├── merge_worker.py                    # Merge sandbox entrypoint (runs in Modal)
├── agent_loop.py                      # Core agent loop (LLM + tools)
├── tools.py                           # bash, read, write, edit
├── db.py                              # asyncpg queries (pooled + direct)
├── r2_client.py                       # R2 mount helpers + boto3 fallback
├── modal_app.py                       # Modal image definitions + sandbox helpers
├── models/
│   ├── task.py                        # Task, TaskStatus
│   ├── handoff.py                     # Handoff, HandoffMetrics
│   └── agent.py                       # AgentState, AgentConfig
└── cli.py                             # CLI entrypoint (click or typer)

harness-core/                          # Rust crate (PyO3)
├── Cargo.toml
├── pyproject.toml                     # maturin config
└── src/
    ├── lib.rs
    ├── patch.rs
    └── hash.rs

schema.sql                             # Postgres schema (Neon)
```

## Scaling Path (Post-MVP)

Once the MVP works end-to-end with flat task decomposition and sequential merge:

**Phase 1: Memory Snapshots.** Enable `_experimental_enable_snapshot` on worker sandboxes. Snapshot idle agents instead of killing them. Snapshot agents at end-of-day for multi-day continuity. Maintain a warm pool of pre-snapshotted sandboxes for near-instant dispatch.

**Phase 2: Reconciliation.** After all tasks complete, run the reconciliation step: pull canonical from R2 mount, run full test suite in a sandbox, parse failures, spawn targeted fixer tasks. Hard cap of 3 fixer rounds.

**Phase 3: Coherence.** Add scratchpad rewriting, context compression, and state reconstruction for long-running agents. Use memory snapshots to persist agent state across compression events. Add error budgets and tunnel-vision detection to the watchdog.

**Phase 4: ACP Integration.** Layer existing agents (Claude Code, Codex, goose) as alternative workers via Agent Client Protocol wrappers. Route tasks to the best agent for each task type.

**Phase 5: Real-Time Dashboard.** WebRTC streaming via Modal FastRTC for live agent progress. Browser-based dashboard showing task board, active sandboxes, and streaming agent output.

## Cost Model (Rough Estimates)

Based on current pricing for a 50-task run (single day):

| Resource | Usage | Cost |
|---|---|---|
| Neon Postgres | ~5,000 queries, ~50 MB storage | Free tier or ~$0.10 on Scale |
| R2 storage | ~500 MB (canonical + patches + snapshots) | ~$0.0075 |
| R2 operations | ~200 Class A + ~500 Class B | ~$0.001 |
| Modal Sandboxes | 50 workers x ~2 min each = 100 min CPU | ~$0.16 (at $0.047/vCPU-hr) |
| Modal Merge | ~50 merges x ~30s each = 25 min CPU | ~$0.02 |
| Anthropic API | 50 agent runs + decomposition | Dominant cost |

**Total infrastructure: ~$0.20 per 50-task run** (excluding LLM costs).

For multi-day runs, Modal costs scale linearly with active sandbox time. Snapshotted (paused) sandboxes cost nothing. The dominant cost remains LLM API calls.

Since you already have a Neon instance, the database cost is effectively zero.

## Open Questions

1. **R2 CloudBucketMount write performance.** CloudBucketMount uses FUSE under the hood. Write performance may be slower than local disk for small random writes (which agents do a lot). If this is a problem, workers should copy canonical from the mount to local disk at startup (`cp -r /vol/.../canonical/ /work/`), work on local disk, then write the patch back to the mount. The merge sandbox may need the same pattern.

2. **Neon connection limits at scale.** The pooled endpoint handles up to 10K concurrent connections. For MVP (50 sandboxes), this is fine. At 200+ concurrent sandboxes with frequent heartbeat writes (every 15s), monitor PgBouncer saturation. If needed, batch heartbeat writes or reduce frequency.

3. **R2 auth in Modal.** R2 authentication requires Cloudflare API tokens passed as Modal Secrets. The CloudBucketMount uses S3-compatible auth (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` mapped to R2 tokens). Needs to be set up once in Modal's secret store.

4. **Modal snapshot stability.** Memory snapshots are marked `_experimental`. If the API changes or snapshots become unreliable, fall back to filesystem snapshots (stable) or treat sandboxes as fully ephemeral and rely on R2 + Postgres for all state recovery.

5. **Multi-day snapshot management.** For runs spanning days, snapshots accumulate. Need a retention policy: keep latest snapshot per agent, delete older ones after 7 days. Modal's snapshot retention limits (30 days for directory snapshots) may also apply.

6. **Merge idempotency.** If the harness crashes mid-merge-dispatch, restarting may attempt the same merge again. The merge worker should check `merge_log` before applying to avoid double-merging. The handoff's `merge_status` field prevents this at the database level.
