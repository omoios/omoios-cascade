# s13: Scratchpad Rewriting

> Long-running workers need freshness controls. In s13, every agent keeps a file-based scratchpad that is rewritten (not appended), plus auto-summarization at 80% context capacity, periodic self-reflection, and role re-alignment after compression.

## The Problem

s12 added structured handoffs, but long-running agents still drift over time:

- Context accumulates stale details.
- Compression can remove role constraints.
- Agents keep repeating weak strategies.
- Important local state gets buried in old messages.

If freshness is unmanaged, agents stay "busy" but lose coherence.

## The Solution

Each agent gets a persistent scratchpad file:

- Path: `.scratchpad/{agent_name}.md`
- Access: `read_scratchpad`, `rewrite_scratchpad`
- Policy: **REWRITE** full content every N turns

```text
Freshness cycle:

+-----------------------------+
| Agent starts work cycle     |
+-------------+---------------+
              |
              v
+-----------------------------+
| read_scratchpad             |
| load current mental model   |
+-------------+---------------+
              |
              v
+-----------------------------+
| normal tool loop            |
| (edits, messages, handoffs) |
+-------------+---------------+
              |
              +-------------------------------+
              |                               |
              v                               v
+-----------------------------+      +-----------------------------+
| every N turns               |      | messages > 80% threshold   |
| rewrite_scratchpad          |      | auto-summarize with LLM     |
| full replacement            |      | + force scratchpad rewrite  |
+-------------+---------------+      +-------------+---------------+
              |                                      |
              v                                      v
+-------------------------------------------------------------+
| Re-inject identity + alignment + continue with fresh state  |
+-------------------------------------------------------------+
```

## REWRITE vs APPEND

The critical rule for this session:

> "The scratchpad must be REWRITTEN, not appended to"

Why rewrite:

- Forces distillation into current truth.
- Prevents unbounded growth.
- Removes stale plans that no longer apply.
- Keeps signal-to-noise high.

Why append fails:

- Old assumptions remain forever.
- Contradictions accumulate.
- Agent keeps reading outdated intent.

```text
Bad:  scratchpad += "\nnew notes..."   (APPEND)
Good: scratchpad =  "current model"    (REWRITE)
```

## How It Works

1. Worker cycle starts by loading `.scratchpad/{name}.md` into message context.
2. Every `SCRATCHPAD_REWRITE_EVERY` turns, worker synthesizes current state and rewrites the full file.
3. Every `SELF_REFLECTION_EVERY` turns, inject prompt:
   - "Are you making progress or going in circles?"
4. If `len(messages) > CONTEXT_THRESHOLD` (80% of configured capacity):
   - Save transcript snapshot
   - Summarize via LLM
   - Replace message history with compressed summary
   - Re-inject identity and alignment reminder
   - Force scratchpad rewrite from summarized state
5. Handoff narrative generation includes scratchpad content so lead receives intent + execution state.

## Key Code

### ScratchpadManager (file-backed)

```python
class ScratchpadManager:
    def read(self, agent_name: str) -> str:
        ...

    def rewrite(self, agent_name: str, content: str) -> str:
        path.write_text(content)  # full replacement
```

### Worker tools

```python
{"name": "read_scratchpad", ...}
{"name": "rewrite_scratchpad", ...}
```

### Summarization trigger (80%)

```python
if len(messages) > CONTEXT_THRESHOLD:
    messages = self._summarize_messages(...)
```

### Reflection injection

```python
if turns % SELF_REFLECTION_EVERY == 0:
    inject("Are you making progress or going in circles?")
```

### Alignment re-injection after summary

```python
messages = [
  make_identity_block(...),
  make_alignment_block(...),
  {"role": "user", "content": "<summary>...</summary>"},
]
```

## What Changed From s12

| Component | s12 | s13 |
|---|---|---|
| Worker memory | message-only | message + file scratchpad |
| Scratchpad policy | none | rewrite-only | 
| Compression reaction | summarize only | summarize + role/alignment reinjection |
| Reflection loop | none | periodic self-reflection prompt |
| Handoff inputs | diff + runtime | diff + runtime + scratchpad |

## Tool Surface

### `read_scratchpad`

- Worker reads its own scratchpad at start of work cycle.
- Lead can read any teammate scratchpad by `agent_name`.

### `rewrite_scratchpad`

- Replaces the entire scratchpad content.
- No append mode exists.

## Constraints and Non-Goals

- No planner/worker role split in this session (that is s14).
- No merge logic changes (that is s16).
- No changes to s06 implementation files; this session layers additional freshness controls in s13.
- Scratchpad state is file-backed under `.scratchpad/`, not in-memory-only.

## Production Reference

This session maps directly to Cursor freshness mechanisms (`docs/reference/cursor-harness-notes.md`, Section 8):

- "The scratchpad must be REWRITTEN, not appended to"
- Auto-summarization at ~80% context capacity
- Self-reflection prompts for stuck detection
- Identity and alignment reminders after compression

These controls prevent drift during long autonomous runs and keep role behavior stable after context resets.

## Why This Matters

Structured handoffs (s12) improve upward communication.
Scratchpad rewriting (s13) improves **local coherence over time**.

Together they create the minimal loop for long-running workers:

- do work
- keep local state fresh
- communicate completion clearly

## Try It

```sh
python agents/s13_scratchpad_rewriting.py
```

Suggested prompts:

1. `Spawn worker alpha to edit a file and keep scratchpad updated every few turns.`
2. `Ask alpha to call read_scratchpad, then rewrite_scratchpad with a clearer plan.`
3. `Force long interaction and verify summarization + alignment reminders appear.`
4. `Submit handoff and inspect whether narrative reflects scratchpad state.`
