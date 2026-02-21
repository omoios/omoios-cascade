---
name: test-writing
description: Pytest patterns for harness layers, async code, and deterministic fixtures.
triggers: tests, pytest, asyncmock, tmp_path, unit test
---

Write tests using the project’s layered strategy and keep each test focused on one behavior.

For model and config logic, prefer pure unit tests with direct object construction and explicit assertions on validation, defaults, and invariants. For tool handlers, use temp workspaces and assert both success and failure paths, including invalid paths, missing fields, and boundary checks.

For async code, use pytest async support with awaitable tests and avoid sleeping for timing control. Mock external async dependencies with `AsyncMock` and assert call arguments to verify orchestration behavior. When validating event emission, inspect event bus history or spy callbacks rather than relying on side-effect-heavy integration flows.

Use `tmp_path` for filesystem tests and keep test data local to each function. Construct directory trees explicitly and verify both file contents and metadata fields returned by handlers. Avoid sharing mutable global state between tests unless guarded with fixture resets.

When adding new matching or scoring behavior, include deterministic tests for ranking and tie-breaking. Cover positive matches, no-match cases, duplicate handling, and source-priority resolution. If behavior depends on path classification, use controlled temporary paths and monkeypatch home/workspace roots.

Prefer small fixtures over broad setup factories. Name tests with behavior-first intent, e.g. `test_registry_prefers_project_skill_over_builtin`. Keep assertions direct and readable so regressions can be diagnosed from one failure line.
