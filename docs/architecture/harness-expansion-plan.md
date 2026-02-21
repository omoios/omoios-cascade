# Harness Expansion Plan: Production Agent Capabilities

Status: PLANNED
Date: 2025-02-21
Sources: oh-my-pi (can1357/oh-my-pi), Claude Code, our harness gap analysis

---

## Current State

The harness (`src/harness/`) is a fully async, PyO3-accelerated multi-agent orchestration system with planner-worker hierarchy, structured handoffs, scratchpad rewriting, optimistic merge, error budgets, watchdog, and reconciliation. 30+ source files, 194 tests passing.

**What exists:**
- 5 worker tools: bash, read_file, write_file, edit_file, submit_handoff
- 12 planner tools: spawn_worker, create_task, review/accept/reject handoff, scratchpad, messaging, etc.
- ToolRegistry with role-based access control
- EventBus with subscriber pattern (basic lifecycle hooks)
- BaseAgent with on_before_llm_call and on_tool_result hooks
- PyO3 Rust crate: snapshot_workspace, compute_diff (walkdir, rayon, md-5)
- 3-layer context compression

**What is missing (compared to oh-my-pi and Claude Code):**
- No search tools (grep, glob, find)
- No LSP integration
- No skill/knowledge loading in the harness
- No AGENTS.md hierarchical config loader
- No hook system for user-defined lifecycle handlers
- No background task tool for workers
- No browser/visual verification
- No web search/fetch
- No todo_write tool
- No ask tool
- No model role routing
- Rust acceleration covers only 2 of 12+ possible modules

---

## Phase A: Essential Worker Tools

**Goal**: Workers can search, discover, and track progress -- the minimum for useful code work.

### A1. Grep Tool

Add regex content search to worker tools.

**File**: `src/harness/tools/worker_tools.py`
**Schema name**: `grep`
**Parameters**: `pattern: str, path: str, workspace_path: str, include: str | None = None, context_lines: int = 0`
**Behavior**:
- Use `asyncio.create_subprocess_exec` with `grep -rn` (or `rg` if available)
- Restrict path resolution to workspace_path (security)
- Return matches as `{file: str, line: int, content: str}[]`
- Cap output at 100 matches with truncation notice
- Add to WORKER_TOOL_SPECS in planner_tools.py
- Register with ToolRegistry for role "worker"

**Rust acceleration (Phase E)**: Replace subprocess grep with ripgrep internals in harness_core.

### A2. Glob/Find Tool

Add file discovery by pattern.

**File**: `src/harness/tools/worker_tools.py`
**Schema name**: `find_files`
**Parameters**: `pattern: str, workspace_path: str, max_results: int = 100`
**Behavior**:
- Use `pathlib.Path.glob()` or `asyncio.create_subprocess_exec` with `find`
- Respect .gitignore via `git ls-files` when in a git repo
- Return sorted file paths relative to workspace_path
- Cap at max_results

**Rust acceleration (Phase E)**: Replace with `ignore` + `globset` crates in harness_core.

### A3. TodoWrite Tool

Add progress tracking visible to planners.

**File**: `src/harness/tools/worker_tools.py`
**Schema name**: `todo_write`
**Parameters**: `todos: list[dict]` where each dict has `content: str, status: str, priority: str`
**Behavior**:
- Store todo list on the worker agent instance
- Status values: pending, in_progress, completed, cancelled
- Planner can read todos via worker state in StateSnapshot
- Emit TodoUpdated event on EventBus

**New model**: Add `TodoItem` to `src/harness/models/` (pydantic).

### A4. Ask Tool

Let workers request clarification from the planner.

**File**: `src/harness/tools/worker_tools.py`
**Schema name**: `ask`
**Parameters**: `question: str, options: list[dict] | None = None`
**Behavior**:
- Sends a message to the worker's parent planner inbox
- Message type: "clarification_request"
- Planner sees it in read_inbox and can respond via send_message
- Worker blocks until response received (with timeout)

---

## Phase B: Agent Infrastructure

**Goal**: Harness loads project context, skills, and supports user-defined lifecycle hooks.

### B1. AGENTS.md Loader

Load hierarchical project context into agent system prompts.

**File**: `src/harness/config/agents_md.py` (new)
**Behavior**:
- On harness startup, walk from workspace root upward looking for AGENTS.md / CLAUDE.md
- Support hierarchical loading: root AGENTS.md + subdirectory AGENTS.md files
- Inject loaded content into the system prompt of every agent (planner and worker)
- Content is read-only, never modified by agents
- Also check for `.claude/CLAUDE.md`, `.codex/AGENTS.md` (extension discovery)

**Integration**: `HarnessRunner.__init__` reads AGENTS.md and passes to agent constructors.

### B2. Skill Loader

Port s05 SKILL.md loading into the harness with description-based matching.

