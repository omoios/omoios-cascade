# Asyncio + PyO3 Migration Plan

Analysis document for making the harness faster. No implementation --- research and planning only.

---

## Current Architecture: Bottleneck Map

The harness runs a planner loop (serial) that spawns worker threads (parallel). Each worker executes an agent loop: call LLM, parse tool use, execute tool, repeat.

### Latency Profile (per worker turn)

```
LLM API call         5,000 - 15,000 ms   (DOMINANT)
subprocess.run bash    100 -  30,000 ms   (tool-dependent)
snapshot_workspace       1 -    500 ms    (scales with file count)
compute_diff             1 -    200 ms    (scales with file count)
File read/write          0 -     10 ms    (negligible for small files)
estimate_tokens          0 -      1 ms    (negligible)
Pydantic serialization   0 -      5 ms    (negligible)
```

The LLM API call is 90%+ of wall time for typical workloads. Everything else is noise unless the repo is large (1000+ files) or bash commands are long-running.

### Threading Model (Current)

```
Main Thread (planner loop)
  |
  +-- daemon Thread (worker-1)  -->  agent loop  -->  blocking client.messages.create()
  +-- daemon Thread (worker-2)  -->  agent loop  -->  blocking client.messages.create()
  +-- daemon Thread (worker-N)  -->  agent loop  -->  blocking client.messages.create()
  |
  EventBus (threading.Lock, sync emit, callbacks inline)
  Signal handler (signal.signal, sets flag + callbacks inline)
```

Workers run in parallel via threads. The GIL is released during I/O (HTTP calls, subprocess, file I/O), so threads achieve real parallelism for the dominant bottleneck (LLM calls). The planner loop is serial --- it processes one tool call at a time.

### Blocking Call Inventory

| Location | Call | Blocking? | Frequency |
|----------|------|-----------|-----------|
| `agents/base.py:100` | `client.messages.create()` | Yes | Every agent turn |
| `runner.py:238` | `client.messages.create()` | Yes | Every planner turn |
| `structured.py:28` | `patched_client.messages.create()` | Yes | Every structured call |
| `tools/worker_tools.py:15` | `subprocess.run(command, shell=True)` | Yes | Every bash tool call |
| `git/workspace.py:26` | `subprocess.run(["git", ...])` | Yes | Workspace creation |
| `git/commit.py:6-34` | `subprocess.run(["git", ...])` | Yes | Commits (3 calls) |
| `orchestration/reconcile.py:33` | `subprocess.run(test_command)` | Yes | Each reconcile round |
| `git/workspace.py:87-103` | `os.walk + open().read()` | Yes | Snapshot (3x per worker) |
| `runner.py:379` | `thread.join(timeout=30)` | Yes | Per handoff review |
| `runner.py:631` | `thread.join(timeout=60)` | Yes | Shutdown |

---

## Phase 1: Asyncio Migration

### 1.1 Why Asyncio

Threading already achieves parallelism for I/O-bound work (GIL releases during HTTP/subprocess/file I/O). The real gains from asyncio are:

1. **Structured concurrency** --- `asyncio.TaskGroup` (Python 3.11+) auto-cancels all workers on first unrecoverable failure. Current daemon threads can silently leak.
2. **Planner parallelism** --- The planner could fire multiple LLM calls concurrently (e.g., evaluate multiple plans simultaneously). Currently impossible with the serial loop.
3. **Cooperative cancellation** --- `CancelledError` propagates cleanly. Current approach sets a flag and hopes threads check it.
4. **No GIL concerns** --- Eliminates the class of bugs where CPU-bound Python code in one thread starves others (relevant when repos are large and snapshot/diff operations become CPU-heavy).
5. **Future pyo3-asyncio integration** --- Rust async functions can be awaited directly from Python when using `pyo3-asyncio`.

### 1.2 Migration Order

Migrate bottom-up: tools first, then agent loop, then orchestrator. Each phase is independently deployable.

#### Phase 1a: Async LLM Client (High Impact, Low Risk)

Replace `anthropic.Anthropic` with `anthropic.AsyncAnthropic`. The SDK provides a drop-in async client.

