# s14: Planner-Worker Split

> In s14 we enforce role separation: planners think and delegate, workers execute and hand off. This is the V5 -> V6 lesson from Cursor's harness evolution.

## The Problem

In s11-s13, one agent can still drift across too many responsibilities:

- It plans and executes in the same context.
- It may avoid delegation and "just do it itself".
- It may claim completion without clear worker-level proof.
- It can confuse coordination with implementation.

Cursor's V5 notes describe this failure mode directly: too many roles in one agent created pathological behavior.

## The Solution

Split role identity at both layers:

1. Tool surface (hard constraint)
2. System prompt (behavioral constraint)

```text
Planner lane (thinking + delegation)          Worker lane (execution)

+-------------------------------+             +-------------------------------+
| PLANNER                       |             | WORKER                        |
|-------------------------------|             |-------------------------------|
| spawn_worker                  |             | bash                          |
| review_handoff                |             | read_file                     |
| rewrite_scratchpad            |             | write_file                    |
| send_message                  |             | edit_file                     |
| read_inbox                    |             | submit_handoff                |
| list_workers                  |             | rewrite_scratchpad            |
+-------------------------------+             +-------------------------------+
| NO bash/write/edit            |             | NO spawn_worker               |
| NEVER writes code             |             | NEVER decomposes              |
+-------------------------------+             +-------------------------------+
```

This is not preference-based guidance. It is enforced by which tools each role can call.

## How It Works

1. Planner receives user goal and decomposes into worker-sized tasks.
2. Planner calls `spawn_worker` for each concrete task.
3. Each worker runs in fresh context with worker-only tools and worker-only system prompt.
4. Worker writes/edits files, then calls `submit_handoff`.
5. Planner reads handoffs via `read_inbox` / `review_handoff` and updates planner scratchpad.
6. Planner decides next wave: spawn more workers, request retries, or report completion.

## Key Code

### Planner prompt constraint

```python
PLANNER_SYSTEM = (
    "You decompose and delegate. You NEVER write code. "
    "If you want to touch files or run shell commands, spawn a worker instead."
)
```

### Worker prompt constraint

```python
WORKER_SYSTEM_TEMPLATE = (
    "You execute a single assigned task. Write code and submit a handoff when done. "
    "You do NOT decompose or delegate. You do NOT spawn workers."
)
```

### Tool-level separation

```python
def _planner_tools(self):
    return [spawn_worker, review_handoff, rewrite_scratchpad,
            send_message, read_inbox, list_workers]

def _worker_tools(self):
    return [bash, read_file, write_file, edit_file,
            submit_handoff, rewrite_scratchpad]
```

### Fresh worker context on spawn

```python
def spawn_worker(self, task, name=None, task_id=None):
    # new runtime
    # new scratchpad
    # dedicated worker thread
```

Workers do not inherit planner conversation history. They begin from assignment + worker constraints.

## What Changed From s13

| Component | s13 | s14 |
|---|---|---|
| Primary role model | mixed lead/worker behavior | strict Planner vs Worker types |
| Planner tools | includes execution-capable tools in lead flow | no file/shell tools |
| Worker tools | broad teammate/coordination tools | execution-only + submit_handoff |
| Spawn semantics | teammate spawn with generic role | `spawn_worker` with worker prompt + fresh context |
| Constraint enforcement | mainly prompt + convention | prompt + tool-level hard boundary |

## Tool Surface

### Planner tools

- `spawn_worker`
- `review_handoff`
- `rewrite_scratchpad`
- `send_message`
- `read_inbox`
- `list_workers`

### Worker tools

- `bash`
- `read_file`
- `write_file`
- `edit_file`
- `submit_handoff`
- `rewrite_scratchpad`

## Why Tool Separation Matters

Prompt-only constraints fail under pressure. When context is noisy, models may violate soft rules.

Tool-level separation prevents that category of error:

- Planner physically cannot run code tools.
- Worker physically cannot spawn/decompose via planner tools.

This aligns with Cursor's "constraints > instructions" prompt principle.

## Handoff Flow

```text
Worker executes task
    -> tracks diff + artifacts + errors
    -> submit_handoff
    -> planner inbox receives {handoff}
    -> planner reviews narrative and decides next step
```

s14 keeps the s12 structured handoff format and s13 scratchpad rewriting behavior, but applies them inside split roles.

## Production Reference

From `docs/reference/cursor-harness-notes.md`:

- Section 2 (V5 failure): "too many roles for one agent" caused dysfunction.
- Section 4 (Agent Roles): planner decompose/delegate, worker execute.
- Section 7 (Prompt Engineering): constraints are stronger than suggestions.
- Session mapping table: s14 is explicitly Planner-Worker split.

This session is the architectural hinge from a flat team to a scalable harness.

## Constraints and Non-Goals

- No recursive SubPlanner hierarchy yet (that is s17).
- No merge/reconciliation logic yet (s16+s20).
- No real git integration (file-based diffs only).
- Planner does not apply diffs; it reviews handoffs and delegates follow-up work.

## Try It

```sh
python agents/s14_planner_worker_split.py
```

Suggested prompts:

1. `Break this feature into 3 worker tasks and delegate each one.`
2. `Review all handoffs and tell me which worker needs retry.`
3. `Update planner scratchpad with unresolved tasks only.`
4. `Send a direct message to worker-1 to limit scope to tests.`
