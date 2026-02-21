from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")

    api_key: str = Field(description="Anthropic API key")
    model: str = Field(default="claude-sonnet-4-20250514")
    max_tokens: int = Field(default=8192)
    base_url: str | None = Field(default=None)


class ModelConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MODEL_")

    default: str = Field(default="claude-sonnet-4-20250514", description="Default model for all roles")
    smol: str | None = Field(default=None, description="Cheap model for quick/explore tasks")
    slow: str | None = Field(default=None, description="Powerful model for complex reasoning")
    plan: str | None = Field(default=None, description="Model for planner role")
    commit: str | None = Field(default=None, description="Model for commit message generation")


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


class BrowserConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BROWSER_")

    enabled: bool = Field(default=False, description="Enable browser tools")
    headless: bool = Field(default=True, description="Run browser in headless mode")
    timeout: int = Field(default=30000, description="Default page timeout in ms")


class GitToolsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GIT_TOOLS_")

    enabled: bool = Field(default=False, description="Enable git status/diff/commit/branch tools")


class WebToolsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEB_TOOLS_")

    enabled: bool = Field(default=False, description="Enable web fetch/extract tools")
    timeout_seconds: int = Field(default=30, description="Default timeout for web tools")


class ObservabilityConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBSERVABILITY_")

    activity_log_dir: str = Field(default=".activity")
    cost_per_input_token: float = Field(default=0.0)
    cost_per_output_token: float = Field(default=0.0)
    metrics_export_path: str | None = Field(default=None)


class ResourceBoundsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESOURCE_BOUNDS_")

    max_wall_time_per_task: int = Field(default=600)
    max_tokens_per_agent: int = Field(default=100_000)
    max_file_modifications: int = Field(default=50)
    max_consecutive_errors: int = Field(default=10)


class PoolConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POOL_")

    min_workers: int = Field(default=1)
    max_workers: int = Field(default=20)
    scale_factor: float = Field(default=2.0)
    check_interval: int = Field(default=30)


class CircuitBreakerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CIRCUIT_BREAKER_")

    error_threshold: float = Field(default=0.5)
    cooldown_seconds: int = Field(default=120)
    window_seconds: int = Field(default=60)


class HarnessConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    agents: AgentLimitsConfig = Field(default_factory=AgentLimitsConfig)
    errors: ErrorPolicyConfig = Field(default_factory=ErrorPolicyConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    git_tools: GitToolsConfig = Field(default_factory=GitToolsConfig)
    web_tools: WebToolsConfig = Field(default_factory=WebToolsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    resource_bounds: ResourceBoundsConfig = Field(default_factory=ResourceBoundsConfig)
    pool: PoolConfig = Field(default_factory=PoolConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    repos: list[str] = Field(default_factory=list, description="Paths to target repositories")
    test_command: str | None = Field(default=None, description="Command to run for reconciliation")
    instructions: str = Field(default="", description="Top-level instructions for the harness")
