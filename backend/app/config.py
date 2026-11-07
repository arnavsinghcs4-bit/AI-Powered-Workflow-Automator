"""Application configuration."""
import os
from pathlib import Path
from pydantic_settings import BaseSettings


def find_env_file() -> Path | None:
    """
    Find .env file by searching from current directory up to root.
    Checks: current dir, backend/, project root.
    """
    candidates = [
        Path(".env"),  # Current directory
        Path("backend") / ".env",  # If running from project root
        Path("..") / ".env",  # If running from backend/
        Path("../..") / ".env",  # Fallback
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return None


class Config(BaseSettings):
    """Application config loaded from environment."""

    # Database
    SUPABASE_DIRECT_URL: str = ""
    SUPABASE_POOLED_URL: str = ""
    ALEMBIC_DATABASE_URL: str = ""
    DATABASE_TEST_URL: str = ""

    # Redis
    REDIS_URL: str = "redis://redis:6379"

    # Auth
    JWT_SECRET: str = "your-secret-key-change-me-in-production"

    # Environment
    ENV: str = "dev"

    def __init__(self, **data):
        super().__init__(**data)

        # Validate required URLs are set
        if not self.SUPABASE_POOLED_URL:
            raise ValueError(
                "SUPABASE_POOLED_URL must be set in .env or environment. "
                "Copy .env.example to .env and add your Supabase connection string."
            )

        if not self.SUPABASE_DIRECT_URL:
            raise ValueError(
                "SUPABASE_DIRECT_URL must be set in .env or environment. "
                "Copy .env.example to .env and add your Supabase connection string."
            )

        # Validate JWT_SECRET on startup
        if self.ENV != "dev" and self.JWT_SECRET == "your-secret-key-change-me-in-production":
            raise ValueError(
                "JWT_SECRET must be changed from the placeholder value in production. "
                "Set ENV=dev to allow the placeholder, or provide a real JWT_SECRET."
            )

    class Config:
        env_file = find_env_file()
        case_sensitive = True


# Load config once at module import
try:
    config = Config()
except ValueError as e:
    # Re-raise with context about where .env should be
    raise ValueError(
        f"Configuration Error: {e}\n\n"
        f"Setup: cp .env.example .env (in project root), then add your Supabase URLs."
    ) from e
