# Harness Testing Strategy

## Philosophy

Every layer of the harness must be testable in isolation before integration. We follow an incremental approach:

```
Layer 0: Models (pure pydantic — no I/O, no LLM)
Layer 1: Config (pydantic-settings — .env loading)
Layer 2: Tools (tool handlers — filesystem/subprocess)
Layer 3: Git (workspace creation, diff, merge — real git)
Layer 4: Agent loop (LLM integration — mocked or real)
Layer 4.5: Coherence (state after compression — scratchpad, snapshot)
Layer 4.6: Confusion regression (idempotency, completion gate)
Layer 5: Orchestration (multi-agent coordination)
Layer 5.5: Endurance (long-horizon orchestration, loop bounds)
Layer 5.6: Chaos (injected failures, race conditions)
Layer 6: End-to-end (full harness run)
```

Each layer depends only on layers below it. Tests at each layer mock the layer above.

## Test Pyramid

```
         ╱╲
        ╱  ╲         Layer 6: E2E (1-2 tests, real LLM, slow)
       ╱    ╲
      ╱──────╲       Layer 5.6: Chaos (2-3 tests, injected failures)
     ╱        ╲
    ╱──────────╲     Layer 5.5: Endurance (3-4 tests, long-horizon)
   ╱            ╲
  ╱──────────────╲   Layer 5: Orchestration (5-10 tests, mocked LLM)
 ╱                ╲
╱──────────────────╲ Layer 4.6: Confusion regression (5-6 tests)
╱                    ╲
╱────────────────────╲ Layer 4.5: Coherence (4-5 tests, compression)
/                      ╲
/──────────────────────╲ Layer 4: Agent loop (10-15 tests, mocked LLM)
╱                        ╲
╱────────────────────────╲   Layer 3: Git/Tools (15-20 tests, real filesystem)
╱                          ╲
╱──────────────────────────╲ Layer 0-2: Models/Config (30+ tests, pure logic)
```

The base is fast, pure, and numerous. The top is slow, real, and sparse. Most bugs should be caught at layers 0-3.

## Layer 0: Model Tests (Pure Pydantic)

Zero I/O, zero mocking. These test pydantic model validation, serialization, and business logic.

### What to test
- Model construction with valid data
- Validation errors with invalid data
- Serialization round-trips (model -> dict -> model)
- Enum values and constraints
- Default values and factory functions
- Computed properties (e.g., ErrorBudget.failure_rate)
- Model relationships (Task references, Handoff contains FileDiff)

### Example patterns

```python
import pytest
from harness.models.task import Task, TaskStatus, TaskPriority
from harness.models.handoff import Handoff, HandoffStatus, HandoffMetrics, FileDiff
from harness.models.agent import AgentConfig, AgentRole


class TestTaskModel:
    def test_task_defaults(self):
        task = Task(id="t1", title="Fix bug", description="Fix the login bug")
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.NORMAL
        assert task.assigned_to is None
        assert task.blocked_by == []

    def test_task_blocked_by_validation(self):
        task = Task(
            id="t2", title="Deploy", description="Deploy after fix",
            blocked_by=["t1"]
        )
        assert "t1" in task.blocked_by

    def test_task_serialization_roundtrip(self):
        task = Task(id="t1", title="Test", description="Test task")
        data = task.model_dump()
        restored = Task.model_validate(data)
        assert restored == task

    def test_task_json_roundtrip(self):
        task = Task(id="t1", title="Test", description="Test task")
        json_str = task.model_dump_json()
        restored = Task.model_validate_json(json_str)
        assert restored.id == task.id


class TestHandoffModel:
    def test_handoff_requires_narrative(self):
        metrics = HandoffMetrics(
            wall_time_seconds=10.0, tokens_used=500,
            attempts=1, files_modified=2
        )
        handoff = Handoff(
            agent_id="w1", task_id="t1",
            status=HandoffStatus.SUCCESS,
            narrative="Implemented login fix. Changed auth.py and tests.",
            metrics=metrics,
        )
        assert handoff.narrative != ""

    def test_handoff_with_diffs(self):
        diff = FileDiff(path="src/auth.py", diff_text="- old\n+ new")
        handoff = Handoff(
            agent_id="w1", task_id="t1",
            status=HandoffStatus.SUCCESS,
            narrative="Fixed auth",
            diffs=[diff],
            metrics=HandoffMetrics(
                wall_time_seconds=5.0, tokens_used=200,
                attempts=1, files_modified=1
            ),
        )
        assert len(handoff.diffs) == 1
        assert handoff.diffs[0].path == "src/auth.py"


class TestErrorBudget:
    def test_healthy_zone(self):
        from harness.models.error_budget import ErrorBudget, ErrorZone
        budget = ErrorBudget(window_size=10, budget_percentage=0.2)
        for _ in range(10):
            budget.record(True)
        assert budget.zone == ErrorZone.HEALTHY
        assert budget.failure_rate == 0.0

    def test_critical_zone(self):
        from harness.models.error_budget import ErrorBudget, ErrorZone
        budget = ErrorBudget(window_size=10, budget_percentage=0.2)
        for _ in range(8):
            budget.record(True)
        for _ in range(4):
            budget.record(False)
        assert budget.zone == ErrorZone.CRITICAL

    def test_sliding_window(self):
        from harness.models.error_budget import ErrorBudget
        budget = ErrorBudget(window_size=5, budget_percentage=0.5)
        for _ in range(5):
            budget.record(False)
        assert budget.failure_rate == 1.0
        for _ in range(5):
            budget.record(True)
        assert budget.failure_rate == 0.0
```

