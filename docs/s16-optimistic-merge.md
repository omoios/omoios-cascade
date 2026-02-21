# s16: Optimistic Merge Strategy (Fix-Forward, Never Revert)

> In s16, workers still run in isolated workspaces, but now planner can integrate worker output into canonical repo using a file-based 3-way merge. If conflicts appear, the system creates fix-forward tasks and keeps moving. It does not revert.

## Why s16 Exists

s15 solved workspace interference by isolating workers in `.workspaces/{worker}`.
That prevents active collisions during execution, but it does not answer the integration question:

- How do we merge worker output back into canonical state?
- What if canonical changed after worker spawn?
- What if both worker and canonical edited the same file differently?

s16 introduces an **optimistic merge** strategy for that exact phase.

## Core Principle

From `docs/reference/cursor-harness-notes.md` section 6:

- "DO NOT REVERT. The repo may be broken. This is by design."

That rule is not rhetorical. It shapes all merge behavior in this session.

## Mental Model

```text
base snapshot (worker spawn)
       |
       +--> worker workspace (ours)
       |
       +--> canonical repo keeps changing (theirs)

on handoff:
  3-way merge(base, ours, theirs)

if clean: apply
if conflict: apply clean subset + create fix-forward task
never: revert canonical
```

This is optimistic because we assume most files merge cleanly.

## What Is New vs s15

| Area | s15 | s16 |
|---|---|---|
| Worker output | Handoff only | Handoff + merge attempt |
| Merge engine | none | file-based 3-way merge |
| Conflict handling | not applicable | fix-forward task creation |
| Failure policy | n/a | no revert, continue forward |
| Observability | handoffs | handoffs + merge logs + fix tasks |

## Merge Inputs

Each merge uses three snapshots:

1. `base` - worker snapshot at spawn time
2. `ours` - worker workspace state at handoff
3. `theirs` - current canonical repo at merge time

All snapshots are file-path maps (`path -> content`) from filesystem reads.
No git commands are used.

## 3-Way Merge Rules

For each file path in union(base, ours, theirs):

1. If `ours == base` -> worker did not change file; keep canonical.
2. If `theirs == base` -> canonical unchanged since spawn; apply worker version.
3. If `ours == theirs` -> same final value; no action needed.
4. Otherwise -> conflict.

Deletion is represented as missing file (or `None` in snapshot state), so add/update/delete all flow through the same rules.

## optimistic_merge() Behavior

Planner calls `optimistic_merge` on a selected handoff.

High-level flow:

1. Resolve target handoff (`handoff_id`, or `task_id`, or `agent_id`).
2. Load `base`, `ours`, and `theirs` snapshots.
3. Compute file-level merge decisions.
4. Apply non-conflicting updates to canonical repo.
5. If conflicts exist, create fix-forward task payload with `base/ours/theirs` text for each conflict.
6. Write merge log entry.
7. Mark handoff merged with merge status.

Return payload includes:

- merge status
- applied files
- conflicted files
- optional fix task id
- note reminding no revert policy

## Conflict Strategy: Fix-Forward Tasks

On conflict, s16 **does not rollback** applied files.
It creates a structured fix-forward task:

- source handoff id / worker / task
- human-readable title + description
- full conflict map with `base`, `ours`, `theirs`
- status (`pending`)

Fix tasks are stored and queryable through planner tooling:

- `list_fix_tasks`

A message is also emitted to planner inbox for visibility.

## Merge Log

Every merge attempt is logged to support debugging and audit:

- `log_id`, timestamp
- handoff metadata
- merge status (`Applied`, `Conflict`, `NoChanges`)
- attempted file count
- applied files
- conflicted files
- unchanged files
- fix task id (if any)
- explanatory note

Planner can inspect history via:

- `read_merge_log`

## Session Tooling

Planner tools in s16:

- `spawn_worker`
- `review_handoff`
- `optimistic_merge`
- `list_fix_tasks`
- `read_merge_log`
- `rewrite_scratchpad`
- `send_message`
- `read_inbox`
- `list_workers`

Worker tools remain workspace-local:

- `bash`
- `read_file`
- `write_file`
- `edit_file`
- `submit_handoff`
- `rewrite_scratchpad`

## Guarantees and Non-Goals

### Guarantees

- Merge logic is file-based (no git dependency).
- Worker edits are computed relative to worker base snapshot.
- Conflicts generate actionable follow-up tasks.
- Canonical repo is never auto-reverted by merge subsystem.

### Non-Goals

- Semantic merge understanding
- AST-aware conflict resolution
- automatic build break repair
- full reconciliation pass across all handoffs

Those are future layers.

## Why This Scales Better Than Revert-First

Revert-first workflows protect short-term cleanliness but destroy throughput under concurrency:

- one conflict can erase valid independent edits
- repeated retries can thrash the same files
- planner spends cycles restoring state instead of progressing

Fix-forward preserves progress while making conflicts explicit and routable.

## Operational Notes

- Merge can apply a clean subset even when some files conflict.
- Conflict payloads should be small but complete enough for a repair worker.
- Merge logs are first-class debugging artifacts, not optional metadata.
- If canonical gets temporarily broken, that is acceptable in this session model.

## Try It

```sh
python agents/s16_optimistic_merge.py
```

Suggested prompts:

1. `Delegate one worker to edit README.md and submit handoff, then run optimistic_merge.`
2. `Run two workers that both touch the same file, then merge one and merge the other.`
3. `Show fix-forward tasks and merge logs after conflict.`

## Key Takeaway

s15 solved **execution isolation**.
s16 adds **integration strategy under concurrency**.

The important pattern is not "always clean merge".
The pattern is:

- merge optimistically,
- detect conflicts cheaply,
- create repair work,
- never throw away forward progress.
