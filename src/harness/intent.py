from harness.models.task_spec import TaskSpec


class IntentValidationResult:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def validate_intent(spec: TaskSpec) -> IntentValidationResult:
    result = IntentValidationResult()

    if not spec.objective or not spec.objective.strip():
        result.errors.append("objective is required and cannot be empty")

    if not spec.scope:
        result.errors.append("scope must list at least one file or module")

    if not spec.success_criteria:
        result.errors.append("success_criteria must have at least one criterion")

    if spec.priority not in ("high", "medium", "low"):
        result.errors.append(f"priority must be high/medium/low, got: {spec.priority}")

    if spec.estimated_complexity not in ("simple", "medium", "complex"):
        result.errors.append(f"estimated_complexity must be simple/medium/complex, got: {spec.estimated_complexity}")

    if not spec.non_goals:
        result.warnings.append("non_goals is empty — risk of scope creep")

    if not spec.performance_bounds:
        result.warnings.append("performance_bounds is empty — risk of slow implementation")

    if not spec.dependency_philosophy:
        result.warnings.append("dependency_philosophy is empty — risk of unnecessary dependencies")

    if not spec.architectural_constraints:
        result.warnings.append("architectural_constraints is empty — no pattern guidance")

    return result
