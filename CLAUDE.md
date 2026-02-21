# CLAUDE.md -- Agent Instructions

This is a progressive learning repository that teaches how to build AI agents from scratch across 20 sessions (s01-s20). Sessions s01-s11 cover fundamentals (agent loop through autonomous teams). Sessions s12-s20 implement a multi-agent orchestration harness based on Cursor's "self-driving codebases" research.

The `harness` Python package in `src/harness/` is fully implemented with asyncio concurrency and PyO3/Rust acceleration.

---

## Project Structure

```
learn-claude-code/
├── agents/                     # Python reference implementations (s01-s20 + s_full.py)
├── src/harness/                # Production-style harness package (asyncio, 30+ files)
├── src/harness_core/           # PyO3/Rust acceleration crate (maturin, walkdir, rayon, md-5)
├── web/                        # Next.js interactive learning platform (TypeScript)
│   ├── src/agents/             #   TypeScript agent implementations (s01-s20)
│   └── tests/agents/           #   Vitest tests for TS agents
├── docs/                       # Session guides + architecture docs
│   ├── architecture/           #   design-doc.md, testing-strategy.md
│   ├── reference/              #   cursor-harness-notes.md (source research)
│   ├── s01-*.md ... s20-*.md   #   Per-session learning guides
├── skills/                     # Skill files for s05 (agent-builder, code-review, etc.)
├── ARCHITECTURE.md             # High-level harness architecture overview
├── pyproject.toml              # UV-managed Python project config
└── .github/workflows/ci.yml   # CI: typecheck + vitest + build (web/)
```

---

## Commands

### Python (UV)

```bash
uv sync                                    # Install dependencies
uv run python agents/s01_agent_loop.py     # Run any session agent
uv run pytest tests/python/ -v             # Run Python tests
uv run ruff check src/ agents/             # Lint
uv run ruff format src/ agents/            # Format
```

### Web (npm)

```bash
cd web
npm ci                       # Install dependencies
npx tsc --noEmit             # Type check
npx vitest run               # Run tests
npm run build                # Full build
npm run dev                  # Dev server at localhost:3000
```

### CI (GitHub Actions)

CI runs on push/PR to main: `tsc --noEmit` -> `vitest run` -> `npm run build` (web/ only).

---

## Architecture Decisions (Settled)

These decisions were made through iterative refinement and are NOT open for re-discussion:

1. **Instructor library** for ALL structured LLM outputs (handoffs, tasks, planner decisions, scratchpad)
2. **Instructor integration**: loop-level for planner decisions, tool-level for payloads
3. **Event bus + Rich CLI renderer** for observability (typed pydantic HarnessEvent models)
4. **Thread-safe queue per worker** for downward context delivery
5. **Hybrid StateSnapshot freshness**: eager for task_board counts, lazy for full worker snapshots
6. **Strict scratchpad validation** on required sections, advisory on optional
7. **ABANDONED as TaskStatus enum value** (not a separate tool)
8. **Hard cap of 3 fixer rounds** in reconciliation
9. **Watchdog**: metrics + output pattern analysis (repeated tool calls, diminishing diffs)
10. **Uniform model** for all roles (single model from config)
11. **IdempotencyGuard** with optional file persistence (.idempotency.json)
12. **Signal handler + checkpoint + resume** for graceful Ctrl+C shutdown
13. **Refactor s_full.py into `src/harness/` package** (models.py, planner.py, worker.py, watchdog.py, etc.)
14. **Error messages**: problem + guidance + state dump (include worker IDs, task IDs, handoff IDs)
15. **Endurance tests**: predefined task graph for happy path, invariant assertions for chaos

---

## Key Documents

### Architecture (read these first)

| Document | Path | What It Covers |
|----------|------|----------------|
| Architecture Overview | [ARCHITECTURE.md](./ARCHITECTURE.md) | High-level harness diagram, layers, data flow (254 lines) |
| Design Document | [docs/architecture/design-doc.md](./docs/architecture/design-doc.md) | Full technical spec: pydantic models, concurrency, coherence mechanisms (980 lines) |
| Testing Strategy | [docs/architecture/testing-strategy.md](./docs/architecture/testing-strategy.md) | Layer-by-layer test plan with pytest examples (1343 lines) |
| Cursor Research Notes | [docs/reference/cursor-harness-notes.md](./docs/reference/cursor-harness-notes.md) | Source material: Cursor's 6 iterations, failure modes, what worked (381 lines) |

