"""
Settings module - loads API keys and configuration from environment variables.
All paths are resolved relative to PROJECT_ROOT so the app works from any CWD.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Anchor every relative path to the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root explicitly
load_dotenv(PROJECT_ROOT / ".env", override=True)


class Settings:
    """Central configuration loaded from environment variables."""

    # ── Generation parameters ───────────────────────────────────────────
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.4"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    IMAGE_WIDTH: int = int(os.getenv("IMAGE_WIDTH", "1344"))
    IMAGE_HEIGHT: int = int(os.getenv("IMAGE_HEIGHT", "768"))

    # ── Paths (resolved from PROJECT_ROOT) ──────────────────────────────
    OUTPUT_DIR: Path = PROJECT_ROOT / os.getenv("OUTPUT_DIR", "outputs")
    TEMPLATE_PATH: Path = PROJECT_ROOT / "templates" / "company_template.pptx"

    @classmethod
    def validate(cls) -> list[str]:
        """Validate that required settings are configured. Returns list of errors."""
        errors: list[str] = []
        if not os.getenv("OPENROUTER_API_KEY"):
            errors.append("OPENROUTER_API_KEY is not set. Add it to your .env file.")
        if not cls.TEMPLATE_PATH.exists():
            errors.append(
                f"Template file not found at {cls.TEMPLATE_PATH}. "
                "See README.md for setup instructions."
            )
        return errors


# Module-level singleton
settings = Settings()

# Ensure output directory exists on import
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
