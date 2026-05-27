from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Literal, Self

import tomlkit
from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    SecretStr,
    ValidationError,
    field_serializer,
    model_validator,
)
from tomlkit.exceptions import TOMLKitError

from pythinker_code.exception import ConfigError
from pythinker_code.hooks.config import HookDef
from pythinker_code.llm import ModelCapability, ProviderType
from pythinker_code.share import get_share_dir
from pythinker_code.utils.logging import logger

AgentExecutionProfile = Literal[
    "default",
    "review_safe",
    "autonomous_coding",
    "plan_only",
    "ci_fixer",
]


class OAuthRef(BaseModel):
    """Reference to OAuth credentials stored outside the config file."""

    storage: Literal["keyring", "file"] = "file"
    """Credential storage backend."""
    key: str
    """Storage key to locate OAuth credentials."""


class LLMProvider(BaseModel):
    """LLM provider configuration."""

    type: ProviderType
    """Provider type"""
    base_url: str
    """API base URL"""
    api_key: SecretStr
    """API key"""
    env: dict[str, str] | None = None
    """Environment variables to set before creating the provider instance"""
    custom_headers: dict[str, str] | None = None
    """Custom headers to include in API requests"""
    reasoning_key: str | None = None
    """Message field name carrying reasoning content for OpenAI-compatible APIs.
    Applies to provider type ``openai_legacy``. Defaults to ``reasoning_content``
    when unset. Use an empty string to disable reasoning round-tripping."""
    oauth: OAuthRef | None = None
    """OAuth credential reference (do not store tokens here)."""

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr):
        return v.get_secret_value()


class LLMModel(BaseModel):
    """LLM model configuration."""

    provider: str
    """Provider name"""
    model: str
    """Model name"""
    max_context_size: int
    """Maximum context size (unit: tokens)"""
    capabilities: set[ModelCapability] | None = None
    """Model capabilities"""
    display_name: str | None = None
    """Human-readable model name (sourced from the provider's models API when available)"""


class LoopControl(BaseModel):
    """Agent loop control configuration."""

    max_steps_per_turn: int = Field(
        default=1000,
        ge=1,
        validation_alias=AliasChoices("max_steps_per_turn", "max_steps_per_run"),
    )
    """Maximum number of steps in one turn"""
    max_retries_per_step: int = Field(default=3, ge=1)
    """Maximum number of retries in one step"""
    max_ralph_iterations: int = Field(default=0, ge=-1)
    """Extra iterations after the first turn in Ralph mode. Use -1 for unlimited."""
    reserved_context_size: int = Field(default=50_000, ge=1000)
    """Reserved token count for LLM response generation. Auto-compaction triggers when
    either context_tokens + reserved_context_size >= max_context_size or
    context_tokens >= max_context_size * compaction_trigger_ratio. Default is 50000."""
    compaction_trigger_ratio: float = Field(default=0.85, ge=0.5, le=0.99)
    """Context usage ratio threshold for auto-compaction. Default is 0.85 (85%).
    Auto-compaction triggers when context_tokens >= max_context_size * compaction_trigger_ratio
    or when context_tokens + reserved_context_size >= max_context_size."""


class BackgroundConfig(BaseModel):
    """Background task runtime configuration."""

    max_running_tasks: int = Field(default=4, ge=1)
    read_max_bytes: int = Field(default=30_000, ge=1024)
    notification_tail_lines: int = Field(default=20, ge=1)
    notification_tail_chars: int = Field(default=3_000, ge=256)
    wait_poll_interval_ms: int = Field(default=500, ge=50)
    worker_heartbeat_interval_ms: int = Field(default=5_000, ge=100)
    worker_stale_after_ms: int = Field(default=15_000, ge=1000)
    kill_grace_period_ms: int = Field(default=2_000, ge=100)
    keep_alive_on_exit: bool = Field(
        default=False,
        description="Keep background tasks alive when CLI exits. Default: kill on exit.",
    )
    agent_task_timeout_s: int = Field(default=3600, ge=60)
    """Maximum runtime in seconds for a background agent task. Default: 3600 (1 hour)."""
    print_wait_ceiling_s: int = Field(default=3600, ge=1)
    """Hard ceiling for how long ``--print`` mode waits for background tasks before
    killing them and exiting. The effective wait is
    ``min(max(active_task.timeout_s or agent_task_timeout_s), print_wait_ceiling_s)``.
    Default: 3600 (1 hour)."""


