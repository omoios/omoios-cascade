import json

from harness.orchestration.shutdown import HarnessCheckpoint, checkpoint, resume


class TestCheckpoint:
    def test_checkpoint_saves_state_to_file(self, tmp_path):
        state = HarnessCheckpoint(
            task_states={"t1": "pending", "t2": "completed"},
            worker_states={"w1": "running"},
            error_budget_snapshot={"zone": "healthy", "failure_rate": 0.0},
            scratchpad_content={"root": "plan\nnext"},
            metadata={"turn": 3},
        )
        path = tmp_path / "checkpoint.json"

        checkpoint(state, str(path))

        assert path.exists()
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["task_states"]["t1"] == "pending"
        assert data["worker_states"]["w1"] == "running"

    def test_resume_loads_state_from_file(self, tmp_path):
        state = HarnessCheckpoint(
            task_states={"t1": "in_progress"},
            worker_states={"w1": "idle"},
            error_budget_snapshot={"zone": "warning", "failed": 2},
            scratchpad_content={"planner": "status update"},
            metadata={"checkpoint_version": 1},
        )
        path = tmp_path / "checkpoint.json"
        checkpoint(state, str(path))

        loaded = resume(str(path))

        assert loaded.task_states == {"t1": "in_progress"}
        assert loaded.worker_states == {"w1": "idle"}
        assert loaded.error_budget_snapshot == {"zone": "warning", "failed": 2}
        assert loaded.scratchpad_content == {"planner": "status update"}
        assert loaded.metadata == {"checkpoint_version": 1}

    def test_state_roundtrip(self, tmp_path):
        state = HarnessCheckpoint(
            task_states={"t1": "completed", "t2": "failed", "t3": "blocked"},
            worker_states={"w1": "completed", "w2": "failed"},
            error_budget_snapshot={"zone": "critical", "total": 25, "failed": 6},
            scratchpad_content={"root": "summary", "worker_w1": "done"},
            metadata={"run_id": "abc123", "timestamp": "2026-02-21T12:00:00"},
        )
        path = tmp_path / "checkpoint.json"

        checkpoint(state, str(path))
        restored = resume(str(path))

        assert restored.model_dump() == state.model_dump()