### Session Guides (s01-s11: fundamentals)

| Session | Doc | Agent (Python) | Agent (TypeScript) | Concept |
|---------|-----|----------------|--------------------|---------| 
| s01 | [docs/s01-the-agent-loop.md](./docs/s01-the-agent-loop.md) | [agents/s01_agent_loop.py](./agents/s01_agent_loop.py) | [web/src/agents/s01.ts](./web/src/agents/s01.ts) | while loop + bash |
| s02 | [docs/s02-multi-tool-dispatch.md](./docs/s02-multi-tool-dispatch.md) | [agents/s02_multi_tool.py](./agents/s02_multi_tool.py) | [web/src/agents/s02.ts](./web/src/agents/s02.ts) | Read, Write, Edit, Bash |
| s03 | [docs/s03-structured-planning.md](./docs/s03-structured-planning.md) | [agents/s03_structured_planning.py](./agents/s03_structured_planning.py) | [web/src/agents/s03.ts](./web/src/agents/s03.ts) | TodoWrite |
| s04 | [docs/s04-context-isolation.md](./docs/s04-context-isolation.md) | [agents/s04_context_isolation.py](./agents/s04_context_isolation.py) | [web/src/agents/s04.ts](./web/src/agents/s04.ts) | Task tool / subagents |
| s05 | [docs/s05-knowledge-loading.md](./docs/s05-knowledge-loading.md) | [agents/s05_knowledge_loading.py](./agents/s05_knowledge_loading.py) | [web/src/agents/s05.ts](./web/src/agents/s05.ts) | SKILL.md injection |
| s06 | [docs/s06-context-compression.md](./docs/s06-context-compression.md) | [agents/s06_compression.py](./agents/s06_compression.py) | [web/src/agents/s06.ts](./web/src/agents/s06.ts) | 3-layer compression |
| s07 | [docs/s07-file-based-tasks.md](./docs/s07-file-based-tasks.md) | [agents/s07_file_tasks.py](./agents/s07_file_tasks.py) | [web/src/agents/s07.ts](./web/src/agents/s07.ts) | Tasks API + deps |
| s08 | [docs/s08-background-execution.md](./docs/s08-background-execution.md) | [agents/s08_background.py](./agents/s08_background.py) | [web/src/agents/s08.ts](./web/src/agents/s08.ts) | Background threads |
| s09 | [docs/s09-team-messaging.md](./docs/s09-team-messaging.md) | [agents/s09_team_messaging.py](./agents/s09_team_messaging.py) | [web/src/agents/s09.ts](./web/src/agents/s09.ts) | Agent teams + mailboxes |
| s10 | [docs/s10-team-protocols.md](./docs/s10-team-protocols.md) | [agents/s10_team_protocols.py](./agents/s10_team_protocols.py) | [web/src/agents/s10.ts](./web/src/agents/s10.ts) | Shutdown + plan approval |
| s11 | [docs/s11-autonomous-agent.md](./docs/s11-autonomous-agent.md) | [agents/s11_autonomous.py](./agents/s11_autonomous.py) | [web/src/agents/s11.ts](./web/src/agents/s11.ts) | Idle cycle + auto-claim |

### Session Guides (s12-s20: harness)

