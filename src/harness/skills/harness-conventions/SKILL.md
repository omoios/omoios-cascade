---
name: harness-conventions
description: Coding conventions for harness Python modules and async orchestration.
triggers: harness, conventions, pydantic, asyncio, import style
---

Follow these conventions when editing `src/harness/` modules.

Use pydantic models as the source of truth for structured data exchanged between agent roles, orchestration components, and tool boundaries. Prefer explicit model fields with clear defaults and keep validation logic close to the model when practical. Preserve existing field names and avoid introducing alternate aliases unless a migration explicitly requires them.

Prefer asyncio-native patterns across orchestration code. Use `async def` for I/O paths, `await` for subprocess, filesystem offloading, and network calls, and only use thread offload for blocking operations that cannot be replaced with async APIs. Keep async call chains explicit rather than hiding concurrency behind side effects.

Imports should be grouped and deterministic: standard library first, third-party second, local package imports last. Keep imports minimal and avoid wildcard imports. Avoid circular dependencies by moving narrowly scoped imports inside functions when needed for runtime safety.

Preserve the repository style of concise code without docstrings. Instead of long comments, make intent clear through naming, small helper functions, and direct control flow. Add comments only for non-obvious coordination constraints, invariants, or failure-mode handling.

When changing orchestration behavior, prefer additive, backwards-compatible changes that do not break existing session guides or historical tests. Keep interfaces stable and keep fallback behavior in place when introducing new features.
