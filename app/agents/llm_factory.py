"""LLM factory – returns a ChatOpenAI instance for the configured provider.

Supported providers (set via ``LLM_PROVIDER`` env var):
    * ``openai``   – OpenAI API (default)
    * ``deepseek`` – DeepSeek API (OpenAI-compatible)
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI
from app.observability.context import get_active_llm_callbacks


_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
        "model_env": "OPENAI_CHAT_MODEL",
    },
    "deepseek": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_CHAT_MODEL",
        "base_url_env": "DEEPSEEK_BASE_URL",
    },
}


def get_provider() -> str:
    """Return the active LLM provider name (lowercase)."""
    return os.getenv("LLM_PROVIDER", "openai").lower()


def default_model_name() -> str:
    """Return the default model name for the active provider."""
    provider = get_provider()
    cfg = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["openai"])
    return os.getenv(cfg["model_env"], cfg["model"])


def create_llm(
    model_name: str | None = None,
    temperature: float = 0.0,
) -> ChatOpenAI:
    """Create a ChatOpenAI instance for the active provider.

    Parameters
    ----------
    model_name : str, optional
        Override the model name.  When *None*, uses the provider's default
        (from env var or built-in fallback).
    temperature : float
        Sampling temperature.
    """
    provider = get_provider()
    cfg = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["openai"])

    resolved_model = model_name or os.getenv(cfg["model_env"], cfg["model"])

    kwargs: dict = {
        "model": resolved_model,
        "temperature": temperature,
    }
    active_callbacks = get_active_llm_callbacks()
    if active_callbacks:
        kwargs["callbacks"] = active_callbacks

    if provider == "deepseek":
        kwargs["api_key"] = os.getenv(cfg["api_key_env"], "")
        kwargs["base_url"] = os.getenv(
            cfg.get("base_url_env", ""), cfg.get("base_url", "")
        )
    # For openai, ChatOpenAI reads OPENAI_API_KEY automatically.

    return ChatOpenAI(**kwargs)