**Before:**
```python
# agents/base.py
from anthropic import Anthropic

class BaseAgent:
    def __init__(self, config):
        self.client = Anthropic(api_key=config.api_key, base_url=config.base_url)

    def _call_llm(self):
        return self.client.messages.create(**kwargs)

    def run(self):
        while not self._should_stop():
            response = self._call_llm()
            tool_results = self._process_tools(response)
```

**After:**
```python
# agents/base.py
from anthropic import AsyncAnthropic

class BaseAgent:
    def __init__(self, config):
        self.client = AsyncAnthropic(api_key=config.api_key, base_url=config.base_url)

    async def _call_llm(self):
        return await self.client.messages.create(**kwargs)

    async def run(self):
        while not self._should_stop():
            response = await self._call_llm()
            tool_results = await self._process_tools(response)
```

**Files changed:** `agents/base.py`, `agents/planner.py`, `agents/worker.py`, `agents/watchdog.py`, `structured.py`

**Evidence this works:** PydanticAI, browser-use, Google ADK, and Agno all use `AsyncAnthropic` as their production async client.

#### Phase 1b: Async Subprocess (High Impact, Low Risk)

Replace `subprocess.run` with `asyncio.create_subprocess_shell` / `asyncio.create_subprocess_exec`.

**Before:**
```python
# tools/worker_tools.py
result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
```

**After:**
```python
# tools/worker_tools.py
proc = await asyncio.create_subprocess_shell(
    command,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE
)
try:
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
except asyncio.TimeoutError:
    proc.kill()
    await proc.wait()
    raise
```

**Files changed:** `tools/worker_tools.py`, `git/workspace.py`, `git/commit.py`, `orchestration/reconcile.py`

#### Phase 1c: Async File I/O (Medium Impact, Low Risk)

Two options:

**Option A: `asyncio.to_thread` (recommended for this codebase)**
Wraps existing sync file I/O in a thread executor. Zero code change to file operations, just wrap the call site.

```python
content = await asyncio.to_thread(Path(filepath).read_text, encoding="utf-8")
```

**Option B: `aiofiles` library**
Adds a dependency for native async file operations. More idiomatic but overkill for this educational codebase.

```python
async with aiofiles.open(filepath, "r") as f:
    content = await f.read()
```

Recommendation: Option A. File I/O is not the bottleneck, and `to_thread` requires no new dependency.

**Files changed:** `tools/worker_tools.py`, `git/workspace.py`, `orchestration/merge.py`, `orchestration/shutdown.py`, `models/coherence.py`, `runner.py` (_apply_diffs_to_canonical)

#### Phase 1d: Worker Orchestration (High Impact, Medium Risk)

Replace `threading.Thread` + `thread.join` with `asyncio.TaskGroup`.

**Before:**
```python
# runner.py
thread = threading.Thread(target=_run_worker, name=worker_id, daemon=True)
thread.start()
self._threads[worker_id] = thread

# Later:
thread.join(timeout=30)
```

**After:**
```python
# runner.py
async with asyncio.TaskGroup() as tg:
    for worker_id in worker_ids:
        task = tg.create_task(worker.run())
        self._tasks[worker_id] = task

# Timeout on individual worker:
try:
    async with asyncio.timeout(30):
        result = await task
except asyncio.TimeoutError:
    task.cancel()
```

**Benefits:**
- Automatic cancellation of all workers if one raises an unhandled exception
- Clean timeout via `asyncio.timeout()` instead of `thread.join(timeout=)`
- No daemon thread leaks

**Files changed:** `runner.py` (spawn, join, shutdown logic)

#### Phase 1e: Event Bus (Medium Impact, Low Risk)

Replace `threading.Lock` with `asyncio.Lock`. Make emit async or keep sync with `asyncio.Lock`.

**Option A: Async emit (preferred)**
```python
class EventBus:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._callbacks = {}
        self._history = []

    async def emit(self, event: HarnessEvent):
        async with self._lock:
            self._history.append(event)
            for callback in self._callbacks.get(type(event), []):
                await callback(event)  # or fire-and-forget with create_task
```

