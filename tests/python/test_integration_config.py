
import pytest

from harness.config import (
    AgentLimitsConfig,
    BrowserConfig,
    ErrorPolicyConfig,
    HarnessConfig,
    LLMConfig,
    ModelConfig,
    WorkspaceConfig,
)

pytestmark = pytest.mark.slow


class TestConfigIntegration:
    def test_default_config(self):
        config = HarnessConfig(llm=LLMConfig(api_key="test-key"))

        assert config.llm.api_key == "test-key"
        assert config.llm.model == "claude-sonnet-4-20250514"

    def test_llm_config_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "env-key-123")
        config = LLMConfig()

        assert config.api_key == "env-key-123"

    def test_workspace_config_defaults(self):
        config = WorkspaceConfig()

        assert config.root_dir == ".workspaces"
        assert config.canonical_dir == "."
        assert config.cleanup_on_success is True
        assert config.retain_count == 5

    def test_agent_limits_defaults(self):
        config = AgentLimitsConfig()

        assert config.max_workers == 10
        assert config.max_depth == 3

    def test_error_policy_defaults(self):
        config = ErrorPolicyConfig()

        assert config.budget_percentage == 0.15
        assert config.max_reconciliation_rounds == 3

    def test_config_nested_sub_configs(self):
        config = HarnessConfig(llm=LLMConfig(api_key="test"))

        assert isinstance(config.workspace, WorkspaceConfig)
        assert isinstance(config.agents, AgentLimitsConfig)
        assert isinstance(config.errors, ErrorPolicyConfig)
        assert isinstance(config.models, ModelConfig)

    def test_models_config(self):
        config = ModelConfig()

        assert config.default == "claude-sonnet-4-20250514"
        assert config.smol is None
        assert config.slow is None
        assert config.plan is None

    def test_browser_config_disabled_by_default(self):
        config = BrowserConfig()

        assert config.enabled is False
        assert config.headless is True