### Run command
```bash
uv run pytest tests/python/test_models.py -v
```

## Layer 1: Config Tests

Test that pydantic-settings correctly loads from .env files and environment variables.

### What to test
- Default values when no .env present
- Loading from .env file
- Environment variable overrides
- Nested config (LLM, Workspace, etc.)
- Validation errors for invalid config values
- Type coercion (string "10" -> int 10)

### Example patterns

```python
import os
import pytest
from pathlib import Path


class TestHarnessConfig:
    def test_defaults(self):
        from harness.config import HarnessConfig
        config = HarnessConfig(llm={"api_key": "test-key"})
        assert config.agents.max_workers == 10
        assert config.agents.max_depth == 3
        assert config.errors.budget_percentage == 0.15
        assert config.watchdog.enabled is True

    def test_from_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("LLM_API_KEY=sk-test\nAGENT_MAX_WORKERS=20\n")
        config = HarnessConfig(_env_file=str(env_file))
        assert config.llm.api_key == "sk-test"
        assert config.agents.max_workers == 20

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
        monkeypatch.setenv("AGENT_MAX_WORKERS", "50")
        from harness.config import HarnessConfig
        config = HarnessConfig()
        assert config.llm.api_key == "sk-from-env"
        assert config.agents.max_workers == 50

    def test_invalid_budget_percentage(self):
        from harness.config import ErrorPolicyConfig
        with pytest.raises(Exception):
            ErrorPolicyConfig(budget_percentage=2.0)  # > 1.0 should fail
```

### Run command
```bash
uv run pytest tests/python/test_config.py -v
```

## Layer 2: Tool Handler Tests

Test individual tool handlers with real filesystem operations but no LLM.

### What to test
- bash tool: command execution, exit codes, stderr capture
- read_file: existing files, missing files, offset/limit
- write_file: create new, overwrite existing
- edit_file: find and replace, missing old_string
- submit_handoff: builds correct Handoff model
- Tool registry: correct tools registered per role

### Mock boundary
- No LLM calls
- Real filesystem (use pytest tmp_path)
- Real subprocess for bash tool

### Example patterns

```python
import pytest


class TestBashTool:
    def test_echo(self):
        from harness.tools.worker_tools import bash_handler
        result = bash_handler(command="echo hello")
        assert "hello" in result["stdout"]
        assert result["exit_code"] == 0

    def test_failing_command(self):
        from harness.tools.worker_tools import bash_handler
        result = bash_handler(command="exit 1")
        assert result["exit_code"] == 1

    def test_stderr_capture(self):
        from harness.tools.worker_tools import bash_handler
        result = bash_handler(command="echo err >&2")
        assert "err" in result["stderr"]


class TestFileTools:
    def test_write_and_read(self, tmp_path):
        from harness.tools.worker_tools import write_file_handler, read_file_handler
        target = tmp_path / "test.txt"
        write_file_handler(path=str(target), content="hello world")
        result = read_file_handler(path=str(target))
        assert "hello world" in result

    def test_edit_file(self, tmp_path):
        from harness.tools.worker_tools import write_file_handler, edit_file_handler
        target = tmp_path / "test.txt"
        write_file_handler(path=str(target), content="foo bar baz")
        edit_file_handler(path=str(target), old_string="bar", new_string="qux")
        assert "foo qux baz" in target.read_text()

    def test_read_missing_file(self, tmp_path):
        from harness.tools.worker_tools import read_file_handler
        result = read_file_handler(path=str(tmp_path / "missing.txt"))
        assert "error" in result.lower() or "not found" in result.lower()


class TestToolRegistry:
    def test_planner_tools_exclude_code_tools(self):
        from harness.tools.registry import get_tools_for_role
        from harness.models.agent import AgentRole
        tools = get_tools_for_role(AgentRole.ROOT_PLANNER)
        tool_names = [t["name"] for t in tools]
        assert "spawn_worker" in tool_names
        assert "bash" not in tool_names
        assert "write_file" not in tool_names

    def test_worker_tools_exclude_spawn(self):
        from harness.tools.registry import get_tools_for_role
        from harness.models.agent import AgentRole
        tools = get_tools_for_role(AgentRole.WORKER)
        tool_names = [t["name"] for t in tools]
        assert "bash" in tool_names
        assert "spawn_worker" not in tool_names
        assert "spawn_sub_planner" not in tool_names
```

### Run command
```bash
uv run pytest tests/python/test_tools.py -v
```

## Layer 3: Git and Workspace Tests

Test workspace creation, diff computation, and merge logic with real git operations.

### What to test
- Workspace creation (copy or worktree)
- File isolation between workspaces
- Diff computation against canonical
- 3-way merge: clean apply
- 3-way merge: conflict detection
- Fix-forward task generation from conflicts
- Workspace cleanup

### Mock boundary
- Real git, real filesystem (use pytest tmp_path with git init)
- No LLM calls
- No agent logic

### Example patterns

