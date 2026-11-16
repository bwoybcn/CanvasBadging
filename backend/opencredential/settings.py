# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runtime configuration, read from environment variables (prefix ``OC_``)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from opencredential.paths import BACKEND_DIR

#: Committed, publicly known development secrets. Production refuses to start with them.
DEV_SECRET_KEY = "dev-only-insecure-session-key-change-me-0000000000"  # noqa: S105
DEV_SIGNER_SHARED_SECRET = "dev-only-insecure-signer-secret"  # noqa: S105
DEV_TOKEN_ENCRYPTION_KEY = "dev-only-insecure-token-encryption-key-000000"  # noqa: S105
PLACEHOLDER_VERIFICATION_HOST = "credentials.example.ac.uk"


class Environment(StrEnum):
    development = "development"
    test = "test"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OC_", env_file=".env", extra="ignore")

    #: Never guessed. An unset ``OC_ENV`` used to mean development, which accepts the committed
    #: secrets above and mounts the development sign-in: a real deployment that forgot the
    #: variable would have run that way without a word. ``_require_explicit_mode`` says so.
    env: Environment

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
    #: The longest a session may be kept alive by renewal, counted from the Canvas launch. A
    #: value at or below ``session_ttl_minutes`` switches renewal off.
    session_max_minutes: int = Field(default=480, ge=5, le=1440)

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

    # ---- Serving (api/ratelimit.py, docs/deployment/production.md) -----------------------
    #: Requests a minute one client address may make to the routes that verify a credential
    #: without a session (the public checker and share pages). 0 switches the limit off.
    rate_limit_verify_per_minute: int = Field(default=60, ge=0)
    #: The same for the LTI login and launch steps. A whole campus can arrive from one address,
    #: so this is generous: 600 is 300 people opening Badges from one network in one minute.
    rate_limit_signin_per_minute: int = Field(default=600, ge=0)
    #: API processes ``oc api`` starts. One process serves one slow burst at a time.
    api_workers: int = Field(default=1, ge=1, le=64)
    #: Addresses whose ``X-Forwarded-For`` and ``X-Forwarded-Proto`` uvicorn believes: the
    #: reverse proxy's address or network, comma-separated, or ``*`` when only the proxy can
    #: reach the API at all. Without it every visitor looks like the proxy.
    forwarded_allow_ips: str = "127.0.0.1"

    # ---- Alerts (jobs/health.py) ---------------------------------------------------------
    #: Chat channel webhook told when background jobs fail. Unset: no alert is sent, and
    #: ``GET /healthz/jobs`` is the only signal.
    alert_webhook_url: str | None = None
    #: ``text`` for Slack-style incoming webhooks, ``teams`` for a Microsoft Teams workflow.
    alert_webhook_format: Literal["text", "teams"] = "text"

    # ---- Canvas / LTI (W3, ADR-0008, ADR-0009) -------------------------------------------
    #: PEM file holding the tool's RSA private key (LTI client assertions). Development
    #: generates it on first use; production refuses to start without it.
    lti_private_key_file: str = str(BACKEND_DIR / "var" / "lti" / "tool_key.pem")
    #: Key that encrypts Canvas OAuth tokens and client secrets at rest (AES-256-GCM).
    token_encryption_key: SecretStr = SecretStr(DEV_TOKEN_ENCRYPTION_KEY)
    #: Server-side rewrite of Canvas base URLs, for containers that cannot reach the browser's
    #: Canvas address. Example: ``http://localhost:3000=http://host.docker.internal:3000``.
    canvas_url_rewrite: str | None = None
    #: Seconds to wait for Canvas; retries back off exponentially up to ``canvas_max_retries``.
    canvas_timeout_seconds: float = Field(default=20.0, gt=0)
    canvas_max_retries: int = Field(default=4, ge=0, le=10)
    #: Launch state (OIDC ``state``/``nonce``) lifetime.
    lti_state_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    #: Clock skew tolerated when checking ``iat``/``exp`` of platform id tokens.
    lti_clock_skew_seconds: int = Field(default=60, ge=0, le=300)

    @property
    def is_production(self) -> bool:
        return self.env == Environment.production

    @property
    def dev_login_enabled(self) -> bool:
        """Development login exists only outside production; there is no flag to force it on."""
        return not self.is_production

    @model_validator(mode="before")
    @classmethod
    def _require_explicit_mode(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("env"):
            raise ValueError(
                "OC_ENV is not set. Set OC_ENV to development, test or production. The service "
                "does not guess its mode, because development mode accepts publicly known "
                "secrets and offers a sign-in page without Canvas."
            )
        return data

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
        if self.token_encryption_key.get_secret_value() == DEV_TOKEN_ENCRYPTION_KEY:
            problems.append("OC_TOKEN_ENCRYPTION_KEY is the committed development value")
        if len(self.token_encryption_key.get_secret_value()) < 32:
            problems.append("OC_TOKEN_ENCRYPTION_KEY must be at least 32 characters")
        if self.alert_webhook_url and not self.alert_webhook_url.startswith("https://"):
            problems.append("OC_ALERT_WEBHOOK_URL must be an https address")
        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # ``env`` comes from OC_ENV, or startup fails
