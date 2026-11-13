# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runtime configuration, read from environment variables (prefix ``OC_``)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from opencredential.paths import BACKEND_DIR

#: Committed, publicly known development secrets. Production refuses to start with them.
DEV_SECRET_KEY = "dev-only-insecure-session-key-change-me-0000000000"  # noqa: S105
DEV_SIGNER_SHARED_SECRET = "dev-only-insecure-signer-secret"  # noqa: S105
PLACEHOLDER_VERIFICATION_HOST = "credentials.example.ac.uk"


class Environment(StrEnum):
    development = "development"
    test = "test"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OC_", env_file=".env", extra="ignore")

    env: Environment = Environment.development

    # Runtime role: subject to row-level security, no DDL rights.
    database_url: str = "postgresql+psycopg://oc_app:oc_app_dev@localhost:5432/opencredential"
    # Owner role: runs migrations and dev seeding. Never used by request handlers.
    database_owner_url: str = (
        "postgresql+psycopg://oc_owner:oc_owner_dev@localhost:5432/opencredential"
    )
    db_app_role: str = "oc_app"
    db_signer_role: str = "oc_signer"

    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    session_ttl_minutes: int = Field(default=30, ge=5, le=240)

    signer_url: str = "http://localhost:8790"
    signer_shared_secret: SecretStr = SecretStr(DEV_SIGNER_SHARED_SECRET)

    public_base_url: str = "http://localhost:8000"
    verification_host: str = PLACEHOLDER_VERIFICATION_HOST

    log_level: str = "INFO"
    log_json: bool = True

    static_dir: str | None = None

    #: Filesystem store for badge artwork (content-addressed, immutable files).
    storage_dir: str = str(BACKEND_DIR / "var" / "assets")
    #: Rate limit for on-demand Canvas refreshes (spec §4.4), per course.
    sync_min_interval_seconds: int = Field(default=300, ge=0)

    @property
    def is_production(self) -> bool:
        return self.env == Environment.production

    @property
    def dev_login_enabled(self) -> bool:
        """Development login exists only outside production; there is no flag to force it on."""
        return not self.is_production

    @model_validator(mode="after")
    def _refuse_dev_secrets_in_production(self) -> Settings:
        if not self.is_production:
            return self
        problems = []
        if self.secret_key.get_secret_value() == DEV_SECRET_KEY:
            problems.append("OC_SECRET_KEY is the committed development value")
        if len(self.secret_key.get_secret_value()) < 32:
            problems.append("OC_SECRET_KEY must be at least 32 characters")
        if self.signer_shared_secret.get_secret_value() == DEV_SIGNER_SHARED_SECRET:
            problems.append("OC_SIGNER_SHARED_SECRET is the committed development value")
        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