```python
import subprocess
import pytest
from pathlib import Path


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "main.py").write_text("def hello():\n    return 'hello'\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return repo


class TestWorkspaceCreation:
    def test_create_workspace(self, git_repo, tmp_path):
        from harness.git.workspace import create_workspace
        ws = create_workspace(
            repo_path=str(git_repo),
            worker_id="w1",
            workspaces_root=str(tmp_path / "workspaces")
        )
        assert Path(ws.workspace_path).exists()
        assert (Path(ws.workspace_path) / "main.py").exists()

    def test_workspace_isolation(self, git_repo, tmp_path):
        from harness.git.workspace import create_workspace
        ws1 = create_workspace(str(git_repo), "w1", str(tmp_path / "ws"))
        ws2 = create_workspace(str(git_repo), "w2", str(tmp_path / "ws"))
        (Path(ws1.workspace_path) / "main.py").write_text("modified by w1")
        content_w2 = (Path(ws2.workspace_path) / "main.py").read_text()
        assert "modified by w1" not in content_w2


class TestDiffComputation:
    def test_detect_changes(self, git_repo, tmp_path):
        from harness.git.workspace import create_workspace, compute_diff
        ws = create_workspace(str(git_repo), "w1", str(tmp_path / "ws"))
        (Path(ws.workspace_path) / "main.py").write_text("def hello():\n    return 'world'\n")
        diffs = compute_diff(ws)
        assert len(diffs) >= 1
        assert any(d.path == "main.py" for d in diffs)

    def test_no_changes(self, git_repo, tmp_path):
        from harness.git.workspace import create_workspace, compute_diff
        ws = create_workspace(str(git_repo), "w1", str(tmp_path / "ws"))
        diffs = compute_diff(ws)
        assert len(diffs) == 0


class TestMerge:
    def test_clean_merge(self, git_repo, tmp_path):
        from harness.git.workspace import create_workspace
        from harness.orchestration.merge import optimistic_merge
        ws = create_workspace(str(git_repo), "w1", str(tmp_path / "ws"))
        (Path(ws.workspace_path) / "new_file.py").write_text("new content")
        result = optimistic_merge(ws, str(git_repo))
        assert result.status.value == "clean"

    def test_conflict_generates_fix_task(self, git_repo, tmp_path):
        from harness.git.workspace import create_workspace
        from harness.orchestration.merge import optimistic_merge
        ws = create_workspace(str(git_repo), "w1", str(tmp_path / "ws"))
        # Modify same file in both canonical and workspace
        (git_repo / "main.py").write_text("canonical change")
        (Path(ws.workspace_path) / "main.py").write_text("worker change")
        result = optimistic_merge(ws, str(git_repo))
        assert result.status.value == "conflict"
        assert result.fix_forward_task is not None
```

### Run command
```bash
uv run pytest tests/python/test_git.py -v
```

### Layer 3.5: Structured Output (Pydantic + Instructor)

Tests that pydantic models correctly validate and reject structured LLM outputs.
These sit between tool tests (Layer 3) and agent loop tests (Layer 4) because
structured output validation happens at the boundary between tool execution
and agent decision-making.

What to test:
- Handoff model validates required fields and rejects invalid status values
- ScratchpadSchema enforces non-empty required sections
- PlannerDecision model (when implemented) validates action enums
- Instructor extraction produces valid model instances from LLM responses (requires mocked LLM)

What to mock:
- LLM responses (for instructor extraction tests)
- Nothing else — these test pure validation logic

Test file: tests/python/test_structured_output.py

## Layer 4: Agent Loop Tests (Mocked LLM)

Test the agent loop mechanics with a mocked Anthropic client. This verifies the loop control flow without spending real tokens.

### What to test
- Loop exits when stop_reason != "tool_use"
- Tool calls dispatched correctly
- Tool results appended to messages
- Context compression triggers at threshold
- Scratchpad rewrite triggers at interval
- Identity re-injection after compression
- Token budget enforcement (agent stops when budget exceeded)
- Timeout enforcement

### Mock boundary
- Mock anthropic.Anthropic client (return scripted responses)
- Real tool handlers (filesystem tools use tmp_path)
- Real scratchpad logic

### Example patterns

```python
import pytest
from unittest.mock import MagicMock, patch


def make_mock_response(content_blocks, stop_reason="end_turn", input_tokens=100, output_tokens=50):
    """Create a mock Anthropic response."""
    response = MagicMock()
    response.content = content_blocks
    response.stop_reason = stop_reason
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    return response


def make_text_block(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def make_tool_use_block(tool_id, name, input_data):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = input_data
    return block


class TestAgentLoop:
    def test_loop_exits_on_end_turn(self):
        from harness.agents.base import BaseAgent
        mock_client = MagicMock()
        mock_client.messages.create.return_value = make_mock_response(
            [make_text_block("Done!")], stop_reason="end_turn"
        )
        agent = BaseAgent(client=mock_client, config=mock_agent_config())
        agent.run()
        assert mock_client.messages.create.call_count == 1

    def test_loop_executes_tool_and_continues(self):
        from harness.agents.base import BaseAgent
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            make_mock_response(
                [make_tool_use_block("t1", "bash", {"command": "echo hi"})],
                stop_reason="tool_use"
            ),
            make_mock_response(
                [make_text_block("All done")],
                stop_reason="end_turn"
            ),
        ]
        agent = BaseAgent(client=mock_client, config=mock_agent_config())
        agent.run()
        assert mock_client.messages.create.call_count == 2

    def test_token_budget_enforcement(self):
        from harness.agents.base import BaseAgent
        mock_client = MagicMock()
        mock_client.messages.create.return_value = make_mock_response(
            [make_tool_use_block("t1", "bash", {"command": "echo"})],
            stop_reason="tool_use",
            input_tokens=50_000, output_tokens=50_001
        )
        config = mock_agent_config()
        config.token_budget = 100_000
        agent = BaseAgent(client=mock_client, config=config)
        agent.run()
        # Agent should stop after exceeding budget
        assert agent.state.value == "completed" or agent.state.value == "failed"
```