| Session | Doc | Agent (Python) | Agent (TypeScript) | Concept |
|---------|-----|----------------|--------------------|---------| 
| s12 | [docs/s12-structured-handoffs.md](./docs/s12-structured-handoffs.md) | [agents/s12_structured_handoffs.py](./agents/s12_structured_handoffs.py) | [web/src/agents/s12.ts](./web/src/agents/s12.ts) | Diff + narrative + status + metrics |
| s13 | [docs/s13-scratchpad-rewriting.md](./docs/s13-scratchpad-rewriting.md) | [agents/s13_scratchpad_rewriting.py](./agents/s13_scratchpad_rewriting.py) | [web/src/agents/s13.ts](./web/src/agents/s13.ts) | REWRITE not append |
| s14 | [docs/s14-planner-worker-split.md](./docs/s14-planner-worker-split.md) | [agents/s14_planner_worker_split.py](./agents/s14_planner_worker_split.py) | [web/src/agents/s14.ts](./web/src/agents/s14.ts) | Planners delegate, workers execute |
| s15 | [docs/s15-worker-isolation.md](./docs/s15-worker-isolation.md) | [agents/s15_worker_isolation.py](./agents/s15_worker_isolation.py) | [web/src/agents/s15.ts](./web/src/agents/s15.ts) | Per-worker workspace copies |
| s16 | [docs/s16-optimistic-merge.md](./docs/s16-optimistic-merge.md) | [agents/s16_optimistic_merge.py](./agents/s16_optimistic_merge.py) | [web/src/agents/s16.ts](./web/src/agents/s16.ts) | 3-way merge + fix-forward |
| s17 | [docs/s17-recursive-hierarchy.md](./docs/s17-recursive-hierarchy.md) | [agents/s17_recursive_hierarchy.py](./agents/s17_recursive_hierarchy.py) | [web/src/agents/s17.ts](./web/src/agents/s17.ts) | Root -> sub-planners -> workers |
| s18 | [docs/s18-error-tolerance.md](./docs/s18-error-tolerance.md) | [agents/s18_error_tolerance.py](./agents/s18_error_tolerance.py) | [web/src/agents/s18.ts](./web/src/agents/s18.ts) | Error budgets, errors-as-tasks |
| s19 | [docs/s19-failure-modes.md](./docs/s19-failure-modes.md) | [agents/s19_failure_modes.py](./agents/s19_failure_modes.py) | [web/src/agents/s19.ts](./web/src/agents/s19.ts) | Watchdog: zombie/tunnel-vision/burn |
| s20 | [docs/s20-reconciliation-pass.md](./docs/s20-reconciliation-pass.md) | [agents/s20_reconciliation.py](./agents/s20_reconciliation.py) | [web/src/agents/s20.ts](./web/src/agents/s20.ts) | Green branch + fixer loop |

### Combined Reference

| File | Path | Description |
|------|------|-------------|
| s_full.py | [agents/s_full.py](./agents/s_full.py) | Monolithic combined reference (2550 lines, all s01-s20 patterns). Being refactored into src/harness/. |

### Coherence Mechanism Session Map

These cross-cutting mechanisms are introduced in specific sessions:

| Mechanism | Primary Session | Design Doc Section |
|-----------|----------------|--------------------|
| StateSnapshot (state reconstruction after compression) | s13 | Long-Running Agent Coherence > State Reconstruction |
| ScratchpadSchema (mandatory sections + instructor validation) | s13 | Long-Running Agent Coherence > Mandatory Scratchpad Schema |
| CompletionGate (verify all workers stopped, handoffs merged) | s14 | Long-Running Agent Coherence > Completion Verification Gate |
| Planner loop bounds (max_turns, max_wall_time) | s14 | Long-Running Agent Coherence > Planner Loop Bounds |
| ContextUpdate (downward info delivery via thread-safe queues) | s14 | Long-Running Agent Coherence > Downward Context Updates |
| IdempotencyGuard (prevent duplicate spawns, merges, tasks) | s16 | Long-Running Agent Coherence > Duplicate Work Prevention |
| Error budget snapshots in StateSnapshot | s18 | Long-Running Agent Coherence > State Reconstruction |
| Watchdog pattern analysis (repeated tool calls, diminishing diffs) | s19 | Long-Running Agent Coherence > (referenced in design doc) |
| Fixer loop bounds (hard cap 3 rounds) | s20 | Long-Running Agent Coherence > (referenced in design doc) |

### Test Layers

Defined in [docs/architecture/testing-strategy.md](./docs/architecture/testing-strategy.md):