class NotificationConfig(BaseModel):
    """Notification runtime configuration."""

    claim_stale_after_ms: int = Field(default=15_000, ge=1000)


class PythinkerAISearchConfig(BaseModel):
    """Pythinker AI Search configuration."""

    base_url: str
    """Base URL for Pythinker AI Search service."""
    api_key: SecretStr
    """API key for Pythinker AI Search service."""
    custom_headers: dict[str, str] | None = None
    """Custom headers to include in API requests."""
    oauth: OAuthRef | None = None
    """OAuth credential reference (do not store tokens here)."""

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr):
        return v.get_secret_value()


class PythinkerAIFetchConfig(BaseModel):
    """Pythinker AI Fetch configuration."""

    base_url: str
    """Base URL for Pythinker AI Fetch service."""
    api_key: SecretStr
    """API key for Pythinker AI Fetch service."""
    custom_headers: dict[str, str] | None = None
    """Custom headers to include in API requests."""
    oauth: OAuthRef | None = None
    """OAuth credential reference (do not store tokens here)."""

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr):
        return v.get_secret_value()


class Services(BaseModel):
    """Services configuration."""

    pythinker_ai_search: PythinkerAISearchConfig | None = None
    """Pythinker AI Search configuration."""
    pythinker_ai_fetch: PythinkerAIFetchConfig | None = None
    """Pythinker AI Fetch configuration."""


class FeedbackConfig(BaseModel):
    """User-submitted feedback endpoint configuration."""

    endpoint_url: str = Field(
        default="",
        description=(
            "Full URL for the /feedback slash command. Overrides the built-in "
            "Pythinker platform endpoint when set."
        ),
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="Optional bearer token for the feedback endpoint.",
    )
    custom_headers: dict[str, str] | None = Field(
        default=None,
        description="Optional extra headers for feedback endpoint requests.",
    )
    github_client_id: str = Field(
        default="",
        description=(
            "Optional GitHub OAuth App client ID. When set, /feedback uses GitHub "
            "device login and creates issues as the signed-in GitHub user."
        ),
    )
    github_repo: str = Field(
        default="mohamed-elkholy95/Pythinker-Code",
        description="GitHub owner/repo used by /feedback GitHub OAuth submissions.",
    )

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr | None):
        return v.get_secret_value() if v is not None else None


class MCPClientConfig(BaseModel):
    """MCP client configuration."""

    tool_call_timeout_ms: int = 60000
    """Timeout for tool calls in milliseconds."""


class TUIConfig(BaseModel):
    """TUI rendering style configuration."""

    style: Literal["pythinker", "card"] = Field(
        default="card",
        description=(
            "TUI rendering style. 'card' (default) uses highlighted user "
            "messages and bordered tool cards. 'pythinker' keeps the legacy "
            "worklog-based rendering. Override at runtime with the env var "
            "PYTHINKER_TUI_STYLE=pythinker."
        ),
    )
    prompt_history_enabled: bool = Field(
        default=True,
        description=(
            "Persist shell prompt history under the Pythinker share directory. "
            "Set false or export PYTHINKER_DISABLE_PROMPT_HISTORY=1 for sensitive sessions."
        ),
    )


class MCPConfig(BaseModel):
    """MCP configuration."""

    client: MCPClientConfig = Field(
        default_factory=MCPClientConfig, description="MCP client configuration"
    )