### Run command
```bash
uv run pytest tests/python/test_agent_loop.py -v
```

## Layer 5: Orchestration Tests (Mocked LLM)

Test multi-agent coordination with mocked LLM responses. This verifies scheduling, handoff processing, error budget, merge, and watchdog.

### What to test
- Scheduler dispatches tasks to available workers
- Handoff received and processed by planner
- Error budget transitions (HEALTHY -> WARNING -> CRITICAL)
- Watchdog detects zombie agents
- Watchdog detects tunnel vision
- Optimistic merge called on accepted handoffs
- Reconciliation loop runs test command and parses failures
- Multi-repo task assignment

### Mock boundary
- Mock LLM client
- Mock worker execution (return scripted Handoff objects)
- Real scheduling, error budget, watchdog logic
- Real merge logic (with git_repo fixture)

### Example patterns

```python
class TestScheduler:
    def test_dispatches_pending_tasks(self):
        from harness.orchestration.scheduler import Scheduler
        from harness.models.task import Task
        scheduler = Scheduler(max_workers=3)
        scheduler.add_task(Task(id="t1", title="A", description="do A"))
        scheduler.add_task(Task(id="t2", title="B", description="do B"))
        ready = scheduler.get_ready_tasks()
        assert len(ready) == 2

    def test_respects_blocked_by(self):
        from harness.orchestration.scheduler import Scheduler
        from harness.models.task import Task
        scheduler = Scheduler(max_workers=3)
        scheduler.add_task(Task(id="t1", title="A", description="do A"))
        scheduler.add_task(Task(id="t2", title="B", description="do B", blocked_by=["t1"]))
        ready = scheduler.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "t1"


class TestWatchdog:
    def test_detects_zombie(self):
        from harness.agents.watchdog import Watchdog
        from harness.models.watchdog import ActivityEntry
        wd = Watchdog(zombie_timeout_seconds=5)
        # Simulate agent with stale heartbeat
        wd.record_activity(ActivityEntry(
            event_type="heartbeat", agent_id="w1",
            timestamp=datetime.now() - timedelta(seconds=60)
        ))
        events = wd.check_agents()
        assert any(e.failure_mode.value == "zombie" for e in events)

    def test_detects_tunnel_vision(self):
        from harness.agents.watchdog import Watchdog
        from harness.models.watchdog import ActivityEntry
        wd = Watchdog(tunnel_vision_threshold=5)
        for _ in range(10):
            wd.record_activity(ActivityEntry(
                event_type="tool_use", agent_id="w1",
                files_touched=["src/same_file.py"]
            ))
        events = wd.check_agents()
        assert any(e.failure_mode.value == "tunnel_vision" for e in events)


class TestReconciliation:
    def test_green_on_first_try(self, git_repo):
        from harness.orchestration.reconcile import reconcile
        report = reconcile(
            repo_path=str(git_repo),
            test_command="exit 0",
            max_rounds=3
        )
        assert report.final_verdict == "pass"
        assert len(report.rounds) == 1

    def test_fixers_spawned_on_failure(self, git_repo):
        from harness.orchestration.reconcile import reconcile
        report = reconcile(
            repo_path=str(git_repo),
            test_command="echo 'FAILED test_auth' && exit 1",
            max_rounds=1,
            spawn_fixer=mock_fixer_that_succeeds
        )
        assert report.rounds[0].fixers_spawned >= 1
```

### Run command
```bash
uv run pytest tests/python/test_orchestration.py -v
```

## Layer 6: End-to-End Tests (Real LLM)

Minimal E2E tests that use real LLM calls. These are slow, expensive, and gated behind a marker.

### What to test
- Single worker completes a simple task (write a file)
- Planner decomposes a 2-task problem and delegates to workers
- Full harness run with 1 repo, 2 tasks, reconciliation

### Guard
```python
import os
import pytest

requires_api_key = pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY"),
    reason="LLM_API_KEY not set — skipping E2E tests"
)
```

### Example patterns

```python
@requires_api_key
class TestE2E:
    def test_single_worker_writes_file(self, git_repo, tmp_path):
        from harness.config import HarnessConfig
        from harness.agents.worker import Worker
        config = HarnessConfig(
            repos=[str(git_repo)],
            workspace={"root_dir": str(tmp_path / "ws")}
        )
        worker = Worker(config=config, task=Task(
            id="t1", title="Create hello.py",
            description="Create a file hello.py that prints 'hello world'",
            repo=str(git_repo)
        ))
        handoff = worker.run()
        assert handoff.status in (HandoffStatus.SUCCESS, HandoffStatus.PARTIAL_FAILURE)
        assert any("hello" in d.path for d in handoff.diffs)
```