**Option B: Queue-based (decoupled)**
```python
class EventBus:
    def __init__(self):
        self._queue = asyncio.Queue()

    async def emit(self, event: HarnessEvent):
        await self._queue.put(event)

    async def _dispatcher(self):
        while True:
            event = await self._queue.get()
            for callback in self._callbacks.get(type(event), []):
                await callback(event)
```

Recommendation: Option A for simplicity. Option B if events need to be processed independently of emitters.

**Files changed:** `events.py`, all emit call sites

#### Phase 1f: Signal Handling (Medium Impact, Low Risk)

Replace `signal.signal()` with `loop.add_signal_handler()`.

**Before:**
```python
# orchestration/shutdown.py
signal.signal(signal.SIGINT, _handler)
```

**After:**
```python
# orchestration/shutdown.py
loop = asyncio.get_running_loop()
loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown()))
loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(shutdown()))
```

`asyncio.create_task(shutdown())` is the canonical way to trigger async cleanup from a signal handler. The shutdown coroutine cancels all tasks and waits for them to finish.

**Files changed:** `orchestration/shutdown.py`, `runner.py` (setup)

### 1.3 Async Entry Point

The CLI entry point wraps everything in `asyncio.run()`:

```python
# cli.py
async def async_main(config: HarnessConfig):
    runner = HarnessRunner(config)
    await runner.run()

def main():
    config = load_config()
    asyncio.run(async_main(config))
```

### 1.4 Instructor Integration

The `instructor` library supports async patching:

```python
import instructor
from anthropic import AsyncAnthropic

client = instructor.from_anthropic(AsyncAnthropic())
result = await client.messages.create(
    response_model=MyPydanticModel,
    ...
)
```

No architectural change needed --- just swap the client.

### 1.5 Expected Impact

| Metric | Before (Threading) | After (Asyncio) | Why |
|--------|-------------------|------------------|-----|
| Worker parallelism | Same | Same | Both release GIL during I/O |
| Planner parallelism | Serial only | Can be concurrent | Async enables concurrent LLM calls |
| Cancellation reliability | Flag-based (lossy) | CancelledError (clean) | Structured concurrency |
| Worker leak risk | Daemon threads can leak | TaskGroup prevents leaks | Auto-cancel on exit |
| Signal handling | Interrupt-based (fragile) | Event-loop integrated | Cooperative shutdown |
| Code complexity | Lower (sync is simpler) | Higher (async/await everywhere) | Viral nature of async |

**Honest assessment:** For this educational harness with 1-5 workers, the performance difference between threading and asyncio is negligible. Both achieve the same I/O parallelism. The real value is structural: cleaner cancellation, structured concurrency, and foundation for pyo3-asyncio integration.

---

## Phase 2: PyO3 Acceleration

### 2.1 Why PyO3

Python is slow at CPU-bound work. For large repos (1000+ files), `snapshot_workspace`, `compute_diff`, and `microcompact` become bottlenecks. Rust via PyO3 provides:

1. 10-100x speedup on CPU-bound operations (directory walking, hashing, string comparison)
2. True parallelism via Rayon (no GIL)
3. Zero-copy string borrowing from Python via `&str`
4. Future: native async Rust functions callable from Python asyncio via `pyo3-asyncio`

### 2.2 Priority Targets

Ranked by impact and feasibility:

#### Priority 1: snapshot_workspace (HIGH impact at scale)

**Current:** `os.walk` + `open().read()` for every file. Called 3x per worker lifecycle.

**Why Rust:** `walkdir` crate is significantly faster than `os.walk` due to reduced syscalls. Rayon enables parallel file reads. Release GIL during entire operation.

```rust
use pyo3::prelude::*;
use walkdir::WalkDir;
use rayon::prelude::*;
use std::collections::HashMap;
use std::path::Path;

#[pyfunction]
fn snapshot_workspace(py: Python, root: &str, ignore: Vec<String>) -> PyResult<HashMap<String, String>> {
    py.allow_threads(|| {
        let root_path = Path::new(root);
        let paths: Vec<_> = WalkDir::new(root)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().is_file())
            .filter(|e| {
                let rel = e.path().strip_prefix(root_path).unwrap();
                !ignore.iter().any(|pat| rel.to_string_lossy().contains(pat.as_str()))
            })
            .map(|e| e.into_path())
            .collect();

        let results: HashMap<String, String> = paths.par_iter()
            .filter_map(|path| {
                let content = std::fs::read_to_string(path).ok()?;
                let rel = path.strip_prefix(root_path).ok()?;
                Some((rel.to_string_lossy().into_owned(), content))
            })
            .collect();

        Ok(results)
    })
}
```

