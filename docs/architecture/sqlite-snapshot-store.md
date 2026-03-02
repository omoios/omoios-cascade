# SQLite SnapshotStore — Implementation Notes

**Date**: 2026-03-01
**Status**: Wired and verified end-to-end

---

## Problem

The multi-agent orchestration harness stored workspace snapshots as `dict[str, str]` (path → file content) in memory. With 7 workers, each spawning a base snapshot of the full repo, memory usage hit 16-20GB. The `snapshot_workspace()` function in `workspace.py` reads every text file into memory and gets called on every worker spawn, handoff, and reconciliation.

## Solution

SQLite-backed `SnapshotStore` with content-addressable deduplication. Files are stored once in a `blobs` table keyed by MD5 hash. 7 workers sharing the same codebase store 1 copy, not 7.

### Schema (3 tables)

```
snapshots        — snapshot_id (PK), workspace_path, created_at, file_count
blobs            — content_hash (PK), content, size
snapshot_files   — (snapshot_id, rel_path) PK, content_hash FK
```

### Key Design Decisions

- **WAL journal mode** for concurrent reads (workers read while planner writes)
- **Sync-only API** — callers wrap with `asyncio.to_thread()` for async
- **Content dedup** via `INSERT OR IGNORE` on content_hash
- **Lazy loading** — `get_content()` fetches one file at a time, never bulk
- **SQL-based diffing** — `changed_files()` compares hashes via JOIN, no content loaded
- **Transient snapshots** cleaned up after merge operations

### Snapshot ID Convention

```
base-{task_id}              — captured at worker spawn
current-{worker_id}         — captured at diff time, deleted after
merge-canonical-{worker_id} — transient, deleted after merge
merge-worker-{worker_id}    — transient, deleted after merge
```

## Files

| File | What Changed |
|------|-------------|
| `src/harness/git/snapshot_store.py` | **NEW** — 272 lines. Full SnapshotStore class. |
| `src/harness/agents/worker.py` | `setup_workspace()` and `get_file_diffs()` use store when available. Legacy in-memory fallback preserved. |
| `src/harness/orchestration/merge.py` | `optimistic_merge()` accepts `snapshot_store` param. Uses store for capture, change detection, per-file content retrieval. Cleans up transient snapshots. |
| `src/harness/runner.py` | `_handle_spawn_worker()` captures via store. `_apply_diffs_to_canonical()` reads base content from store. `_handle_accept_handoff()` deletes base snapshot. Shutdown closes store + cleans orphan blobs. |

## What Still Uses In-Memory Snapshots

- `compute_diff()` in `workspace.py` — only called from tests, not production code
- Tests in `test_git.py`, `test_chaos.py` — call `snapshot_workspace()` and `optimistic_merge()` with dict snapshots directly. These still work via the legacy fallback path.
- `_base_snapshots: dict` still declared in runner.py (line 560) as dead code / legacy fallback

## Verification

- LSP diagnostics: 0 errors on all modified files
- 386 tests pass, 2 skipped, 0 failures
- Full headless harness run completed (exit 0):
  - Planner → task → worker (failed, no diffs) → reject → recovery worker → accept → file written
  - SnapshotStore DB: 32KB at `.workspaces/.harness/snapshots.db`
  - Generated test_main.py passes pytest

## Memory Impact

| Metric | Before (in-memory) | After (SQLite) |
|--------|-------------------|----------------|
| 7-worker base snapshots | 7 × full repo content | 1 × content (deduped blobs) |
| Peak memory for snapshots | ~200MB+ per snapshot | ~96KB metadata in memory |
| Diff computation | Load 2 full snapshots | SQL hash comparison, load changed files only |

## Future Considerations

- The `snapshot_workspace()` function still exists and works — nothing removed, only bypassed in production paths
- Could add snapshot TTL / auto-expiry for long-running sessions
- Could add compression on blob content for further storage savings
- Orphan blob cleanup runs at shutdown; could also run periodically during long sessions
