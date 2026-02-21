from harness.config import (
    AgentLimitsConfig,
    ErrorPolicyConfig,
    HarnessConfig,
    LLMConfig,
    WatchdogConfig,
    WorkspaceConfig,
)


class TestHarnessConfigDefaults:
    def test_default_max_workers(self, mock_config):
        assert mock_config.agents.max_workers == 10

    def test_default_max_depth(self, mock_config):
        assert mock_config.agents.max_depth == 3

    def test_default_budget_percentage(self, mock_config):
        assert mock_config.errors.budget_percentage == 0.15

    def test_watchdog_enabled_by_default(self, mock_config):
        assert mock_config.watchdog.enabled is True


class TestEnvVarOverride:
    def test_llm_api_key_override(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "env-api-key-123")
        config = HarnessConfig()
        assert config.llm.api_key == "env-api-key-123"

    def test_agent_max_workers_override(self, monkeypatch):
        from harness.config import LLMConfig

        monkeypatch.setenv("AGENT_MAX_WORKERS", "20")
        config = HarnessConfig(llm=LLMConfig(api_key="test-key"))
        assert config.agents.max_workers == 20


class TestNestedConfigAccess:
    def test_llm_model_access(self, mock_config):
        assert mock_config.llm.model == "claude-sonnet-4-20250514"

    def test_agents_max_workers_access(self, mock_config):
        assert mock_config.agents.max_workers == 10

    def test_errors_budget_percentage_access(self, mock_config):
        assert mock_config.errors.budget_percentage == 0.15


class TestTypeCoercion:
    def test_string_to_int_coercion(self, monkeypatch):
        from harness.config import LLMConfig

        monkeypatch.setenv("AGENT_MAX_WORKERS", "10")
        config = HarnessConfig(llm=LLMConfig(api_key="test-key"))
        assert config.agents.max_workers == 10
        assert isinstance(config.agents.max_workers, int)

    def test_string_to_float_coercion(self, monkeypatch):
        from harness.config import LLMConfig

        monkeypatch.setenv("ERROR_BUDGET_PERCENTAGE", "0.25")
        config = HarnessConfig(llm=LLMConfig(api_key="test-key"))
        assert config.errors.budget_percentage == 0.25
        assert isinstance(config.errors.budget_percentage, float)

    def test_string_to_bool_coercion(self, monkeypatch):
        from harness.config import LLMConfig

        monkeypatch.setenv("WATCHDOG_ENABLED", "false")
        config = HarnessConfig(llm=LLMConfig(api_key="test-key"))
        assert config.watchdog.enabled is False


class TestSubConfigEnvPrefix:
    def test_llm_config_env_prefix(self):
        config = LLMConfig(api_key="test-key")
        assert config.model_config.get("env_prefix") == "LLM_"

    def test_workspace_config_env_prefix(self):
        config = WorkspaceConfig()
        assert config.model_config.get("env_prefix") == "WORKSPACE_"

    def test_agent_limits_config_env_prefix(self):
        config = AgentLimitsConfig()
        assert config.model_config.get("env_prefix") == "AGENT_"

    def test_error_policy_config_env_prefix(self):
        config = ErrorPolicyConfig()
        assert config.model_config.get("env_prefix") == "ERROR_"

    def test_watchdog_config_env_prefix(self):
        config = WatchdogConfig()
        assert config.model_config.get("env_prefix") == "WATCHDOG_"
