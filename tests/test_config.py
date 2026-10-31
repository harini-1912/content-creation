"""Automated unit tests for application configuration and settings.

Verifies default offline-deterministic mode, secret masking,
and explicit error raising on unsupported execution modes.
"""

import pytest
from pydantic import ValidationError

from app.core.config import (
    Settings,
    load_settings,
    AppEnvironmentEnum,
    GenerationModeEnum
)


def test_default_offline_deterministic_mode():
    """Verifies that settings default to OFFLINE_DETERMINISTIC without requiring credentials."""
    settings = load_settings(env_override={})
    assert settings.generation_mode == GenerationModeEnum.OFFLINE_DETERMINISTIC
    assert settings.app_env == AppEnvironmentEnum.DEVELOPMENT
    assert settings.gemini_api_key is None


def test_reject_unsupported_generation_mode():
    """Verifies that an unknown mode raises ValueError without silent fallback."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(generation_mode="HYBRID_AUTONOMOUS_MODE")
    assert "Unsupported generation mode" in str(exc_info.value)


def test_online_mode_requires_api_key():
    """Verifies that ONLINE_LLM mode raises error when API key is missing."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(generation_mode=GenerationModeEnum.ONLINE_LLM, gemini_api_key=None)
    assert "GEMINI_API_KEY is required when GENERATION_MODE is ONLINE_LLM" in str(exc_info.value)


def test_online_mode_accepts_valid_key():
    """Verifies that ONLINE_LLM accepts a configured API key."""
    settings = Settings(
        generation_mode=GenerationModeEnum.ONLINE_LLM,
        gemini_api_key="test_dummy_key_12345"
    )
    assert settings.generation_mode == GenerationModeEnum.ONLINE_LLM
    assert settings.gemini_api_key == "test_dummy_key_12345"


def test_secret_safe_dict_masking():
    """Verifies that to_safe_dict() masks sensitive API keys."""
    settings = Settings(
        generation_mode=GenerationModeEnum.ONLINE_LLM,
        gemini_api_key="sk-secret-12345-very-confidential"
    )
    safe_data = settings.to_safe_dict()
    assert "sk-secret-12345-very-confidential" not in str(safe_data)
    assert safe_data["gemini_api_key"] == "********[MASKED]"


def test_secret_safe_repr():
    """Verifies that __repr__() does not expose raw secret keys."""
    settings = Settings(
        generation_mode=GenerationModeEnum.ONLINE_LLM,
        gemini_api_key="sk-secret-12345-very-confidential"
    )
    repr_str = repr(settings)
    assert "sk-secret-12345-very-confidential" not in repr_str
    assert "MASKED" in repr_str


def test_environment_separation():
    """Verifies that test environment is explicitly recognized."""
    test_settings = load_settings(env_override={"APP_ENV": "test"})
    assert test_settings.app_env == AppEnvironmentEnum.TEST

    prod_settings = load_settings(env_override={"APP_ENV": "production"})
    assert prod_settings.app_env == AppEnvironmentEnum.PRODUCTION