class Config(BaseModel):
    """Main configuration structure."""

    is_from_default_location: bool = Field(
        default=False,
        description="Whether the config was loaded from the default location",
        exclude=True,
    )
    source_file: Path | None = Field(
        default=None,
        description="Path to the loaded config file. None when loaded from --config text.",
        exclude=True,
    )
    default_model: str = Field(default="", description="Default model to use")
    default_thinking: bool = Field(default=False, description="Default thinking mode")
    agent_execution_profile: AgentExecutionProfile = Field(
        default="default",
        description=(
            "Preset defaults for agent autonomy. Profiles only fill unset related options: "
            "review_safe, autonomous_coding, plan_only, or ci_fixer."
        ),
    )
    default_yolo: bool = Field(default=False, description="Default yolo (auto-approve) mode")
    ask_user_question_policy: Literal["always", "ask_except_auto", "never"] = Field(
        default="ask_except_auto",
        description=(
            "Controls AskUserQuestion behavior: always ask, ask except in auto mode, "
            "or never pause and let the agent use best judgment."
        ),
    )
    skip_auto_prompt_injection: bool = Field(
        default=False,
        description=(
            "If true, suppress the auto-mode system reminder. "
            "Yolo mode does not inject a system reminder."
        ),
    )
    default_plan_mode: bool = Field(default=False, description="Default plan mode for new sessions")
    default_editor: str = Field(
        default="",
        description="Default external editor command (e.g. 'vim', 'code --wait')",
    )
    theme: Literal["dark", "light"] = Field(
        default="dark",
        description="Terminal color theme. Use 'light' for light terminal backgrounds.",
    )
    show_thinking_stream: bool = Field(
        default=True,
        description=(
            "If true, stream the raw reasoning text in the live area as a "
            "6-line scrolling preview and commit the full reasoning markdown "
            "to history when the block ends. Default true. Set to false to "
            "show only the compact 'Thinking ...' indicator and a one-line "
            "trace summary."
        ),
    )
    prevent_idle_sleep: bool = Field(
        default=False,
        description=(
            "Prevent the computer from idle-sleeping while an agent turn is running. "
            "Supported on macOS, Linux, and Windows. Default: false."
        ),
    )
    models: dict[str, LLMModel] = Field(default_factory=dict, description="List of LLM models")
    providers: dict[str, LLMProvider] = Field(
        default_factory=dict, description="List of LLM providers"
    )
    loop_control: LoopControl = Field(default_factory=LoopControl, description="Agent loop control")
    background: BackgroundConfig = Field(
        default_factory=BackgroundConfig, description="Background task configuration"
    )
    notifications: NotificationConfig = Field(
        default_factory=NotificationConfig, description="Notification configuration"
    )
    services: Services = Field(default_factory=Services, description="Services configuration")
    feedback: FeedbackConfig = Field(
        default_factory=FeedbackConfig,
        description="User-submitted feedback endpoint configuration",
    )
    mcp: MCPConfig = Field(default_factory=MCPConfig, description="MCP configuration")
    tui: TUIConfig = Field(default_factory=TUIConfig, description="TUI rendering configuration")
    hooks: list[HookDef] = Field(default_factory=list, description="Hook definitions")  # pyright: ignore[reportUnknownVariableType]
    merge_all_available_skills: bool = Field(
        default=True,
        description=(
            "Merge skills from all existing brand directories (pythinker/claude/codex) "
            "instead of using only the first one found. Defaults to true so users "
            "who keep skills in multiple brand directories see everything out of "
            "the box; set to false to restore the first-match-only behaviour."
        ),
    )
    extra_skill_dirs: list[str] = Field(
        default_factory=list,
        description=(
            "Extra directories to discover skills from, added on top of the "
            "built-in / user / project locations. Each entry may be an absolute "
            "path, ``~``-prefixed (expanded against $HOME), or relative to the "
            "project root (the nearest ``.git`` directory above the work dir). "
            "Missing paths are silently skipped."
        ),
    )
    telemetry: bool = Field(
        default=True,
        description=(
            "Enable anonymous telemetry to help improve pythinker-code. Set to false to opt out."
        ),
    )

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        self._apply_agent_execution_profile()
        if self.default_model and self.default_model not in self.models:
            raise ValueError(f"Default model {self.default_model} not found in models")
        for model in self.models.values():
            if model.provider not in self.providers:
                raise ValueError(f"Provider {model.provider} not found in providers")
        return self

    def _apply_agent_execution_profile(self) -> None:
        profile = self.agent_execution_profile
        if profile == "default":
            return
        fields_set = self.model_fields_set
        if profile == "review_safe":
            if "ask_user_question_policy" not in fields_set:
                self.ask_user_question_policy = "always"
        elif profile == "autonomous_coding":
            if "default_yolo" not in fields_set:
                self.default_yolo = True
            if "ask_user_question_policy" not in fields_set:
                self.ask_user_question_policy = "never"
        elif profile == "plan_only":
            if "default_plan_mode" not in fields_set:
                self.default_plan_mode = True
            if "ask_user_question_policy" not in fields_set:
                self.ask_user_question_policy = "always"
        elif profile == "ci_fixer" and "ask_user_question_policy" not in fields_set:
            self.ask_user_question_policy = "ask_except_auto"