**Crates:** `walkdir` (directory traversal), `rayon` (parallel file reads), `ignore` (gitignore support)

**Expected speedup:** 5-10x for repos with 500+ files. Negligible for small repos.

#### Priority 2: compute_diff with MD5 hashing (HIGH impact at scale)

**Current:** Set operations on snapshot keys + `hashlib.md5(content.encode()).hexdigest()` per changed file.

**Why Rust:** MD5 hashing is CPU-bound. Rayon parallelizes across files. The `md-5` crate is SIMD-accelerated.

```rust
use md5;
use rayon::prelude::*;

#[pyfunction]
fn compute_diff(
    py: Python,
    before: HashMap<String, String>,
    after: HashMap<String, String>
) -> PyResult<Vec<FileDiff>> {
    py.allow_threads(|| {
        let all_keys: HashSet<&str> = before.keys().chain(after.keys())
            .map(|k| k.as_str()).collect();

        let diffs: Vec<FileDiff> = all_keys.par_iter()
            .filter_map(|key| {
                match (before.get(*key), after.get(*key)) {
                    (None, Some(content)) => Some(FileDiff::added(key, content)),
                    (Some(_), None) => Some(FileDiff::deleted(key)),
                    (Some(old), Some(new)) => {
                        let old_hash = format!("{:x}", md5::compute(old.as_bytes()));
                        let new_hash = format!("{:x}", md5::compute(new.as_bytes()));
                        if old_hash != new_hash {
                            Some(FileDiff::modified(key, old, new))
                        } else {
                            None
                        }
                    }
                    _ => None,
                }
            })
            .collect();

        Ok(diffs)
    })
}
```

**Crates:** `md-5` (SIMD-accelerated MD5), `rayon`

**Expected speedup:** 3-5x for repos with 100+ changed files. The set operations are already fast; the win is parallel hashing.

#### Priority 3: microcompact / compression (MEDIUM impact, highest CPU density)

**Current:** `deepcopy()` on every message in the compression pipeline. `deepcopy` is notoriously slow in Python --- it traverses the entire object graph, handling circular references and memoization.

**Why Rust:** Message compaction is pure CPU: iterate messages, copy selectively, truncate content. No I/O. Predictable structure (list of dicts with string values).

```rust
#[pyfunction]
fn microcompact(
    py: Python,
    messages: Vec<HashMap<String, PyObject>>,
    keep_recent: usize
) -> PyResult<Vec<HashMap<String, PyObject>>> {
    // Implement message compaction in Rust
    // Avoid Python's deepcopy entirely
    // Key: only copy fields that need modification
}
```

**Challenge:** Messages contain nested Python objects (`content` can be a list of blocks). Crossing the Python/Rust boundary for complex nested structures adds overhead that may negate the deepcopy savings.

**Alternative approach:** Stay in Python but replace `deepcopy` with manual dict construction:
```python
# Instead of:
new_msg = deepcopy(message)
# Use:
new_msg = {"role": message["role"], "content": truncated_content}
```

This Python-only optimization may be sufficient. Profile before porting to Rust.

**Expected speedup:** 5-20x if messages are large. But the Python-only fix (no deepcopy) may get 80% of the gain.

#### Priority 4: Watchdog pattern analysis (LOW impact)

**Current:** `Counter` over activities, nested loops for file counts, `max()` with lambda.

**Why not Rust:** Runs periodically (not per-turn), operates on small data sets (number of workers, not number of files). Python is fast enough.

**Expected speedup:** Not worth the complexity.

#### Priority 5: estimate_tokens (LOW impact)

**Current:** `sum(len(str(msg)) // 4 for msg in messages)`

**Why not Rust:** One-liner. Already O(n). The `str()` conversion dominates, and that happens in Python regardless.

**Expected speedup:** Negligible.

