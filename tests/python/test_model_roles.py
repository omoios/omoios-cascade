from harness.config import HarnessConfig, LLMConfig, ModelConfig
from harness.runner import HarnessRunner


def test_model_config_defaults():
    models = ModelConfig()
    assert models.default == "claude-sonnet-4-20250514"
    assert models.smol is None
    assert models.slow is None
    assert models.plan is None
    assert models.commit is None


def test_model_config_with_overrides():
    models = ModelConfig(
        default="model-default",
        smol="model-smol",
        slow="model-slow",
        plan="model-plan",
        commit="model-commit",
    )
    assert models.default == "model-default"
    assert models.smol == "model-smol"
    assert models.slow == "model-slow"
    assert models.plan == "model-plan"
    assert models.commit == "model-commit"


def test_get_model_for_role_returns_role_specific_models():
    config = HarnessConfig(
        llm=LLMConfig(api_key="test-key"),
        models=ModelConfig(default="def", plan="plan", slow="slow"),
    )
    runner = HarnessRunner(config=config)

    assert runner._get_model_for_role("root_planner") == "plan"
    assert runner._get_model_for_role("sub_planner") == "plan"
    assert runner._get_model_for_role("worker") == "def"
    assert runner._get_model_for_role("fixer") == "slow"


def test_get_model_for_role_falls_back_to_default_when_unset():
    config = HarnessConfig(
        llm=LLMConfig(api_key="test-key"),
        models=ModelConfig(default="def", plan=None, slow=None),
    )
    runner = HarnessRunner(config=config)

    assert runner._get_model_for_role("root_planner") == "def"
    assert runner._get_model_for_role("sub_planner") == "def"
    assert runner._get_model_for_role("fixer") == "def"
    assert runner._get_model_for_role("unknown") == "def"


def test_harness_config_includes_models_field():
    config = HarnessConfig(llm=LLMConfig(api_key="test-key"))
    assert isinstance(config.models, ModelConfig)