def get_config_file() -> Path:
    """Get the configuration file path."""
    return get_share_dir() / "config.toml"


def get_default_config() -> Config:
    """Get the default configuration."""
    return Config(
        default_model="",
        models={},
        providers={},
        services=Services(),
    )


def load_config(config_file: Path | None = None) -> Config:
    """
    Load configuration from config file.
    If the config file does not exist, create it with default configuration.

    Args:
        config_file (Path | None): Path to the configuration file. If None, use default path.

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If the configuration file is invalid.
    """
    default_config_file = get_config_file().expanduser().resolve(strict=False)
    if config_file is None:
        config_file = default_config_file
    config_file = config_file.expanduser().resolve(strict=False)
    is_default_config_file = config_file == default_config_file
    logger.debug("Loading config from file: {file}", file=config_file)

    # If the user hasn't provided an explicit config path, migrate legacy JSON config once.
    if is_default_config_file and not config_file.exists():
        migration_error = _migrate_json_config_to_toml()
        if migration_error is not None:
            raise ConfigError(
                f"Legacy config file has incompatible settings; please fix or "
                f"rename/delete {migration_error.config_file} to continue. "
                f"Errors: {migration_error.errors}"
            ) from None

    if not config_file.exists():
        config = get_default_config()
        logger.debug("No config file found, creating default config: {config}", config=config)
        save_config(config, config_file)
        config.is_from_default_location = is_default_config_file
        config.source_file = config_file
        return config

    try:
        config_text = config_file.read_text(encoding="utf-8")
        if config_file.suffix.lower() == ".json":
            data = json.loads(config_text)
        else:
            data = tomlkit.loads(config_text)
        config = Config.model_validate(data)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in configuration file {config_file}: {e}") from e
    except TOMLKitError as e:
        raise ConfigError(f"Invalid TOML in configuration file {config_file}: {e}") from e
    except ValidationError as e:
        raise ConfigError(f"Invalid configuration file {config_file}: {e}") from e
    config.is_from_default_location = is_default_config_file
    config.source_file = config_file
    return config


