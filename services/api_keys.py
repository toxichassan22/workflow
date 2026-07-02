"""
Shared API key utilities for OpenRouter services.
"""

import os


def get_openrouter_api_key() -> str:
    """Get OpenRouter API key from environment."""
    env_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    return ""


def get_zai_api_key() -> str:
    """Get Z.ai API key from environment."""
    env_key = os.getenv("ZAI_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    return ""

