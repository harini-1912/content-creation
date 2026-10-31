"""Application configuration and environment settings for IncuBrix Content Engine.

Enforces offline deterministic execution by default, secret masking,
and explicit mode validation without silent fallbacks.
"""

import os
from enum import Enum
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class AppEnvironmentEnum(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class GenerationModeEnum(str, Enum):
    OFFLINE_DETERMINISTIC = "OFFLINE_DETERMINISTIC"
    ONLINE_LLM = "ONLINE_LLM"


class Settings(BaseModel):
    """Immutable application settings model."""
    app_env: AppEnvironmentEnum = Field(
        default=AppEnvironmentEnum.DEVELOPMENT,
        description="Active application runtime environment"
    )
    generation_mode: GenerationModeEnum = Field(
        default=GenerationModeEnum.OFFLINE_DETERMINISTIC,
        description="Active engine execution mode (defaults to zero-cost offline)"
    )
    gemini_api_key: Optional[str] = Field(
        default=None,
        description="Optional API key for live LLM mode (masked in logs)"
    )
    default_campaign_name: str = Field(
        default="creator_repurpose_2026",
        description="Default campaign name for UTM tracking"
    )
    default_base_url: str = Field(
        default="https://app.incubrix.com/",
        description="Verified destination endpoint for app exploration"
    )
    output_dir: str = Field(
        default="output",
        description="Destination directory for rendered assets"
    )
    logs_dir: str = Field(
        default="logs",
        description="Destination directory for run logs"
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )

    @field_validator("generation_mode", mode="before")
    @classmethod
    def validate_mode_string(cls, v: Any) -> Any:
        """Strictly validates mode; rejects unsupported modes without silent fallback."""
        if isinstance(v, str):
            v_upper = v.strip().upper()
            valid_modes = [m.value for m in GenerationModeEnum]
            if v_upper not in valid_modes:
                raise ValueError(
                    f"Unsupported generation mode '{v}'. Must be one of: {valid_modes}"
                )
            return v_upper
        return v

    @model_validator(mode="after")
    def validate_mode_and_credentials(self) -> "Settings":
        """Enforces credential presence for online mode, while keeping offline mode zero-dependency."""
        if self.generation_mode == GenerationModeEnum.ONLINE_LLM:
            if not self.gemini_api_key or not self.gemini_api_key.strip():
                raise ValueError(
                    "GEMINI_API_KEY is required when GENERATION_MODE is ONLINE_LLM. "
                    "For offline execution without credentials, set GENERATION_MODE=OFFLINE_DETERMINISTIC."
                )
        return self

    def to_safe_dict(self) -> Dict[str, Any]:
        """Returns a sanitized dictionary representation with all secrets masked."""
        data = self.model_dump()
        if data.get("gemini_api_key"):
            data["gemini_api_key"] = "********[MASKED]"
        else:
            data["gemini_api_key"] = None
        return data

    def __repr__(self) -> str:
        """Secret-safe string representation."""
        safe = self.to_safe_dict()
        items = ", ".join(f"{k}={v!r}" for k, v in safe.items())
        return f"Settings({items})"


def load_settings(
    env_override: Optional[Dict[str, str]] = None,
    load_env_file: Optional[bool] = None,
    env_file: Union[str, os.PathLike[str]] = ".env",
) -> Settings:
    """Factory to load settings with defined configuration precedence:

    Precedence order:
    1. env_override (explicit test/runtime overrides)
    2. os.environ (system environment variables)
    3. .env file (loaded when load_env_file is True, or when env_override is None and file exists)
    4. Settings model defaults

    When env_override is explicitly passed (e.g. in test suites), load_env_file
    defaults to False to guarantee test isolation from developer secrets.
    """
    env: Dict[str, Any] = {}

    # Determine whether to load .env file
    should_load_dot = load_env_file if load_env_file is not None else (env_override is None)

    if should_load_dot:
        try:
            import dotenv
            if os.path.isfile(env_file):
                dot_vals = dotenv.dotenv_values(env_file)
                env.update({k: v for k, v in dot_vals.items() if v is not None})
        except Exception:
            pass

    # os.environ overrides .env file values
    env.update(os.environ)

    # env_override has highest precedence
    if env_override:
        env.update(env_override)

    raw_env = env.get("APP_ENV", "development").lower()
    raw_mode = env.get("GENERATION_MODE", "OFFLINE_DETERMINISTIC")
    raw_key = env.get("GEMINI_API_KEY")

    return Settings(
        app_env=raw_env,
        generation_mode=raw_mode,
        gemini_api_key=raw_key if raw_key else None,
        default_campaign_name=env.get("DEFAULT_CAMPAIGN_NAME", "creator_repurpose_2026"),
        default_base_url=env.get("DEFAULT_BASE_URL", "https://app.incubrix.com/"),
        output_dir=env.get("OUTPUT_DIR", "output"),
        logs_dir=env.get("LOGS_DIR", "logs"),
        log_level=env.get("LOG_LEVEL", "INFO")
    )