### 2.3 Rust Module Structure

```
src/harness_core/
  Cargo.toml
  src/
    lib.rs              # #[pymodule] entry point
    snapshot.rs          # snapshot_workspace, IGNORE_PATTERNS
    diff.rs              # compute_diff, FileDiff struct
    compress.rs          # microcompact (if profiling justifies it)
```

**Cargo.toml:**
```toml
[package]
name = "harness_core"
version = "0.1.0"
edition = "2021"

[lib]
name = "harness_core"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.22", features = ["extension-module"] }
walkdir = "2.5"
rayon = "1.10"
md-5 = "0.10"
ignore = "0.4"

[profile.release]
lto = true
codegen-units = 1
opt-level = 3
```

**Python integration (pyproject.toml):**
```toml
[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

[tool.maturin]
module-name = "harness_core"
```

**Usage in Python:**
```python
# git/workspace.py
try:
    from harness_core import snapshot_workspace as _rust_snapshot
    from harness_core import compute_diff as _rust_diff
    HAS_RUST = True
except ImportError:
    HAS_RUST = False

def snapshot_workspace(root: str) -> dict[str, str]:
    if HAS_RUST:
        return _rust_snapshot(root, list(IGNORE_PATTERNS))
    # Fallback to pure Python implementation
    ...
```

This pattern (try-import with fallback) keeps the harness functional without compiled Rust, which matters for the educational use case.

### 2.4 Memory Considerations

When passing data between Python and Rust:

| Pattern | Copies | Use When |
|---------|--------|----------|
| `&str` parameter | 0 (borrow) | Read-only access to Python strings |
| `String` parameter | 1 (into Rust) | Need ownership in Rust |
| Return `String` | 1 (into Python) | Returning results |
| `HashMap<String, String>` return | N copies | Returning snapshots (unavoidable) |

**For snapshot_workspace:** The returned `HashMap<String, String>` copies all file contents into Python. This is unavoidable --- Rust reads the files, Python needs the data. The win is parallelism during the read phase, not zero-copy on the return.

**GIL release:** All Rust functions should use `py.allow_threads(|| { ... })` to release the GIL during computation. This lets Python threads (or asyncio tasks) continue while Rust works.

### 2.5 PyO3 + Asyncio Integration

With `pyo3-asyncio`, Rust async functions can be awaited directly from Python:

```rust
use pyo3_asyncio::tokio as pyo3_tokio;

#[pyfunction]
fn async_snapshot(py: Python, root: String) -> PyResult<&PyAny> {
    pyo3_tokio::future_into_py(py, async move {
        let result = tokio::task::spawn_blocking(move || {
            snapshot_workspace_sync(&root)
        }).await.unwrap();
        Ok(result)
    })
}
```

**Python side:**
```python
snapshot = await harness_core.async_snapshot("/path/to/repo")
```

This is the endgame: the harness runs on asyncio, and CPU-heavy Rust operations are awaited natively without `to_thread`.

**Dependency:** `pyo3-asyncio` version `0.20+` with `tokio-runtime` feature.

### 2.6 Expected Impact

| Operation | Python (current) | Rust (projected) | Speedup | When It Matters |
|-----------|-----------------|-------------------|---------|-----------------|
| snapshot_workspace (100 files) | ~50ms | ~5ms | 10x | Always |
| snapshot_workspace (1000 files) | ~500ms | ~30ms | 16x | Large repos |
| compute_diff (100 files) | ~20ms | ~3ms | 7x | Every handoff |
| compute_diff (1000 files) | ~200ms | ~15ms | 13x | Large repos |
| microcompact (100 messages) | ~10ms | ~1ms | 10x | Every compression |
| microcompact (1000 messages) | ~100ms | ~5ms | 20x | Long sessions |

**Honest assessment:** For the educational harness with small repos (10-50 files) and short sessions (10-30 turns), the absolute time savings are milliseconds. The LLM API call (5-15 seconds) dominates regardless. PyO3 becomes meaningful when:
- Repos have 500+ files (snapshot/diff overhead becomes noticeable)
- Sessions run 100+ turns (compression runs frequently with large message histories)
- Multiple harness instances run concurrently (CPU contention matters)

