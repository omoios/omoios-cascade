---
name: code-review
description: Practical review checklist for harness changes before handoff.
triggers: review, code review, checklist, quality, regressions
---

Apply this review pass before finalizing code changes.

Start with correctness and scope control. Verify the implementation actually satisfies the requested behavior and does not silently expand into unrelated refactors. Confirm key control-flow paths are covered, especially error handling, fallback logic, and edge cases around missing files, invalid inputs, and duplicate operations.

Check type and model integrity. Ensure pydantic models still represent the contract used by callers. Prefer explicit field defaults and avoid introducing optional behavior that weakens invariants. Look for places where `dict[str, Any]` can leak unchecked structure across boundaries and ensure validation occurs before persisted side effects.

Review async and orchestration safety. Confirm async handlers return awaitable results where expected, no blocking calls are left on hot paths, and new state mutation is deterministic. Verify tools do not escape workspace boundaries and do not introduce unsafe command execution behavior.

Review style and maintainability. Keep naming consistent with existing harness terms (`task_id`, `worker_id`, `handoff`). Preserve import ordering and project patterns. Avoid docstrings if the module style excludes them. Ensure helper functions are small and specific rather than generic wrappers with hidden behavior.

Finally, validate test coverage and runtime checks. Existing tests should remain green, and new logic should have focused tests that capture matching, validation, and integration points. Favor one behavior assertion per test scenario to keep failures easy to diagnose.
