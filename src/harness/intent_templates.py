from harness.models.task_spec import TaskSpec

INTENT_TEMPLATES: dict[str, dict] = {
    "feature": {
        "non_goals": ["No unrelated refactoring"],
        "success_criteria": ["All new tests pass", "No regressions in existing tests"],
        "architectural_constraints": ["Follow existing code patterns"],
    },
    "bugfix": {
        "non_goals": ["No refactoring beyond the fix", "No new features"],
        "success_criteria": ["Bug no longer reproduces", "Regression test added"],
    },
    "refactor": {
        "non_goals": ["No behavior change", "No new features"],
        "success_criteria": ["All existing tests pass unchanged", "Code quality improved"],
    },
    "test": {
        "non_goals": ["No production code changes"],
        "success_criteria": ["Coverage increase", "All tests pass"],
    },
    "docs": {
        "non_goals": ["No code changes"],
        "success_criteria": ["Documentation is accurate", "All links valid"],
    },
}


def apply_template(template_name: str, overrides: dict | None = None) -> TaskSpec:
    if template_name not in INTENT_TEMPLATES:
        raise ValueError(f"Unknown template: {template_name}. Available: {list(INTENT_TEMPLATES.keys())}")

    base = INTENT_TEMPLATES[template_name].copy()
    if overrides:
        for key, value in overrides.items():
            base[key] = value

    if "objective" not in base:
        base["objective"] = ""
    if "scope" not in base:
        base["scope"] = []

    return TaskSpec(**base)
