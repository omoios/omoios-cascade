import pytest
from pydantic import ValidationError

from harness.models.handoff import Handoff, HandoffMetrics
from harness.models.scratchpad import ScratchpadSchema


class TestStructuredOutput:
    def test_handoff_validates_required_fields(self):
        handoff = Handoff(
            agent_id="w1",
            task_id="t1",
            status="success",
            narrative="Completed the assigned task and updated files.",
            metrics=HandoffMetrics(
                wall_time_seconds=1.0,
                tokens_used=100,
                attempts=1,
                files_modified=1,
            ),
        )
        assert handoff.agent_id == "w1"
        assert handoff.task_id == "t1"

        with pytest.raises(ValidationError):
            Handoff(
                task_id="t1",
                status="success",
                narrative="Completed the assigned task and updated files.",
                metrics=HandoffMetrics(
                    wall_time_seconds=1.0,
                    tokens_used=100,
                    attempts=1,
                    files_modified=1,
                ),
            )

    def test_handoff_rejects_invalid_status(self):
        with pytest.raises(ValidationError):
            Handoff(
                agent_id="w1",
                task_id="t1",
                status="bogus",
                narrative="Attempted task execution.",
                metrics=HandoffMetrics(
                    wall_time_seconds=1.0,
                    tokens_used=100,
                    attempts=1,
                    files_modified=1,
                ),
            )

    def test_scratchpad_schema_validates_structure(self):
        scratchpad = ScratchpadSchema(goal="Ship layer 3.5 tests", next_action="Run pytest")
        assert scratchpad.goal == "Ship layer 3.5 tests"
        assert scratchpad.next_action == "Run pytest"

        with pytest.raises(ValidationError):
            ScratchpadSchema(goal="", next_action="Run pytest")

    def test_scratchpad_schema_rejects_empty_required(self):
        with pytest.raises(ValidationError):
            ScratchpadSchema(goal="", next_action="do something")

        with pytest.raises(ValidationError):
            ScratchpadSchema(goal="something", next_action="")