def load_config_from_string(config_string: str) -> Config:
    """
    Load configuration from a TOML or JSON string.

    Args:
        config_string (str): TOML or JSON configuration text.

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If the configuration text is invalid.
    """
    if not config_string.strip():
        raise ConfigError("Configuration text cannot be empty")

    json_error: json.JSONDecodeError | None = None
    try:
        data = json.loads(config_string)
    except json.JSONDecodeError as exc:
        json_error = exc
        data = None

    if data is None:
        try:
            data = tomlkit.loads(config_string)
        except TOMLKitError as toml_error:
            raise ConfigError(
                f"Invalid configuration text: {json_error}; {toml_error}"
            ) from toml_error

    try:
        config = Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Invalid configuration text: {e}") from e
    config.is_from_default_location = False
    config.source_file = None
    return config


def save_config(config: Config, config_file: Path | None = None):
    """
    Save configuration to config file.

    Args:
        config (Config): Config object to save.
        config_file (Path | None): Path to the configuration file. If None, use default path.
    """
    config_file = config_file or get_config_file()
    logger.debug("Saving config to file: {file}", file=config_file)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_data = config.model_dump(mode="json", exclude_none=True)
    with open(config_file, "w", encoding="utf-8") as f:
        if config_file.suffix.lower() == ".json":
            f.write(json.dumps(config_data, ensure_ascii=False, indent=2))
        else:
            f.write(tomlkit.dumps(config_data))  # type: ignore[reportUnknownMemberType]
    with contextlib.suppress(OSError):
        os.chmod(config_file, 0o600)


class MigrationError(Exception):
    """Raised when legacy config migration fails due to incompatible schema."""

    def __init__(self, config_file: str, errors: list[str]) -> None:
        super().__init__(config_file, errors)
        self.config_file = config_file
        self.errors = errors


def _migrate_json_config_to_toml() -> MigrationError | None:
    """
    Attempt to migrate legacy JSON config to TOML.

    Returns:
        None on success.
        MigrationError if the JSON is valid but has incompatible schema — caller
        should raise ConfigError so the user can see their actual settings.

    Corrupt JSON is handled here: backed up so defaults take over silently.
    """
    old_json_config_file = get_share_dir() / "config.json"
    new_toml_config_file = get_share_dir() / "config.toml"

    if not old_json_config_file.exists():
        return None
    if new_toml_config_file.exists():
        return None

    logger.info(
        "Migrating legacy config file from {old} to {new}",
        old=old_json_config_file,
        new=new_toml_config_file,
    )

    backup_path = _next_legacy_config_backup_path(old_json_config_file)

    data: object | None = None
    json_decode_error: json.JSONDecodeError | None = None
    validation_errors: list[str] = []
    config: Config | None = None

    try:
        data = json.loads(old_json_config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        json_decode_error = e

    if json_decode_error is not None:
        # Corrupt JSON: back up the file so load_config() creates a fresh config.
        logger.error(
            "Legacy config file is corrupt JSON ({err}); backing it up and skipping migration. "
            "Please fix or remove {file} to restore default behavior.",
            err=json_decode_error,
            file=old_json_config_file,
        )
        old_json_config_file.replace(backup_path)
        return None

    try:
        config = Config.model_validate(data)
    except ValidationError as e:
        validation_errors = [
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()
        ]

    if config is not None:
        save_config(config, new_toml_config_file)
        old_json_config_file.replace(backup_path)
        logger.info("Legacy config migrated and backed up to {file}", file=backup_path)
        return None

    # Valid JSON but incompatible schema: keep the original in place so load_config()
    # raises ConfigError with the user's actual settings. This preserves user data.
    logger.warning(
        "Legacy config file has incompatible settings; please review and fix {file} or "
        "rename/delete it to use defaults. Errors: {errors}",
        file=old_json_config_file,
        errors=validation_errors,
    )
    return MigrationError(
        config_file=str(old_json_config_file),
        errors=validation_errors,
    )


def _next_legacy_config_backup_path(config_file: Path) -> Path:
    backup_path = config_file.with_name("config.json.bak")
    if not backup_path.exists():
        return backup_path
    index = 1
    while True:
        candidate = config_file.with_name(f"config.json.bak.{index}")
        if not candidate.exists():
            return candidate
        index += 1
