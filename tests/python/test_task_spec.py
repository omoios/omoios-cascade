import pytest
from pydantic import ValidationError

from harness.models.task_spec import TaskSpec


def test_task_spec_creation_with_all_fields():
    spec = TaskSpec(
        objective="Implement intent framework",
        scope=["src/harness/intent.py", "src/harness/intent_templates.py"],
        non_goals=["No planner wiring"],
        success_criteria=["Tests pass", "Lint passes"],
        performance_bounds={"max_latency_ms": 100},
        dependency_philosophy={"allow": ["pydantic"], "forbid": ["new external libs"]},
        architectural_constraints=["Follow existing patterns"],
        priority="high",
        estimated_complexity="complex",
    )

    assert spec.objective == "Implement intent framework"
    assert len(spec.scope) == 2
    assert spec.priority == "high"
    assert spec.estimated_complexity == "complex"


def test_task_spec_defaults():
    spec = TaskSpec(objective="Minimal spec")

    assert spec.scope == []
    assert spec.non_goals == []
    assert spec.success_criteria == []
    assert spec.performance_bounds == {}
    assert spec.dependency_philosophy == {}
    assert spec.architectural_constraints == []
    assert spec.priority == "medium"
    assert spec.estimated_complexity == "medium"


def test_task_spec_serialization_roundtrip():
    spec = TaskSpec(
        objective="Roundtrip",
        scope=["src/harness/models/task_spec.py"],
        success_criteria=["Roundtrip succeeds"],
    )

    data = spec.model_dump()
    restored = TaskSpec.model_validate(data)
    assert restored == spec

    json_data = spec.model_dump_json()
    restored_json = TaskSpec.model_validate_json(json_data)
    assert restored_json == spec


def test_task_spec_field_validation():
    with pytest.raises(ValidationError):
        TaskSpec(scope=["src/harness"], success_criteria=["ok"])  # type: ignore[call-arg]