### Run commands
```bash
# Skip E2E by default
uv run pytest tests/python/ -v -m "not e2e"

# Run E2E (requires API key)
LLM_API_KEY=sk-ant-xxx uv run pytest tests/python/ -v -m e2e
```

## Layer 4.5: Coherence Tests (State After Compression)

Test that state survives context compression cycles. These verify the scratchpad and snapshot mechanisms maintain accuracy across multiple compression rounds.

### What to test
- StateSnapshot accurately reflects runtime state before compression
- After auto_compact + state injection, planner can reconstruct worker list
- After 3 compression cycles, task board state is still accurate
- Scratchpad content matches actual system state post-compression
- Compression count increments correctly

### Mock boundary
- Mock LLM client (return scripted compress summary)
- Real StateSnapshot serialization
- Real scratchpad validation
- Simulated worker states (inject WorkerAgentRuntime objects)

### Example patterns

```python
import pytest
from unittest.mock import MagicMock
from datetime import datetime


class TestStateSnapshot:
    def test_state_snapshot_captures_active_workers(self):
        from harness.orchestration.state import StateSnapshot
        from harness.models.agent import AgentState
        
        # Create mock worker runtimes
        worker1 = MagicMock()
        worker1.agent_id = "w1"
        worker1.state = AgentState.RUNNING
        worker1.current_task_id = "t1"
        
        worker2 = MagicMock()
        worker2.agent_id = "w2"
        worker2.state = AgentState.RUNNING
        worker2.current_task_id = "t2"
        
        worker3 = MagicMock()
        worker3.agent_id = "w3"
        worker3.state = AgentState.IDLE
        worker3.current_task_id = None
        
        # Build snapshot
        snapshot = StateSnapshot()
        snapshot.capture_workers([worker1, worker2, worker3])
        
        # Verify all 3 appear in snapshot
        assert len(snapshot.workers) == 3
        assert snapshot.workers["w1"].current_task_id == "t1"
        assert snapshot.workers["w2"].current_task_id == "t2"
        assert snapshot.workers["w3"].current_task_id is None

    def test_snapshot_survives_compression(self):
        from harness.orchestration.state import StateSnapshot
        from harness.orchestration.compression import auto_compact
        
        snapshot = StateSnapshot()
        snapshot.capture_workers([MagicMock(agent_id="w1", state="RUNNING", current_task_id="t1")])
        snapshot.capture_tasks([{"id": "t1", "title": "Test", "status": "in_progress"}])
        
        # Simulate auto_compact
        compressed_messages = auto_compact(
            messages=[],
            snapshot=snapshot,
            client=MagicMock()
        )
        
        # Verify snapshot JSON is in compressed messages
        snapshot_json = snapshot.model_dump_json()
        assert snapshot_json in str(compressed_messages) or "StateSnapshot" in str(compressed_messages)

    def test_scratchpad_validated_against_schema(self):
        from harness.orchestration.scratchpad import Scratchpad, ScratchpadValidationError
        
        # Write scratchpad missing "## Active Workers"
        bad_scratchpad = """# Project Status

## Tasks
- t1: in_progress

## Completed
- t2: done
"""
        scratchpad = Scratchpad()
        
        # Should reject due to missing Active Workers section
        with pytest.raises(ScratchpadValidationError):
            scratchpad.validate(bad_scratchpad)

    def test_three_compression_cycles_maintain_accuracy(self):
        from harness.orchestration.state import StateSnapshot
        from harness.orchestration.compression import run_compression_cycle
        
        # Initial state with 2 workers
        workers = [
            MagicMock(agent_id="w1", state="RUNNING", current_task_id="t1"),
            MagicMock(agent_id="w2", state="RUNNING", current_task_id="t2"),
        ]
        snapshot = StateSnapshot()
        
        # Simulate 3 compression cycles with changing worker states
        for cycle in range(3):
            snapshot.capture_workers(workers)
            
            # Simulate state change between cycles
            workers[0].current_task_id = f"t{cycle + 10}"
            
            # Run compression (mocked)
            run_compression_cycle(snapshot, client=MagicMock())
        
        # Verify final snapshot still accurate
        assert snapshot.workers["w1"].current_task_id == "t12"
        assert snapshot.workers["w2"].current_task_id == "t2"

    def test_compression_count_tracks_cycles(self):
        from harness.orchestration.compression import CompressionTracker
        
        tracker = CompressionTracker()
        
        assert tracker.compression_count == 0
        tracker.increment()
        assert tracker.compression_count == 1
        tracker.increment()
        tracker.increment()
        assert tracker.compression_count == 3
```

### Run command
```bash
uv run pytest tests/python/test_coherence.py -v
```

## Layer 4.6: Confusion Regression Tests

Test idempotency guards and completion gates that prevent common planner confusion patterns.

### What to test
- Planner cannot re-spawn worker for task with completed handoff (idempotency)
- Planner cannot merge same handoff twice
- Planner cannot create duplicate tasks (same title+description)
- Planner cannot exit loop with workers still running (completion gate)
- Planner cannot exit loop with unmerged handoffs
- Inspection-only loop detection triggers after 4 rounds
- Stalled progress detection triggers after 6 rounds

