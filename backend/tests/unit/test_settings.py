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


def test_the_mode_is_never_guessed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """An unset OC_ENV used to mean development: committed secrets accepted, development
    sign-in mounted. A deployment that forgot the variable must be told, not run that way."""
    monkeypatch.delenv("OC_ENV", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env file here to supply it
    with pytest.raises(ValidationError, match="OC_ENV is not set"):
        Settings()
    with pytest.raises(ValidationError):
        Settings(env="prod")  # a typo is refused too, not read as development
    monkeypatch.setenv("OC_ENV", "development")
    assert Settings().dev_login_enabled
