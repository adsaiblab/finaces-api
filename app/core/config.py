"""
app/core/config.py — P0-08 Fix: Centralized pydantic-settings configuration.

All sensitive values are read from environment variables or a .env file.
No hard-coded credentials in source code.
"""

import os
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from typing import Self


class Settings(BaseSettings):
    # ── Project ───────────────────────────────────────────────
    PROJECT_NAME: str = "FinaCES API MCC"
    API_V1_STR: str = "/api/v1"
    VERSION: str = "1.2.0"

    BACKEND_CORS_ORIGINS: list[str] = []

    # ── Environment ───────────────────────────────────────────
    ENVIRONMENT: str = Field(
        default="development",
        description="Deployment environment: development | staging | production"
    )

    # ── Security ────────────────────────────────────────────
    SECRET_KEY: str = Field(
        default="CHANGE_ME_IN_PRODUCTION_PLEASE",
        description="JWT signing secret — override via SECRET_KEY env var"
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Database ────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://finaces:password@localhost:5432/finaces",
        description="Async PostgreSQL DSN — override via DATABASE_URL env var"
    )

    # ── Validators ───────────────────────────────────────────
    @model_validator(mode="after")
    def _check_secret_key(self) -> Self:
        """
        Fail fast if the default placeholder SECRET_KEY is used in a
        non-development environment.  Catches misconfiguration at startup
        before it can be silently exploited.
        """
        if (
            self.ENVIRONMENT in ("staging", "production")
            and self.SECRET_KEY == "CHANGE_ME_IN_PRODUCTION_PLEASE"
        ):
            raise ValueError(
                "SECRET_KEY must be overridden via environment variable in "
                f"{self.ENVIRONMENT}. "
                "Set SECRET_KEY=<strong-random-secret> in your .env or CI secrets."
            )
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


# Singleton accessible throughout the application
settings = Settings()