---

## Migration Risks

### Risk 1: Async Virality
**Problem:** `async` infects everything. One async function means all callers must be async.
**Mitigation:** Migrate bottom-up (tools -> agents -> orchestrator). Each phase is a working state.

### Risk 2: PyO3 Build Complexity
**Problem:** Requires Rust toolchain. `maturin` adds build step. CI needs Rust installed.
**Mitigation:** Optional dependency with pure-Python fallback. CI installs Rust only for performance tests.

### Risk 3: Debugging Complexity
**Problem:** Async stack traces are harder to read. Rust panics in PyO3 produce opaque errors.
**Mitigation:** Keep pure-Python fallback for debugging. Use `RUST_BACKTRACE=1` in development.

### Risk 4: Test Suite Changes
**Problem:** All async functions need `pytest-asyncio` or equivalent. Existing 194 tests use sync patterns.
**Mitigation:** Add `pytest-asyncio` dependency. Convert tests incrementally alongside implementation.

### Risk 5: Instructor Library Compatibility
**Problem:** Instructor must support async patching.
**Mitigation:** Instructor supports `from_anthropic(AsyncAnthropic())` natively. Verified in their docs.

---

## Incremental Migration Strategy

### Step 1: Asyncio Foundation (2-3 days)
- Add `pytest-asyncio` to dev dependencies
- Convert `BaseAgent.run()` and `_call_llm()` to async
- Convert tool handlers to async (subprocess, file I/O)
- Keep `runner.py` using `asyncio.to_thread` for worker spawning (hybrid)
- Run existing tests with async wrappers

### Step 2: Full Async Orchestrator (2-3 days)
- Convert `HarnessRunner.run()` to async
- Replace `threading.Thread` with `asyncio.TaskGroup`
- Convert `EventBus` to async
- Convert signal handling to `loop.add_signal_handler`
- Update CLI entry point to `asyncio.run()`

### Step 3: PyO3 Setup (1-2 days)
- Add `maturin` build config
- Implement `snapshot_workspace` in Rust
- Add try-import fallback pattern
- CI: install Rust toolchain

### Step 4: PyO3 Expansion (1-2 days)
- Implement `compute_diff` in Rust
- Profile `microcompact` --- decide if Rust port is justified vs Python-only deepcopy fix
- Wire `pyo3-asyncio` for native async Rust from Python

### Step 5: Validation (1 day)
- Run all 194 tests against async implementation
- Run all 10 tiers against async implementation
- Benchmark: threading baseline vs asyncio vs asyncio+pyo3
- Document results

**Total estimated effort:** 7-11 days for a complete migration.

---

## Dependencies to Add

### For Asyncio (Phase 1)
```toml
# pyproject.toml [project.dependencies]
# anthropic already included --- just use AsyncAnthropic
# No new runtime dependencies needed

# [project.optional-dependencies]
# dev =
pytest-asyncio = ">=0.23"
```

### For PyO3 (Phase 2)
```toml
# pyproject.toml
[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

# Cargo.toml (new file)
[dependencies]
pyo3 = { version = "0.22", features = ["extension-module"] }
walkdir = "2.5"
rayon = "1.10"
md-5 = "0.10"
ignore = "0.4"
pyo3-asyncio = { version = "0.22", features = ["tokio-runtime"], optional = true }
tokio = { version = "1", features = ["rt-multi-thread"], optional = true }
```

---

## Decision Matrix

| Question | Answer | Reasoning |
|----------|--------|-----------|
| Should we migrate to asyncio? | Yes | Structured concurrency, clean cancellation, pyo3-asyncio foundation |
| Should we add pyo3? | Yes, but optional | Real gains at scale, educational value, fallback keeps it accessible |
| Which asyncio phase first? | 1a (async LLM client) | Highest impact, lowest risk, most code stays the same |
| Which pyo3 target first? | snapshot_workspace | Called most frequently, clearest speedup, simplest Rust implementation |
| Should we replace deepcopy with Rust? | Profile first | Python-only fix (manual dict construction) may be sufficient |
| Should we use pyo3-asyncio? | Yes, in Step 4 | Elegant integration, but requires asyncio migration first |
