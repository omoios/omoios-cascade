# s15: Worker Isolation (Per-Worker Workspaces)

> In s15, each worker gets its own repository copy under `.workspaces/{worker_id}`. Workers execute only in their own workspace, produce canonical diffs in handoff, and are cleaned up on completion.

## Why s15 Exists

s14 fixed role confusion with a planner/worker split, but workers still touched the same filesystem.
That means parallel execution can interfere:

- Worker A edits `src/app.py`
- Worker B edits `src/app.py`
- Last write wins
- Neither worker sees true conflict context

s15 adds infrastructure isolation to prevent this entire class of collision.

## Core Idea

```text
Canonical repo (read baseline)
         |
         +--> .workspaces/worker-1/   (private copy)
         +--> .workspaces/worker-2/   (private copy)
         +--> .workspaces/worker-3/   (private copy)

Workers only read/write inside their workspace.
On handoff: diff(workspace, canonical) -> planner review payload.
```

No shared write surface during worker execution.

## Session Constraints

1. Planner still never writes code.
2. Worker still never decomposes/spawns.
3. Worker tool calls are workspace-local only.
4. Handoff diff is computed against canonical repository.
5. Workspace is removed after worker completion.
6. No merge logic in this session (that is s16).

## Worker Workspace Class

`WorkerWorkspace` is the central primitive.

Responsibilities:

- Create private directory at `.workspaces/{worker_id}/`
- Copy canonical repository into worker directory
- Resolve all paths relative to workspace root
- Reject absolute or escaping paths (`..` traversal)
- Execute shell commands with workspace as CWD
- Compute before/after diff against canonical repo
- Cleanup workspace directory

### Create

```python
workspace = WorkerWorkspace(worker_id, canonical_root, workspaces_root)
workspace.create()
```

### Path Safety

```python
resolved = (workspace.path / rel_path).resolve()
if not resolved.is_relative_to(workspace.path):
    raise ValueError("Path escapes worker workspace")
```

This enforces "worker can only access its own workspace."

### Diff on Handoff

Diff is not based on incremental write tracking. Instead, s15 computes final diff from filesystem state:

```python
diff = workspace.compute_diff_against_canonical()
```

This aligns with the architecture reference: worker contribution is the delta between private copy and canonical base.

### Cleanup

After worker loop exits (normal finish or failure path):

```python
workspace.cleanup()
```

Cleanup is explicit and deterministic.

## Tool Behavior Changes

Worker tools remain familiar but their execution surface changed:

- `bash` -> runs in workspace directory
- `read_file` -> reads from workspace only
- `write_file` -> writes to workspace only
- `edit_file` -> edits workspace file only
- `submit_handoff` -> computes canonical diff from workspace
- `rewrite_scratchpad` -> unchanged

Planner tools remain orchestration-only.

## What Planner Receives in Handoff

Handoff now carries workspace provenance:

- `workspace_path`
- `diff` computed against canonical repo
- `status`, `narrative`, `artifacts`, `metrics`

Planner can review the full worker output without any merge happening yet.

## Relationship to Cursor Notes

From `docs/reference/cursor-harness-notes.md` section 9:

- "Each agent receives its own copy of the repository"
- "Modifications are isolated until merge time"

s15 implements this infrastructure layer.
s16 will consume these isolated diffs and introduce optimistic integration behavior.

## What Changed From s14

| Component | s14 | s15 |
|---|---|---|
| Worker write target | canonical repo | private `.workspaces/{worker}` copy |
| Path boundary | repo-root safety | workspace-root safety |
| Diff source | tracked per-write mutations | computed `workspace vs canonical` at handoff |
| Parallel interference | possible | prevented during execution |
| Workspace lifecycle | none | create on spawn, cleanup on completion |

## Non-Goals (Intentional)

- No merge engine
- No conflict resolution worker
- No build verification after apply
- No reconciliation pass

Those are future sessions.

## Operational Notes

- Ignore directories like `.git`, `.workspaces`, caches, and large dependency folders when copying.
- Treat non-text/binary files conservatively in diff (placeholder if unreadable).
- Keep worker errors in runtime state and map unknown failures to `Failed`/`Blocked` status.

## Mental Model

s14 solved **who can do what**.
s15 solves **where they can do it**.

Role isolation + filesystem isolation is what makes parallel worker execution safe enough to scale.

## Try It

```sh
python agents/s15_worker_isolation.py
```

Suggested prompts:

1. `Split this feature into two worker tasks and delegate both.`
2. `Show me all handoffs with diffs and workspace paths.`
3. `List workers and confirm their workspaces were cleaned.`