**File**: `src/harness/config/skills.py` (new)
**Behavior**:
- Discover SKILL.md files from:
  - `{workspace}/.omp/skills/*/SKILL.md`
  - `{workspace}/.claude/skills/*/SKILL.md`
  - `{workspace}/skills/*/SKILL.md`
  - `~/.claude/skills/*/SKILL.md` (global)
- Parse YAML frontmatter for `name`, `description`, `triggers`
- On worker spawn, match task description against skill descriptions
- Inject matched skill content into the worker's system prompt
- Workers can also call `load_skill` tool to load a skill on demand

**New model**: Add `SkillDefinition` to `src/harness/models/` (pydantic).

### B3. Hook System Expansion

Add user-defined lifecycle hooks beyond the current on_before_llm_call / on_tool_result.

**File**: `src/harness/config/hooks.py` (new)
**Hook points**:
- `session_start` -- fired when harness run begins
- `session_end` -- fired when harness run completes
- `turn_start` -- fired before each agent loop iteration
- `turn_end` -- fired after each agent loop iteration
- `pre_tool_call(tool_name, args)` -- can modify args or block the call
- `post_tool_call(tool_name, args, result)` -- can modify result
- `worker_spawn(worker_id, task)` -- fired when a worker is spawned
- `worker_complete(worker_id, handoff)` -- fired when a worker submits handoff

**Hook discovery**:
- `{workspace}/.omp/hooks/*.py`
- `{workspace}/.claude/hooks/*.py`
- Each hook file exports a `register(hook_api)` function
- `hook_api.on(event_name, callback)` registers handlers

**Integration**: Wire hooks into BaseAgent.run() loop, HarnessRunner worker lifecycle.

---

## Phase C: Background Tasks and Model Roles

**Goal**: Workers can spawn async subtasks, and different agent roles use appropriately-sized models.

### C1. Background Task Tool

Let workers spawn fire-and-forget async tasks and collect results.

**File**: `src/harness/tools/worker_tools.py`
**Schema name**: `background_task`
**Parameters**: `description: str, command: str, workspace_path: str`
**Returns**: `{task_id: str, status: "running"}`

**Schema name**: `check_background`
**Parameters**: `task_id: str`
**Returns**: `{status: str, output: str | None}`

**Behavior**:
- Spawn an asyncio.Task that runs the command
- Store task reference in a dict on the worker agent
- check_background polls task status
- Results are available after task completes
- Timeout after configurable limit (default 120s)

### C2. Model Role Routing

Support different models for different agent roles.

**File**: `src/harness/config/settings.py` (modify existing)
**New config fields**:
```python
class HarnessConfig(BaseSettings):
    # existing fields...
    model_default: str = "..."
    model_smol: str | None = None    # cheap model for explore/quick tasks
    model_slow: str | None = None    # powerful model for complex reasoning
    model_plan: str | None = None    # planning model
    model_commit: str | None = None  # commit message model
```

**Behavior**:
- RootPlanner uses `model_plan` (falls back to model_default)
- Workers use `model_default`
- Explore subagents use `model_smol` (falls back to model_default)
- Reconciliation fixer uses `model_slow` (falls back to model_default)
- Config via env vars: `HARNESS_MODEL_SMOL`, `HARNESS_MODEL_SLOW`, etc.

---

## Phase D: Browser and Visual Verification

**Goal**: Agents can open browsers, take screenshots, and verify UI visually.

### D1. Browser Tool

Integrate Playwright for headless browser automation.

**File**: `src/harness/tools/browser_tool.py` (new)
**Schema name**: `browser`
**Parameters**: `action: str, url: str | None, selector: str | None, ...`
**Actions**:
- `navigate(url)` -- go to URL
- `screenshot(path?)` -- capture current page, return base64 or save to file
- `click(selector)` -- click an element
- `type(selector, text)` -- type into an element
- `evaluate(script)` -- run JavaScript
- `get_text(selector?)` -- extract text content
- `accessibility_snapshot()` -- get accessibility tree (like oh-my-pi)
- `close()` -- close browser

**Dependencies**: `playwright` (pip install playwright, playwright install chromium)
**Integration**:
- Browser instance managed per-worker (isolated sessions)
- Screenshots can be sent to vision model for analysis
- Add to WORKER_TOOL_SPECS, register for role "worker"
- Optional: disable via config `browser_enabled: bool = False`

### D2. Vision Feedback Loop

Screenshot -> vision model analysis -> error detection -> fix cycle.

**File**: `src/harness/tools/browser_tool.py` (extend)
**Schema name**: `visual_verify`
**Parameters**: `url: str, expected: str`
**Behavior**:
- Navigate to URL, take screenshot
- Send screenshot to vision model with prompt: "Does this match the expected description: {expected}? List any visual issues."
- Return structured result: `{matches: bool, issues: list[str], screenshot_path: str}`
- Worker can use this to verify UI changes before submitting handoff

---

## Phase E: Rust Acceleration Expansion

