import pytest

from harness.intent import IntentValidationResult, validate_intent
from harness.intent_templates import INTENT_TEMPLATES, apply_template
from harness.models.task_spec import TaskSpec


def _valid_spec() -> TaskSpec:
    return TaskSpec(
        objective="Add intent validation",
        scope=["src/harness/intent.py"],
        non_goals=["No planner changes"],
        success_criteria=["Validation returns no errors"],
        performance_bounds={"max_latency_ms": 50},
        dependency_philosophy={"allow": ["pydantic"]},
        architectural_constraints=["Follow existing event patterns"],
        priority="medium",
        estimated_complexity="medium",
    )


def test_validate_intent_valid_spec():
    result = validate_intent(_valid_spec())
    assert result.is_valid is True
    assert result.errors == []
    assert result.warnings == []


def test_validate_intent_error_empty_objective():
    spec = _valid_spec()
    spec.objective = "   "

    result = validate_intent(spec)
    assert result.is_valid is False
    assert "objective is required and cannot be empty" in result.errors


def test_validate_intent_error_empty_scope():
    spec = _valid_spec()
    spec.scope = []

    result = validate_intent(spec)
    assert "scope must list at least one file or module" in result.errors


def test_validate_intent_error_empty_success_criteria():
    spec = _valid_spec()
    spec.success_criteria = []

    result = validate_intent(spec)
    assert "success_criteria must have at least one criterion" in result.errors


def test_validate_intent_error_invalid_priority():
    spec = _valid_spec()
    spec.priority = "urgent"

    result = validate_intent(spec)
    assert "priority must be high/medium/low, got: urgent" in result.errors


def test_validate_intent_error_invalid_complexity():
    spec = _valid_spec()
    spec.estimated_complexity = "hard"

    result = validate_intent(spec)
    assert "estimated_complexity must be simple/medium/complex, got: hard" in result.errors


def test_validate_intent_warnings_for_optional_empty_fields():
    spec = TaskSpec(
        objective="Do work",
        scope=["src/harness"],
        success_criteria=["Done"],
    )

    result = validate_intent(spec)
    assert result.is_valid is True
    assert "non_goals is empty — risk of scope creep" in result.warnings
    assert "performance_bounds is empty — risk of slow implementation" in result.warnings
    assert "dependency_philosophy is empty — risk of unnecessary dependencies" in result.warnings
    assert "architectural_constraints is empty — no pattern guidance" in result.warnings


@pytest.mark.parametrize("template_name", list(INTENT_TEMPLATES.keys()))
def test_apply_template_for_each_template(template_name: str):
    spec = apply_template(
        template_name,
        overrides={"objective": f"Use {template_name}", "scope": ["src/harness"]},
    )

    assert isinstance(spec, TaskSpec)
    assert spec.objective == f"Use {template_name}"
    assert spec.scope == ["src/harness"]
    assert spec.non_goals == INTENT_TEMPLATES[template_name]["non_goals"]


def test_apply_template_with_overrides():
    spec = apply_template(
        "feature",
        overrides={
            "objective": "Build feature",
            "scope": ["src/harness/new_feature.py"],
            "priority": "high",
            "success_criteria": ["Feature works"],
        },
    )

    assert spec.objective == "Build feature"
    assert spec.scope == ["src/harness/new_feature.py"]
    assert spec.priority == "high"
    assert spec.success_criteria == ["Feature works"]


def test_apply_template_unknown_template_raises_value_error():
    with pytest.raises(ValueError, match="Unknown template"):
        apply_template("unknown")


def test_intent_validation_result_is_valid_property():
    result = IntentValidationResult()
    assert result.is_valid is True
    result.errors.append("some error")
    assert result.is_valid is False