### Mock boundary
- Mock LLM client (return scripted tool calls that trigger each confusion pattern)
- Real idempotency guards, completion gate, stall detection

### Example patterns

```python
import pytest
from unittest.mock import MagicMock


class TestIdempotencyGuards:
    def test_reject_duplicate_worker_spawn(self):
        from harness.orchestration.planner import Planner
        from harness.models.handoff import HandoffStatus
        
        planner = Planner()
        
        # Complete a task first
        planner.on_handoff_received(MagicMock(
            task_id="t1",
            status=HandoffStatus.SUCCESS
        ))
        
        # Attempt to re-spawn worker for completed task
        result = planner.spawn_worker(task_id="t1")
        
        # Should reject
        assert result.rejected is True
        assert "already completed" in result.reason.lower()

    def test_reject_duplicate_merge(self):
        from harness.orchestration.merge import MergeGuard
        
        guard = MergeGuard()
        handoff = MagicMock()
        handoff.id = "h1"
        
        # First merge succeeds
        result1 = guard.try_merge(handoff)
        assert result1.success is True
        
        # Second merge should reject
        result2 = guard.try_merge(handoff)
        assert result2.success is False
        assert "already merged" in result2.reason.lower()

    def test_reject_duplicate_task_creation(self):
        from harness.orchestration.planner import Planner
        
        planner = Planner()
        
        # Create initial task
        task1 = planner.create_task(
            title="Fix auth",
            description="Fix the login bug"
        )
        
        # Attempt duplicate
        task2 = planner.create_task(
            title="Fix auth",
            description="Fix the login bug"
        )
        
        # Should reject
        assert task2 is None or task2.rejected is True


class TestCompletionGate:
    def test_completion_gate_blocks_with_running_workers(self):
        from harness.orchestration.planner import CompletionGate
        from harness.models.agent import AgentState
        
        gate = CompletionGate()
        
        # Simulate running workers
        workers = [
            MagicMock(agent_id="w1", state=AgentState.RUNNING),
            MagicMock(agent_id="w2", state=AgentState.RUNNING),
        ]
        
        # Should block completion
        result = gate.declare_done(workers=workers, handoffs=[])
        assert result.blocked is True
        assert "running workers" in result.reason.lower()

    def test_completion_gate_blocks_with_pending_handoffs(self):
        from harness.orchestration.planner import CompletionGate
        
        gate = CompletionGate()
        
        # Simulate unmerged handoffs
        handoffs = [
            MagicMock(id="h1", merged=False),
            MagicMock(id="h2", merged=False),
        ]
        
        # Should block completion
        result = gate.declare_done(workers=[], handoffs=handoffs)
        assert result.blocked is True
        assert "unmerged" in result.reason.lower()


class TestStallDetection:
    def test_inspection_loop_detection(self):
        from harness.orchestration.watchdog import InspectionLoopDetector
        
        detector = InspectionLoopDetector(threshold=4)
        
        # Simulate 4 rounds of only list_workers calls
        for _ in range(4):
            detector.record_action("list_workers", {})
        
        # Should trigger detection
        assert detector.is_inspection_loop() is True

    def test_stalled_progress_detection(self):
        from harness.orchestration.watchdog import ProgressStallDetector
        
        detector = ProgressStallDetector(threshold=6)
        
        # Simulate 6 rounds with no task completion
        for _ in range(6):
            detector.record_round(actions=[], completions=0)
        
        # Should trigger stall detection
        assert detector.is_stalled() is True
```

### Run command
```bash
uv run pytest tests/python/test_confusion_regression.py -v
```

## Layer 5.5: Endurance Tests

Test long-horizon orchestration with many tasks and many planner turns. These catch drift and state corruption that only appear over extended runs.

### What to test
- 20-task orchestration over 50+ planner turns completes correctly
- Multiple compression cycles maintain coherent task tracking
- Worker failures mid-execution trigger proper re-queuing
- Error budget transitions through HEALTHY -> WARNING -> CRITICAL -> recovery
- Planner loop bounds (max_turns, max_wall_time) trigger graceful shutdown
- Final task board state matches expected outcomes after full orchestration

### Mock boundary
- Mock LLM client with scripted multi-turn responses (planner and workers)
- Real scheduling, merge, error budget, watchdog, reconciliation
- Real git operations (git_repo fixture)
- Synthetic time progression for timeout tests

### Example patterns