**Goal**: Accelerate the most-called tools with Rust in harness_core.

### E1. Rust Grep

Port ripgrep internals into harness_core.

**File**: `src/harness_core/src/grep.rs` (new)
**Dependencies**: `grep-regex`, `grep-searcher`, `grep-matcher` (ripgrep internals)
**Behavior**:
- Parallel file search with rayon
- Respect .gitignore via `ignore` crate
- Return matches as Vec of (file, line_number, content)
- Release GIL with py.detach for async compatibility
- Wire into worker_tools.py grep handler via HAS_RUST try-import fallback

### E2. Rust Glob

Port file discovery into harness_core.

**File**: `src/harness_core/src/glob.rs` (new)
**Dependencies**: `ignore`, `globset`
**Behavior**:
- Parallel directory walk with rayon
- Glob pattern matching with .gitignore respect
- Return sorted file paths
- Release GIL with py.detach
- Wire into worker_tools.py find_files handler via HAS_RUST try-import fallback

### E3. Rust Shell (brush)

Embed brush-shell for native bash execution.

**File**: `src/harness_core/src/shell.rs` (new)
**Dependencies**: `brush-core` (vendored from brush-shell), `brush-builtins`
**Behavior**:
- Persistent shell sessions (no subprocess spawn per command)
- Streaming stdout/stderr
- Custom builtins for workspace-restricted operations
- Cooperative cancellation with timeout
- Release GIL with py.detach
- Wire into worker_tools.py bash handler via HAS_RUST try-import fallback

**Note**: This is the most complex Rust addition. brush-core is ~15k lines. Vendor as oh-my-pi does.

---

## Phase F: Advanced Patterns

**Goal**: Stream-triggered rules, extension discovery, git tools, web access.

### F1. TTSR (Time-Traveling Streamed Rules)

Zero-context rules that inject only when the model generates matching patterns.

**File**: `src/harness/agents/ttsr.py` (new)
**Behavior**:
- Rules defined in `.omp/rules/*.md` or `.claude/rules/*.md`
- Each rule has a `condition` regex and `content` (the rule text)
- During streaming, check model output against all rule conditions
- When a condition matches: abort stream, inject rule as system reminder, retry
- Each rule fires at most once per session (one-shot)
- Optional `scope` field to restrict to specific tool calls or file types

**Integration**: Wire into BaseAgent._call_llm() streaming path.

### F2. Extension Discovery

Load configuration from multiple AI tool directories.

**File**: `src/harness/config/discovery.py` (new)
**Behavior**:
- Discover and load from: `.omp/`, `.claude/`, `.cursor/`, `.codex/`, `.gemini/`
- Each directory can contain: skills/, hooks/, rules/, commands/
- Priority order: project-level > user-level (~/.omp/ > ~/.claude/)
- Merge configurations with source attribution
- Log which extensions were loaded and from where

### F3. Git Tools (Exposed as Agent Tools)

Expose git operations as proper tool schemas.

**File**: `src/harness/tools/git_tools.py` (new)
**Tool schemas**:
- `git_status(workspace_path)` -- return modified/staged/untracked files
- `git_diff(workspace_path, path?)` -- return diff for file or all changes
- `git_log(workspace_path, n: int = 10)` -- return recent commits
- `git_branch(workspace_path)` -- return current branch and list branches

**Register for**: both "worker" and "root_planner" roles.

### F4. Web Search and Fetch Tools

Let agents access external documentation and APIs.

**File**: `src/harness/tools/web_tools.py` (new)
**Tool schemas**:
- `web_search(query, max_results: int = 5)` -- search the web (via configurable provider)
- `web_fetch(url)` -- fetch URL content, convert HTML to markdown

**Dependencies**: `httpx` for HTTP, `html2text` or `markdownify` for HTML-to-markdown
**Config**: `web_search_provider` setting (exa, jina, etc.) with API key

---

## Phase G: Skill System for Harness

**Goal**: Implement the full skill lifecycle -- not just loading skills, but creating, testing, and managing them as first-class harness capabilities.

### G1. Skill Creation Tool

Let agents create new skills during execution.

**File**: `src/harness/tools/skill_tools.py` (new)
**Schema name**: `create_skill`
**Parameters**: `name: str, description: str, content: str, triggers: list[str] | None = None`
**Behavior**:
- Write SKILL.md to `{workspace}/.omp/skills/{name}/SKILL.md`
- YAML frontmatter: name, description, triggers
- Body: the skill content (instructions, patterns, examples)
- Validate SKILL.md structure before writing
- Emit SkillCreated event on EventBus

### G2. Skill Registry and Matching

Centralized skill management with intelligent matching.

**File**: `src/harness/config/skills.py` (extend from B2)
**New class**: `SkillRegistry`
**Behavior**:
- Maintain in-memory index of all discovered skills
- Match skills to tasks via:
  1. Exact trigger keyword match (highest priority)
  2. Description similarity (cosine similarity or keyword overlap)
  3. File pattern matching (e.g., skill triggers on `*.tsx` files)