```
Layer 0:   Models (pure pydantic)
Layer 1:   Config (pydantic-settings)
Layer 2:   Tools (filesystem/subprocess)
Layer 3:   Git (workspace, diff, merge)
Layer 3.5: Structured Output (instructor + pydantic response models) -- TO BE ADDED
Layer 4:   Agent loop (mocked LLM)
Layer 4.5: Coherence (state after compression)
Layer 4.6: Confusion regression (idempotency, completion gate)
Layer 5:   Orchestration (multi-agent coordination)
Layer 5.5: Endurance (long-horizon, loop bounds)
Layer 5.6: Chaos (injected failures, race conditions)
Layer 6:   End-to-end (real LLM)
```

---

## Implementation Status

### Done

- [x] Sessions s01-s11: Python agents, TypeScript agents, docs, tests
- [x] Sessions s12-s20: Python agents, TypeScript agents, docs, TS tests
- [x] s_full.py: Combined reference with guardrails (idle-loop breaker, progress timeout, forced reconcile)
- [x] Architecture docs: ARCHITECTURE.md, design-doc.md, testing-strategy.md
- [x] Design doc coherence section (6 mechanisms)
- [x] Testing strategy robustness layers (4 new test layers)
- [x] UV migration (pyproject.toml, uv.lock)
- [x] CI workflow (web/ typecheck + vitest + build)

- [x] `src/harness/` package implementation (30+ source files: models, planner, worker, watchdog, cli, events, tools, git, orchestration)
- [x] Instructor library integration (structured.py stub + pyproject.toml dependency)
- [x] Event bus + Rich CLI renderer (events.py + rendering.py + pyproject.toml dependency)
- [x] Python test suite (tests/python/ -- 194 tests across 18 files, layers 0-5.6)
- [x] Layer 3.5 Structured Output test section in testing-strategy.md
- [x] Graceful shutdown (signal handler + checkpoint + resume -- orchestration/shutdown.py)
- [x] Coherence appendix document (docs/architecture/coherence-appendix.md)
- [x] 3-way merge conflict detection wired into accept_handoff (base snapshots per worker)
- [x] SIGINT checkpoint fix (ErrorBudget attribute names, try/except in signal handler)
- [x] Watchdog activity recording in workers
- [x] Context compression trigger in base agent
- [x] Post-run reconciliation with configurable test_command
- [x] Live tier testing (Tiers 1-10) against MiniMax API -- all passing

- [x] Workspace cleanup with configurable retain (always prune at end of run)
- [x] Wire spawn_fixer_fn for auto-fix in reconciliation

- [x] Asyncio migration: all I/O and orchestration converted from threading to asyncio
- [x] PyO3/Rust acceleration: harness_core crate with snapshot_workspace (walkdir+rayon) and compute_diff (md-5+rayon)
- [x] UV workspace setup with maturin build for Rust crate
- [x] Try-import fallback pattern (HAS_RUST flag, pure-Python fallback when Rust unavailable)

---

## Conventions

- **Python**: UV for package management. Ruff for lint/format. Pydantic v2 for all models. Type hints everywhere.
- **TypeScript**: npm in web/. Vitest for tests. Next.js App Router.
- **Docs**: Technical, no emojis, no table of contents. Pydantic code blocks. ASCII diagrams.
- **Tests**: Follow layer-by-layer strategy. Each layer mocks only the layer above.
- **Git**: Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`).
- **Sessions s01-s11**: Frozen. Do not modify.
- **This is educational**: Toy learning implementation. Production patterns at educational scale.

---

## Tech Stack

- Python 3.10+, UV, pydantic v2, pydantic-settings, anthropic SDK, instructor (planned)
- Rust (PyO3 0.28, maturin, walkdir, rayon, md-5) -- optional acceleration
- TypeScript, Next.js, Vitest
- Rich (planned, for CLI output)
- Git (real git operations for workspace isolation and merge)

---

## Skills (for s05)

| Skill | Path |
|-------|------|
| agent-builder | [skills/agent-builder/SKILL.md](./skills/agent-builder/SKILL.md) |
| code-review | [skills/code-review/SKILL.md](./skills/code-review/SKILL.md) |
| mcp-builder | [skills/mcp-builder/SKILL.md](./skills/mcp-builder/SKILL.md) |
| pdf | [skills/pdf/SKILL.md](./skills/pdf/SKILL.md) |
