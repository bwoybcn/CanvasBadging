# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from pydantic import ValidationError

from opencredential.settings import Settings

STRONG = "s" * 48


def test_development_defaults_enable_dev_login() -> None:
    s = Settings(env="development")
    assert s.dev_login_enabled


def test_production_refuses_committed_dev_secrets() -> None:
    with pytest.raises(ValidationError, match="Refusing to start in production"):
        Settings(env="production")


def test_production_refuses_short_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(
            env="production",
            secret_key="short",
            signer_shared_secret=STRONG,
            token_encryption_key=STRONG,
        )


def test_production_with_real_secrets_disables_dev_login() -> None:
    s = Settings(
        env="production",
        secret_key=STRONG,
        signer_shared_secret=STRONG,
        token_encryption_key=STRONG,
    )
    assert not s.dev_login_enabled


def test_production_refuses_dev_token_encryption_key() -> None:
    with pytest.raises(ValidationError, match="OC_TOKEN_ENCRYPTION_KEY"):
        Settings(env="production", secret_key=STRONG, signer_shared_secret=STRONG)
