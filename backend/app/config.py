"""Application configuration."""
import os
from pydantic_settings import BaseSettings


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

        # Validate JWT_SECRET on startup
        if self.ENV != "dev" and self.JWT_SECRET == "your-secret-key-change-me-in-production":
            raise ValueError(
                "JWT_SECRET must be changed from the placeholder value in production. "
                "Set ENV=dev to allow the placeholder, or provide a real JWT_SECRET."
            )

    class Config:
        env_file = ".env"
        case_sensitive = True


config = Config()
