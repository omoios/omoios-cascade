---
name: debugging
description: Systematic debugging workflow for harness tools, orchestration, and agent loops.
triggers: debug, bug, reproduce, isolate, fix, verify
---

Use a disciplined four-step debugging loop: reproduce, isolate, fix, verify.

First reproduce the failure with the smallest deterministic setup possible. Capture exact command, input payload, and observed output. Prefer one failing test or one direct handler call over broad end-to-end runs until you have a stable signal. If the issue is flaky, record timing and state transitions to identify race candidates.

Then isolate the fault boundary. Determine whether the problem lives in validation, matching, tool wiring, async orchestration, or merge/application logic. Inspect state handoffs (`task_id`, `worker_id`, event payloads) and confirm assumptions about data shape at each boundary. Avoid editing multiple layers before finding the failing layer.

Apply the smallest fix that removes the root cause, not only the symptom. Preserve existing interfaces and compatibility paths unless the bug requires a contract change. If behavior depends on ordering or priority, make the rule explicit in code and encode it in tests.

Verify by re-running the original failing case and adjacent regression checks. Ensure both success and failure paths still behave correctly, especially around invalid inputs and duplicate operations. Add a targeted test that would have caught the bug earlier, and keep the test independent of unrelated modules.

Finish by summarizing cause, fix, and guardrail. This keeps future triage fast and prevents repeated regressions in long-horizon orchestration scenarios.