- Support skill priorities: project-level > user-level > built-in
- Provide `list_skills()` and `get_skill(name)` methods
- Workers can call `load_skill` tool to load any skill by name on demand

### G3. Built-in Harness Skills

Ship default skills that teach agents harness-specific patterns.

**Directory**: `src/harness/skills/` (new)

**Skills to include**:
| Skill Name | Description | Triggers |
|---|---|---|
| `harness-conventions` | Coding patterns, pydantic model conventions, async patterns used in this harness | `harness`, `convention`, `pattern` |
| `code-review` | How to review code changes: check types, tests, patterns | `review`, `code quality` |
| `test-writing` | How to write tests following the layer-by-layer strategy | `test`, `pytest`, `testing` |
| `git-workflow` | Git conventions: conventional commits, branch naming | `git`, `commit`, `branch` |
| `debugging` | Systematic debugging approach: reproduce, isolate, fix, verify | `debug`, `error`, `fix` |

**Each skill**: `src/harness/skills/{name}/SKILL.md` with YAML frontmatter.

### G4. Skill Validation and Testing

Ensure skills are well-formed and functional.

**File**: `src/harness/config/skills.py` (extend)
**Behavior**:
- Validate SKILL.md on load:
  - YAML frontmatter present with required fields (name, description)
  - Body content non-empty
  - Triggers are valid strings
  - No duplicate skill names
- Report validation errors via EventBus (SkillValidationError event)
- Skip invalid skills with warning, don't crash

### G5. Skill Injection Points

Multiple ways skills reach the agent.

**Injection methods**:
1. **System prompt injection** (B2): Matched skills injected at agent creation time
2. **On-demand via tool** (G1/G2): Worker calls `load_skill(name)` and gets content as tool_result
3. **TTSR-triggered** (F1): Skill content injected when model output matches skill triggers
4. **Planner-directed**: Planner includes skill names in spawn_worker task description, skill loader matches and injects

**Priority/dedup**: If the same skill would be injected via multiple methods, inject only once.

---

## Phase H: Prompt Engineering and Freshness Hardening

**Goal**: Implement the prompt engineering patterns and freshness mechanisms from Cursor's V5a/V6 evolution that keep agents effective over long-running tasks.

Reference: cursor-harness-notes.md sections 8 (Prompt Engineering) and 9 (Freshness Mechanisms).

### H1. Self-Reflection Injection

Periodically inject self-assessment prompts into the agent loop.

**File**: `src/harness/agents/base.py` (modify)
**Behavior**:
- Every N turns (configurable, default 10), inject a system message:
  - "Are you making progress or going in circles?"
  - "Is your current approach working? If not, consider a different strategy."
- Track turn count on agent instance
- Injection happens in on_before_llm_call hook
- Emit SelfReflectionInjected event on EventBus

**Config**: `self_reflection_interval: int = 10` in HarnessConfig.

### H2. Identity Re-Injection

After every compression event, re-inject the agent's identity and constraints.

**File**: `src/harness/agents/base.py` (modify)
**Behavior**:
- After context compression triggers (auto-summarization at 80%):
  - Insert identity block at start of compressed context
  - "You are a Worker. Execute the assigned task. Do NOT decompose or spawn."
  - "You are a Planner. Decompose and delegate. NEVER write code."
- Identity text stored on agent instance at creation time
- Compression trigger in base.py already exists -- wire identity re-injection into it

### H3. Alignment Reminders

Reinforce role constraints after summarization.

**File**: `src/harness/agents/base.py` (modify)
**Behavior**:
- After any summarization/compaction event, append alignment reminder:
  - Worker: "Remember: you are a Worker. Execute the task. Do not plan or decompose."
  - Planner: "Remember: you are a Planner. Decompose and delegate. Never write code."
- This is distinct from H2 -- identity re-injection goes at the START of compressed context, alignment reminders go at the END as the most recent system message

### H4. Pivot Encouragement

Encourage agents to try different approaches after repeated failures.

**File**: `src/harness/agents/base.py` (modify)
**Behavior**:
- Track consecutive failure count per tool (e.g., edit_file fails 3 times)
- After 3 consecutive failures of the same tool on the same file:
  - Inject: "Your current approach has failed 3 times. Try a completely different approach."
- After 5 consecutive failures:
  - Inject: "STOP. This approach is not working. Step back and reconsider the problem."
- Reset failure counter on success

**Config**: `pivot_threshold: int = 3`, `hard_stop_threshold: int = 5` in HarnessConfig.

### H5. Constraints-Over-Instructions Pattern

Formalize negative constraints in agent system prompts.

**File**: `src/harness/prompts/` (new directory)
**Files**:
- `src/harness/prompts/worker.md` -- worker system prompt with constraints
- `src/harness/prompts/planner.md` -- planner system prompt with constraints
- `src/harness/prompts/sub_planner.md` -- sub-planner system prompt
- `src/harness/prompts/watchdog.md` -- watchdog system prompt