```python
import pytest
from unittest.mock import MagicMock
from datetime import timedelta


class TestLongHorizonOrchestration:
    def test_twenty_task_orchestration(self):
        from harness.orchestration.planner import Planner
        from harness.orchestration.scheduler import Scheduler
        from harness.models.task import Task, TaskStatus
        
        # Create 20 tasks with dependencies
        tasks = []
        for i in range(20):
            blocked_by = [f"t{i-1}"] if i > 0 else []
            tasks.append(Task(
                id=f"t{i}",
                title=f"Task {i}",
                description=f"Do task {i}",
                blocked_by=blocked_by
            ))
        
        # Run full orchestration with mocked LLM
        planner = Planner()
        scheduler = Scheduler(max_workers=5)
        
        for task in tasks:
            scheduler.add_task(task)
        
        # Mock LLM responses for 50+ turns
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = self._make_orchestration_responses()
        
        # Run loop
        results = planner.run_loop(
            tasks=tasks,
            scheduler=scheduler,
            client=mock_client,
            max_turns=60
        )
        
        # Verify all completed
        assert len([t for t in tasks if t.status == TaskStatus.COMPLETED]) == 20

    def test_loop_bound_triggers_reconcile(self):
        from harness.orchestration.planner import Planner
        from harness.orchestration.reconcile import ReconciliationTrigger
        
        planner = Planner(max_planner_turns=10)
        trigger = ReconciliationTrigger()
        
        # Run with hit loop bound
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(type="text", text="Continuing...")],
            stop_reason="tool_use"
        )
        
        turn_count = 0
        while turn_count < 15:
            turn_count += 1
            if not planner.should_continue(turn_count):
                break
        
        # Should have triggered reconciliation
        assert turn_count == 10
        assert trigger.should_reconcile(turn_count=turn_count, reason="loop_bound") is True

    def test_error_budget_recovery(self):
        from harness.models.error_budget import ErrorBudget, ErrorZone
        
        budget = ErrorBudget(window_size=10, budget_percentage=0.2)
        
        # Push to CRITICAL with failures
        for _ in range(8):
            budget.record(False)
        
        assert budget.zone == ErrorZone.CRITICAL
        
        # Recover with successes
        for _ in range(10):
            budget.record(True)
        
        assert budget.zone == ErrorZone.HEALTHY

    def test_worker_failure_requeue(self):
        from harness.orchestration.scheduler import Scheduler
        from harness.models.task import Task, TaskStatus
        
        scheduler = Scheduler(max_workers=3)
        task = Task(id="t1", title="Test", description="Test task")
        scheduler.add_task(task)
        
        # Simulate worker crash
        def simulate_crash():
            raise RuntimeError("Worker crashed")
        
        # Attempt execution, catch failure
        try:
            simulate_crash()
        except RuntimeError:
            # Verify task re-queued
            scheduler.requeue_on_failure(task.id)
        
        ready = scheduler.get_ready_tasks()
        assert any(t.id == "t1" for t in ready)


class TestLoopBounds:
    def test_wall_time_bound_triggers(self):
        from harness.orchestration.planner import Planner
        import time
        
        planner = Planner(max_wall_time_seconds=0)  # Immediate timeout
        
        start = time.time()
        result = planner.run_with_wall_bound(
            client=MagicMock(),
            tasks=[],
            max_wall_time_seconds=0
        )
        elapsed = time.time() - start
        
        assert result.timed_out is True
        assert elapsed < 1.0  # Should have triggered immediately
```

### Run command
```bash
uv run pytest tests/python/test_endurance.py -v -m "not e2e"
```

## Layer 5.6: Chaos Tests

Test system resilience under failure conditions. Inject failures at runtime to verify graceful degradation.

### What to test
- Worker thread crash mid-execution: handoff auto-submitted with FAILED status
- Workspace deleted during merge: merge returns error, fix-forward task spawned
- Corrupt handoff data (missing fields): system rejects gracefully
- Two workers modifying same file: optimistic merge handles conflict
- Watchdog kills worker: worker replaced, task continues
- Out-of-order handoff arrivals: planner processes correctly regardless of order

### Mock boundary
- Mock LLM client
- Real filesystem with injected failures (monkeypatch)
- Real threading with forced interruptions
- Real merge with synthetic conflicts

### Example patterns

