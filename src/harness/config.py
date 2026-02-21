from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")

    api_key: str = Field(description="Anthropic API key")
    model: str = Field(default="claude-sonnet-4-20250514")
    max_tokens: int = Field(default=8192)
    base_url: str | None = Field(default=None)


class WorkspaceConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKSPACE_")

    root_dir: str = Field(default=".workspaces")
    canonical_dir: str = Field(default=".")
    cleanup_on_success: bool = Field(default=True)
    retain_count: int = Field(default=5, description="Max old workspaces to retain (0=unlimited)")


class AgentLimitsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_")

    max_workers: int = Field(default=10)
    max_depth: int = Field(default=3)
    worker_timeout_seconds: int = Field(default=300)
    worker_token_budget: int = Field(default=100_000)
    scratchpad_rewrite_interval: int = Field(default=10)
    context_compression_threshold: float = Field(default=0.8)
    compression_threshold: int = Field(
        default=100_000,
        description="Token count triggering compression",
    )


class ErrorPolicyConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ERROR_")

    budget_percentage: float = Field(default=0.15)
    window_size: int = Field(default=20)
    max_reconciliation_rounds: int = Field(default=3)


class WatchdogConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WATCHDOG_")

    enabled: bool = Field(default=True)
    poll_interval_seconds: int = Field(default=15)
    zombie_timeout_seconds: int = Field(default=60)
    tunnel_vision_threshold: int = Field(default=20)
    token_burn_threshold: int = Field(default=16_000)


class FreshnessConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRESHNESS_")

    self_reflection_interval: int = Field(default=10, description="Inject self-reflection every N turns")
    pivot_threshold: int = Field(default=3, description="Consecutive failures before pivot suggestion")
    hard_stop_threshold: int = Field(default=5, description="Consecutive failures before hard stop")


class HarnessConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    agents: AgentLimitsConfig = Field(default_factory=AgentLimitsConfig)
    errors: ErrorPolicyConfig = Field(default_factory=ErrorPolicyConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    repos: list[str] = Field(default_factory=list, description="Paths to target repositories")
    test_command: str | None = Field(default=None, description="Command to run for reconciliation")
    instructions: str = Field(default="", description="Top-level instructions for the harness")