**Pattern**: Each prompt uses negative constraints (NEVER, DO NOT) over positive instructions:
```
NEVER write code. You decompose and delegate.
Do NOT plan beyond your delegated scope.
NEVER merge changes yourself -- submit handoffs.
```

**Integration**: Runner loads prompt files and passes to agent constructors. Prompts live in static .md files, not inline strings (following oh-my-pi's "NEVER build prompts in code" pattern).

---

## Phase I: Intent Specification Framework

**Goal**: Formalize how tasks are specified to agents, implementing the intent specification patterns from Cursor section 7 that prevent the "amplification of bad instructions" problem.

Reference: cursor-harness-notes.md section 7 (Specifying Intent to Agents).

### I1. TaskSpec Model

Structured intent specification for every task.

**File**: `src/harness/models/task_spec.py` (new)
**Model**:
```python
class TaskSpec(BaseModel):
    objective: str                    # What to accomplish
    scope: list[str]                  # Which files/modules are in scope
    non_goals: list[str] = []        # What NOT to do (explicit exclusions)
    success_criteria: list[str]       # How to verify completion
    performance_bounds: dict = {}     # Latency, memory, throughput limits
    dependency_philosophy: dict = {}  # Which libraries allowed/forbidden
    architectural_constraints: list[str] = []  # Patterns to follow/avoid
    priority: str = "medium"          # high, medium, low
    estimated_complexity: str = "medium"  # simple, medium, complex
```

**Integration**: create_task planner tool accepts TaskSpec fields. Workers receive the full TaskSpec in their system prompt, not just a description string.

### I2. Intent Validation

Validate task specifications before agent execution.

**File**: `src/harness/config/intent.py` (new)
**Behavior**:
- Validate TaskSpec on task creation:
  - objective is non-empty
  - scope lists at least one file or module
  - success_criteria has at least one criterion
- Warn (not block) if:
  - non_goals is empty (risk of scope creep)
  - performance_bounds is empty (risk of slow implementation)
  - dependency_philosophy is empty (risk of unnecessary dependencies)
- Emit IntentValidationWarning event for missing optional fields

### I3. Intent Templates

Pre-built intent templates for common task types.

**File**: `src/harness/config/intent_templates.py` (new)
**Templates**:
| Template | Pre-filled Fields |
|---|---|
| `feature` | scope, success_criteria (tests pass), architectural_constraints |
| `bugfix` | scope (affected files), success_criteria (bug no longer reproduces) |
| `refactor` | scope, non_goals (no behavior change), success_criteria (tests unchanged) |
| `test` | scope (test files), success_criteria (coverage increase) |
| `docs` | scope (doc files), non_goals (no code changes) |

**Usage**: Planner specifies template name + overrides when creating tasks.

---

## Phase J: Production Infrastructure

**Goal**: Activity logging, dynamic scaling, circuit breakers, cost tracking, and metrics dashboarding -- the production hardening layer from Cursor sections 10 and 12.

Reference: cursor-harness-notes.md sections 10 (Infrastructure), 12 (Open Questions), 14 (Gap Analysis).

### J1. Activity Logging

Per-agent structured activity logs.

**File**: `src/harness/observability/activity_log.py` (new)
**Behavior**:
- Each agent writes JSONL to `.activity/{agent_id}.jsonl`
- Each line records:
  ```json
  {"timestamp": "...", "event": "tool_use", "tool": "edit_file",
   "metrics": {"tokens": 150, "wall_time_ms": 230}, "agent_id": "worker_3"}
  ```
- Event types: spawn, tool_use, tool_result, handoff_submit, handoff_accept,
  handoff_reject, compression, self_reflection, error, shutdown
- Log rotation: new file per harness run (timestamped directory)
- Wire into BaseAgent.run() loop for automatic capture

### J2. Cost Attribution

Track token costs per task, per agent, per sub-planner.

**File**: `src/harness/observability/cost_tracker.py` (new)
**Behavior**:
- Track per-agent: input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
- Aggregate per-task: sum of all agent costs working on that task
- Aggregate per-subtree: sum of all costs under a SubPlanner
- Cost calculation: configurable per-token pricing in HarnessConfig
- Emit CostUpdate events on EventBus
- Final summary in reconciliation output

**Model**: Add `CostRecord` to observability module (pydantic).

### J3. Resource Bounds Enforcement

Hard limits on agent resource consumption.

**File**: `src/harness/observability/resource_bounds.py` (new)
**Bounds**:
- `max_wall_time_per_task: int = 600` (seconds, default 10 min)
- `max_tokens_per_agent: int = 100_000` (total tokens)
- `max_file_modifications: int = 50` (files modified before forced review)
- `max_consecutive_errors: int = 10` (errors before agent termination)

**Behavior**:
- Watchdog checks bounds every monitoring cycle
- When bound exceeded: emit ResourceBoundExceeded event, terminate agent
- Planner receives notification of terminated agent and can decide to retry or skip

### J4. Dynamic Agent Pool Scaling

Adjust worker pool size based on queue depth.

**File**: `src/harness/orchestration/pool_scaler.py` (new)
**Behavior**:
- Monitor pending task count on task board
- Scale up: if pending_tasks > active_workers * 2 and active_workers < max_workers
  - Spawn additional workers up to max_workers
- Scale down: if pending_tasks == 0 and idle_workers > min_workers
  - Gracefully shut down idle workers
- Configurable: `min_workers: int = 1`, `max_workers: int = 20`, `scale_factor: float = 2.0`
- Check interval: every 30 seconds
- Emit PoolScaleUp / PoolScaleDown events

### J5. Circuit Breakers

Error rate monitoring with automatic throttling.

**File**: `src/harness/orchestration/circuit_breaker.py` (new)
**States**: CLOSED (normal) -> OPEN (throttled) -> HALF_OPEN (testing recovery)
**Behavior**:
- Track error rate over sliding window (default 60 seconds)
- CLOSED -> OPEN: when error_rate > threshold (default 50%)
  - Stop spawning new workers
  - Let existing workers complete
  - Emit CircuitBreakerOpen event
- OPEN -> HALF_OPEN: after cooldown period (default 120 seconds)
  - Allow one new worker to test
- HALF_OPEN -> CLOSED: if test worker succeeds
- HALF_OPEN -> OPEN: if test worker fails

**Config**: `circuit_breaker_threshold: float = 0.5`, `circuit_breaker_cooldown: int = 120`

### J6. Graceful Degradation

Reduce parallelism under resource pressure.

**File**: `src/harness/orchestration/pool_scaler.py` (extend)
**Behavior**:
- Monitor system resources: memory usage, CPU load
- When memory > 80%: reduce max_workers by 50%, emit DegradationWarning
- When memory > 90%: reduce max_workers to min_workers, emit DegradationCritical
- When CPU sustained > 90% for 60s: reduce max_workers by 25%
- Recovery: when resources drop below thresholds, gradually restore max_workers

**Dependencies**: `psutil` for system resource monitoring.

### J7. Production Metrics Dashboard

Real-time metrics visualization.

**File**: `src/harness/observability/metrics.py` (new)
**Behavior**:
- Collect metrics from EventBus:
  - tasks_completed, tasks_failed, tasks_pending
  - workers_active, workers_idle, workers_terminated
  - tokens_total, tokens_per_minute
  - error_rate (sliding window)
  - merge_success_rate
  - average_task_duration
  - cost_total, cost_per_task
- Export options:
  1. Rich live table (CLI) -- extend existing rendering.py
  2. JSON endpoint (for external dashboards)
  3. JSONL metrics file (for post-hoc analysis)

**Integration**: MetricsCollector subscribes to all EventBus event types. CLI renderer shows live metrics panel.

### J8. Recovery from Partial Failure

Preserve partial results when a SubPlanner fails.

**File**: `src/harness/agents/planner.py` (modify)
**Behavior**:
- When a SubPlanner fails or is terminated:
  - Collect all completed worker handoffs from that SubPlanner's subtree
  - Merge completed work into canonical repo (don't discard)
  - Create recovery task with context: "SubPlanner X failed. Completed: [list]. Remaining: [list]."
  - Parent planner can assign recovery task to new SubPlanner
- Track partial progress via handoff aggregation at each SubPlanner level

---

## Implementation Order

```
Phase A (Essential Tools)             ~2-3 hours
  A1 grep                             worker_tools.py + tests
  A2 find_files                       worker_tools.py + tests
  A3 todo_write                       worker_tools.py + models + tests
  A4 ask                              worker_tools.py + tests

Phase B (Agent Infrastructure)        ~3-4 hours
  B1 AGENTS.md loader                 config/agents_md.py + tests
  B2 skill loader (basic)             config/skills.py + models + tests
  B3 hook system                      config/hooks.py + base agent wiring + tests

Phase C (Background + Roles)          ~2-3 hours
  C1 background_task tool             worker_tools.py + tests
  C2 model role routing               settings.py + runner.py + tests

Phase D (Browser)                     ~3-4 hours
  D1 browser tool                     tools/browser_tool.py + tests
  D2 visual_verify                    tools/browser_tool.py + tests

Phase E (Rust Acceleration)           ~4-6 hours
  E1 Rust grep                        harness_core/src/grep.rs + wiring + tests
  E2 Rust glob                        harness_core/src/glob.rs + wiring + tests
  E3 Rust shell (brush)               harness_core/src/shell.rs + vendoring + tests

Phase F (Advanced Patterns)           ~3-4 hours
  F1 TTSR                             agents/ttsr.py + tests
  F2 extension discovery              config/discovery.py + tests
  F3 git tools                        tools/git_tools.py + tests
  F4 web tools                        tools/web_tools.py + tests

Phase G (Skills)                      ~3-4 hours
  G1 create_skill tool                tools/skill_tools.py + tests
  G2 skill registry + matching        config/skills.py (extend) + tests
  G3 built-in skills                  harness/skills/*/SKILL.md (5 skills)
  G4 skill validation                 config/skills.py (extend) + tests
  G5 skill injection points           base agent + planner wiring + tests

Phase H (Prompt & Freshness)          ~2-3 hours
  H1 self-reflection injection        base.py + tests
  H2 identity re-injection            base.py + tests
  H3 alignment reminders              base.py + tests
  H4 pivot encouragement              base.py + tests
  H5 prompt files                     prompts/*.md + runner wiring + tests

Phase I (Intent Specification)        ~2-3 hours
  I1 TaskSpec model                   models/task_spec.py + tests
  I2 intent validation                config/intent.py + tests
  I3 intent templates                 config/intent_templates.py + tests

Phase J (Production Infrastructure)   ~5-7 hours
  J1 activity logging                 observability/activity_log.py + tests
  J2 cost attribution                 observability/cost_tracker.py + tests
  J3 resource bounds                  observability/resource_bounds.py + tests
  J4 dynamic pool scaling             orchestration/pool_scaler.py + tests
  J5 circuit breakers                 orchestration/circuit_breaker.py + tests
  J6 graceful degradation             orchestration/pool_scaler.py (extend) + tests
  J7 metrics dashboard                observability/metrics.py + rendering.py + tests
  J8 partial failure recovery         planner.py + tests
```

**Total estimated**: ~30-42 hours of implementation across all phases.

**Dependencies**:
- Phase A has no dependencies (can start immediately)
- Phase B depends on A being usable (but not complete)
- Phase C depends on A (background_task uses bash handler patterns)
- Phase D depends on A (browser tool follows same registration pattern)
- Phase E depends on A (accelerates tools from Phase A)
- Phase F depends on B (TTSR uses hook patterns, discovery uses skill patterns)
- Phase G depends on B2 (extends the basic skill loader)
- Phase H depends on nothing (modifies base.py hooks that already exist)
- Phase I depends on nothing (new models + validation, standalone)
- Phase J depends on A+B (uses EventBus, tools, agent lifecycle)

**Parallel execution**:
- Wave 1: A, H, I (no dependencies)
- Wave 2: B, C, D (depend on A patterns)
- Wave 3: E, F, G (depend on A tools, B infrastructure)
- Wave 4: J (depends on everything above for full integration)

---

## Test Strategy

Each new tool/feature follows the existing layer-by-layer strategy:

| Layer | What to Test | How |
|---|---|---|
| Layer 0 | New pydantic models (TodoItem, SkillDefinition) | Pure unit tests |
| Layer 2 | Tool handlers (grep, find_files, etc.) | Real filesystem in tmpdir |
| Layer 3 | Git tools | Real git operations in tmpdir |
| Layer 4 | Hook system, skill loading | Mocked LLM, real config files |
| Layer 5 | Background tasks, model routing | Mocked LLM, async test harness |

Tests go in `tests/python/` following existing naming: `test_{module}.py`.

---

## Files Created/Modified Per Phase

### Phase A
- MODIFY: `src/harness/tools/worker_tools.py` (add grep, find_files, todo_write, ask handlers)
- MODIFY: `src/harness/tools/planner_tools.py` (add to WORKER_TOOL_SPECS)
- MODIFY: `src/harness/runner.py` (register new tools)
- CREATE: `src/harness/models/todo.py` (TodoItem model)
- CREATE: `tests/python/test_worker_tools_extended.py`

### Phase B
- CREATE: `src/harness/config/agents_md.py`
- CREATE: `src/harness/config/skills.py`
- CREATE: `src/harness/config/hooks.py`
- CREATE: `src/harness/models/skill.py`
- MODIFY: `src/harness/agents/base.py` (hook wiring)
- MODIFY: `src/harness/runner.py` (AGENTS.md + skill + hook loading)
- CREATE: `tests/python/test_agents_md.py`
- CREATE: `tests/python/test_skills.py`
- CREATE: `tests/python/test_hooks.py`

### Phase C
- MODIFY: `src/harness/tools/worker_tools.py` (background_task, check_background)
- MODIFY: `src/harness/tools/planner_tools.py` (add to WORKER_TOOL_SPECS)
- MODIFY: `src/harness/config/settings.py` (model role fields)
- MODIFY: `src/harness/runner.py` (model routing)
- CREATE: `tests/python/test_background_tasks.py`
- CREATE: `tests/python/test_model_roles.py`

### Phase D
- CREATE: `src/harness/tools/browser_tool.py`
- MODIFY: `src/harness/tools/planner_tools.py` (add browser to WORKER_TOOL_SPECS)
- MODIFY: `src/harness/runner.py` (register browser tool)
- CREATE: `tests/python/test_browser_tool.py`

### Phase E
- CREATE: `src/harness_core/src/grep.rs`
- CREATE: `src/harness_core/src/glob.rs`
- CREATE: `src/harness_core/src/shell.rs`
- MODIFY: `src/harness_core/src/lib.rs` (register new modules)
- MODIFY: `src/harness_core/Cargo.toml` (add dependencies)
- MODIFY: `src/harness/tools/worker_tools.py` (HAS_RUST fallback wiring)
- CREATE: `tests/python/test_rust_grep.py`
- CREATE: `tests/python/test_rust_glob.py`

### Phase F
- CREATE: `src/harness/agents/ttsr.py`
- CREATE: `src/harness/config/discovery.py`
- CREATE: `src/harness/tools/git_tools.py`
- CREATE: `src/harness/tools/web_tools.py`
- MODIFY: `src/harness/agents/base.py` (TTSR wiring)
- MODIFY: `src/harness/runner.py` (discovery, git/web tool registration)
- CREATE: `tests/python/test_ttsr.py`
- CREATE: `tests/python/test_discovery.py`
- CREATE: `tests/python/test_git_tools.py`
- CREATE: `tests/python/test_web_tools.py`

### Phase G
- CREATE: `src/harness/tools/skill_tools.py`
- MODIFY: `src/harness/config/skills.py` (SkillRegistry, matching, validation)
- CREATE: `src/harness/skills/harness-conventions/SKILL.md`
- CREATE: `src/harness/skills/code-review/SKILL.md`
- CREATE: `src/harness/skills/test-writing/SKILL.md`
- CREATE: `src/harness/skills/git-workflow/SKILL.md`
- CREATE: `src/harness/skills/debugging/SKILL.md`
- MODIFY: `src/harness/agents/base.py` (skill injection points)
- MODIFY: `src/harness/agents/planner.py` (skill-directed spawning)
- MODIFY: `src/harness/runner.py` (skill tool registration)
- CREATE: `tests/python/test_skill_tools.py`
- CREATE: `tests/python/test_skill_registry.py`
- CREATE: `tests/python/test_built_in_skills.py`

### Phase H
- MODIFY: `src/harness/agents/base.py` (self-reflection, identity, alignment, pivot)
- CREATE: `src/harness/prompts/worker.md`
- CREATE: `src/harness/prompts/planner.md`
- CREATE: `src/harness/prompts/sub_planner.md`
- CREATE: `src/harness/prompts/watchdog.md`
- MODIFY: `src/harness/runner.py` (load prompt files)
- MODIFY: `src/harness/config/settings.py` (freshness config fields)
- CREATE: `tests/python/test_freshness.py`
- CREATE: `tests/python/test_prompts.py`

### Phase I
- CREATE: `src/harness/models/task_spec.py`
- CREATE: `src/harness/config/intent.py`
- CREATE: `src/harness/config/intent_templates.py`
- MODIFY: `src/harness/tools/planner_tools.py` (TaskSpec in create_task)
- MODIFY: `src/harness/agents/worker.py` (TaskSpec in system prompt)
- CREATE: `tests/python/test_task_spec.py`
- CREATE: `tests/python/test_intent.py`

### Phase J
- CREATE: `src/harness/observability/activity_log.py`
- CREATE: `src/harness/observability/cost_tracker.py`
- CREATE: `src/harness/observability/resource_bounds.py`
- CREATE: `src/harness/observability/metrics.py`
- CREATE: `src/harness/orchestration/pool_scaler.py`
- CREATE: `src/harness/orchestration/circuit_breaker.py`
- MODIFY: `src/harness/agents/base.py` (activity logging wiring)
- MODIFY: `src/harness/agents/planner.py` (partial failure recovery)
- MODIFY: `src/harness/rendering.py` (metrics dashboard panel)
- MODIFY: `src/harness/config/settings.py` (J config fields)
- CREATE: `tests/python/test_activity_log.py`
- CREATE: `tests/python/test_cost_tracker.py`
- CREATE: `tests/python/test_resource_bounds.py`
- CREATE: `tests/python/test_pool_scaler.py`
- CREATE: `tests/python/test_circuit_breaker.py`
- CREATE: `tests/python/test_metrics.py`

---

## Config Changes

### pyproject.toml additions
```toml
[project.optional-dependencies]
browser = ["playwright>=1.40"]
web = ["httpx>=0.25", "markdownify>=0.11"]
```

### Cargo.toml additions (Phase E)
```toml
grep-regex = "0.1"
grep-searcher = "0.1"
grep-matcher = "0.1"
globset = "0.4"
ignore = "0.4"
# brush-core and brush-builtins vendored in crates/
```

### CLAUDE.md updates
After each phase: update implementation status, add new commands, update test count.