```python
import pytest
import threading
import shutil
from pathlib import Path
from unittest.mock import patch


class TestWorkerCrashHandling:
    def test_worker_crash_auto_submits_failed(self):
        from harness.agents.worker import Worker
        from harness.models.handoff import HandoffStatus
        
        worker = Worker(
            agent_id="w1",
            task=MagicMock(id="t1", title="Test", description="Test"),
            client=MagicMock()
        )
        
        # Simulate crash during execution
        def crash_handler():
            raise RuntimeError("Worker thread crashed")
        
        # Patch execute to crash
        with patch.object(worker, 'execute', side_effect=crash_handler):
            handoff = worker.run_safe()
        
        # Verify FAILED handoff auto-submitted
        assert handoff.status == HandoffStatus.FAILED
        assert "crashed" in handoff.narrative.lower()


class TestFilesystemFailureHandling:
    def test_workspace_deleted_during_merge(self, git_repo, tmp_path):
        from harness.git.workspace import create_workspace
        from harness.orchestration.merge import optimistic_merge
        
        ws = create_workspace(str(git_repo), "w1", str(tmp_path / "ws"))
        
        # Worker completes, then delete workspace
        (Path(ws.workspace_path) / "main.py").write_text("modified")
        
        # Delete workspace before merge
        shutil.rmtree(ws.workspace_path)
        
        # Attempt merge
        result = optimistic_merge(ws, str(git_repo))
        
        # Should handle error gracefully
        assert result.status.value == "error"
        assert result.fix_forward_task is not None

    def test_corrupt_handoff_rejected(self):
        from harness.orchestration.validation import validate_handoff
        from harness.models.handoff import Handoff, HandoffStatus
        
        # Submit handoff with missing narrative
        corrupt_handoff = Handoff(
            agent_id="w1",
            task_id="t1",
            status=HandoffStatus.SUCCESS,
            narrative="",  # Missing!
            metrics=MagicMock(
                wall_time_seconds=10.0,
                tokens_used=500,
                attempts=1,
                files_modified=1
            )
        )
        
        # Should reject
        result = validate_handoff(corrupt_handoff)
        assert result.valid is False
        assert "narrative" in result.error.lower()


class TestConcurrencyHandling:
    def test_concurrent_file_modification(self, git_repo, tmp_path):
        from harness.git.merge import detect_conflict
        
        # Two workers modify same file differently
        base_content = "line1\nline2\nline3\n"
        worker1_content = "line1\nline2_modified_by_w1\nline3\n"
        worker2_content = "line1\nline2_modified_by_w2\nline3\n"
        
        # Detect conflict
        conflict = detect_conflict(
            base=base_content,
            ours=worker1_content,
            theirs=worker2_content
        )
        
        # Should detect conflict
        assert conflict.has_conflict is True

    def test_watchdog_kill_and_replace(self):
        from harness.agents.watchdog import Watchdog
        from harness.agents.worker import Worker
        from datetime import datetime, timedelta
        from harness.models.watchdog import ActivityEntry
        
        watchdog = Watchdog(zombie_timeout_seconds=1)
        
        # Simulate stale worker
        worker = MagicMock()
        worker.agent_id = "w1"
        worker.last_heartbeat = datetime.now() - timedelta(seconds=10)
        
        # Detect zombie
        kill_decision = watchdog.should_kill(worker)
        
        assert kill_decision.should_kill is True
        assert kill_decision.failure_mode.value == "zombie"
        
        # Verify replacement can be spawned
        new_worker = Worker(agent_id="w2", task=worker.current_task)
        assert new_worker is not None


class TestOrdering:
    def test_out_of_order_handoffs(self):
        from harness.orchestration.planner import Planner
        
        planner = Planner()
        
        # Submit handoffs out of order
        handoff3 = MagicMock(id="h3", task_id="t3", order=3)
        handoff1 = MagicMock(id="h1", task_id="t1", order=1)
        handoff2 = MagicMock(id="h2", task_id="t2", order=2)
        
        planner.on_handoff_received(handoff3)
        planner.on_handoff_received(handoff1)
        planner.on_handoff_received(handoff2)
        
        # Process in order regardless of arrival
        processed = planner.process_pending_handoffs()
        
        # Should process in correct order
        assert processed[0].task_id == "t1"
        assert processed[1].task_id == "t2"
        assert processed[2].task_id == "t3"
```

### Run command
```bash
uv run pytest tests/python/test_chaos.py -v
```

## Incremental Build Order

Build and test in this order. Do NOT skip layers.

```
Week 1: Foundation
├── Day 1: Models (Layer 0) — all pydantic models + tests
├── Day 2: Config (Layer 1) — HarnessConfig + tests
└── Day 3: Tool handlers (Layer 2) — bash, read, write, edit + tests

Week 2: Git + Agent
├── Day 4: Workspace (Layer 3) — create, diff, cleanup + tests
├── Day 5: Merge (Layer 3) — 3-way merge, conflict detection + tests
└── Day 6: Agent loop (Layer 4) — base loop + mocked LLM tests

Week 3: Orchestration
├── Day 7: Scheduler + error budget (Layer 5) — task dispatch + tests
├── Day 8: Watchdog (Layer 5) — failure detection + tests
├── Day 9: Reconciliation (Layer 5) — green branch loop + tests
└── Day 10: Planner + worker roles (Layer 5) — role separation + tests

Week 4: Integration
├── Day 11: Multi-repo support (Layer 5) — per-repo workspaces + tests
├── Day 12: Full orchestration (Layer 5) — planner-worker pipeline + tests
└── Day 13: E2E (Layer 6) — real LLM integration tests

Week 4.5: Robustness
├── Day 14: Coherence tests (Layer 4.5) — state snapshot + compression + scratchpad validation
├── Day 15: Confusion regression tests (Layer 4.6) — idempotency + completion gate
├── Day 16: Endurance tests (Layer 5.5) — long-horizon orchestration
└── Day 17: Chaos tests (Layer 5.6) — injected failures, race conditions
```

## CI Configuration

```yaml
# .github/workflows/harness-tests.yml
name: Harness Tests
on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run pytest tests/python/ -v -m "not e2e" --tb=short

  e2e-tests:
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run pytest tests/python/ -v -m e2e --tb=short
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
```

## Test Markers

```python
# conftest.py
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests requiring real LLM API key")
    config.addinivalue_line("markers", "slow: tests that take more than 5 seconds")
```

## Key Testing Principles

1. **Model tests are free** — run thousands, they're pure logic with zero I/O
2. **Git tests need real repos** — use pytest tmp_path + git init fixtures, NOT mocks
3. **LLM tests use scripted responses** — mock the client, return MagicMock responses with specific content blocks
4. **Watchdog tests use synthetic activity logs** — inject ActivityEntry objects with controlled timestamps and files
5. **Merge tests need real file conflicts** — set up actual conflicting file contents, NOT synthetic diff strings
6. **E2E tests are expensive** — gate behind API key env var, run sparingly, test ONE scenario per test
7. **Every layer validates before the next** — if Layer 3 tests fail, do NOT attempt Layer 4

---

*Tests are the specification. Write them before (or alongside) the implementation.*
