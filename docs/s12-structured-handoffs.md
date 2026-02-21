# s12: Structured Handoffs

> Workers do not finish silently. They submit structured handoffs with diff, narrative, status, artifacts, and metrics so leads can reason about outcomes without rereading full worker history.

## The Problem

In s11, autonomous workers can claim and execute work, but completion is weakly communicated.
A worker can finish and stop talking, leaving the lead with low visibility:

- What changed?
- Did the worker fail partially or fully?
- What was blocked?
- How much effort was spent?
- What should happen next?

Without a structured completion protocol, coordination quality drops as team size grows.

## The Solution

Workers produce a **Handoff** object at task completion. A handoff is the minimum complete report for upward communication.

```text
Worker lifecycle with handoff:

+------------------+
| claim / execute  |
+--------+---------+
         |
         v
+------------------+
| track file diffs |
| (before / after) |
+--------+---------+
         |
         v
+------------------+
| final narrative  |
| LLM composition  |
+--------+---------+
         |
         v
+------------------+
| submit_handoff   |
| -> lead inbox    |
+--------+---------+
         |
         v
+------------------+
| review_handoff   |
| lead reads       |
+------------------+
```

## Handoff Schema

The worker sends this exact structure:

```python
{
  agent_id: str,
  task_id: str,
  status: Success | PartialFailure | Failed | Blocked,
  diff: {
    filepath: {
      before: str,
      after: str,
    }
  },
  narrative: str,
  artifacts: list[str],
  metrics: {
    wall_time: float,
    tokens_used: int,
    attempts: int,
    files_modified: int,
  }
}
```

## How It Works

1. Worker runtime state tracks task metadata:
   - `task_id`
   - `start_time`
   - `attempts`
   - `tokens_used`
   - `diff`
   - `artifacts`

2. `write_file` and `edit_file` are tracked:
   - capture `before`
   - apply write/edit
   - capture `after`
   - store in `diff[path]`

3. Completion path:
   - explicit: worker calls `submit_handoff`
   - automatic: if worker exits without submission, system auto-submits

4. Narrative composition:
   - one final LLM call creates concise narrative
   - includes what changed, what did not, risks, next step

5. Delivery:
   - handoff is appended to in-memory handoff store
   - handoff is pushed to lead inbox as `type: "handoff"`

6. Lead inspection:
   - `review_handoff` filters by task or agent
   - returns narrative-centered summaries (optionally include full diff)

## New Tools

### Worker Tool: `submit_handoff`

Purpose: send structured completion packet to lead.

Inputs:

- `task_id` (optional override)
- `status` (optional explicit status)
- `narrative` (optional override; otherwise LLM-composed)
- `artifacts` (optional extras)

Output:

- confirmation string including task id and status

### Lead Tool: `review_handoff`

Purpose: inspect submitted handoffs and narratives.

Inputs:

- `task_id` (optional)
- `agent_id` (optional)
- `include_diff` (optional bool)

Output:

- JSON array with status, narrative, artifacts, metrics, and optional diff

## Status Semantics

- `Success`: intended change completed
- `PartialFailure`: some outputs produced, but errors or incomplete scope
- `Failed`: no usable output due to execution failure
- `Blocked`: progress blocked by missing prerequisites or hard constraints

## Key Code Paths

- `Handoff`, `HandoffMetrics`, `HandoffStatus` dataclasses
- tracked write/edit instrumentation for file-based diff capture
- `_compose_handoff_narrative(...)` final narrative call
- `_submit_handoff(...)` pack + send to lead inbox
- `review_handoffs(...)` lead review API
- worker `_loop(...)` auto-submission fallback

## What Changed From s11

| Component | s11 | s12 |
|---|---|---|
| Completion reporting | implicit | structured handoff |
| Diff capture | none | per-file before/after |
| Narrative | ad hoc | required final narrative |
| Metrics | limited | wall_time, tokens, attempts, files_modified |
| Lead inspection | inbox only | `review_handoff` tool |

## Constraints and Non-Goals

- No merge logic in this session
- No planner role split in this session
- No git-based diffing; diff is file-state tracking only
- Lead reads handoffs but does not reconcile or merge competing worker edits

## Production Reference

This handoff mechanism mirrors Cursor's production architecture (see `docs/reference/cursor-harness-notes.md`):

> "The narrative is not optional metadata. It is the primary mechanism for propagating understanding up the hierarchy."

Cursor achieves ~100:1 compression at the worker layer by sending a narrative + diff instead of full work context. This enables hierarchical teams to scale:

| Layer       | Input                        | Output                    | Ratio   |
|-------------|------------------------------|---------------------------|---------|
| Worker      | Full work context + diffs   | Handoff narrative + diff  | ~100:1  |
| SubPlanner  | N worker handoffs           | Aggregate narrative       | ~20:1   |
| Root        | N SubPlanner handoffs       | Final status + summary   | ~10:1   |

The production system also uses the `status` field for automated decision-making and metrics for cost attribution.

## Production Direction

This mechanism is the first building block for hierarchical orchestration:

- Workers send compressed truth upward
- Leads reason over narratives and metrics, not raw full context
- Future sessions can aggregate handoffs recursively and add optimistic merge/reconciliation

## Try It

```sh
python agents/s12_structured_handoffs.py
```

Example prompts:

1. `Spawn worker alpha. Ask it to claim a task, edit a file, and submit_handoff.`
2. `Have worker submit_handoff with PartialFailure and explain remaining work.`
3. `Use review_handoff with include_diff=true to inspect all worker narratives.`
