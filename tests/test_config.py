"""Tests for the configuration.

These look almost too simple to bother with. They are here because the
configuration file is the foundation every later step builds on, and
because they demonstrate the two behaviors students must understand:
defaults exist, and the environment can override them.
"""

from app.config import Settings


def test_defaults_allow_a_fresh_checkout_to_run():
    """With nothing configured at all, sensible defaults apply.

    This is why a student can clone the repository and run it immediately.
    """
    s = Settings(_env_file=None)  # ignore any local .env file for this test
    assert s.app_name == "JobHunter"
    assert s.environment == "development"


def test_environment_variable_overrides_the_default(monkeypatch):
    """A real environment variable must win over the default.

    This is the exact mechanism the live server will use: same code,
    different environment variables.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    s = Settings(_env_file=None)
    assert s.environment == "production"


def test_invalid_environment_is_rejected(monkeypatch):
    """A misspelled environment must fail loudly at startup, not silently
    fall back to a default. A server that quietly runs in the wrong mode is
    far more dangerous than a server that refuses to start."""
    import pytest

    monkeypatch.setenv("ENVIRONMENT", "prodcution")  # deliberate typo
    with pytest.raises(Exception):
        Settings(_env_file=None)


# --- Step 1: the database address normalizer ---
#
# Hosting companies (Railway, Heroku, ...) hand out database addresses that
# start with "postgres://". Our driver needs "postgresql+asyncpg://". The
# Settings class repairs the address automatically — these tests prove it,
# because a wrong database address is the most common reason a first
# deployment fails.


def test_short_postgres_scheme_is_repaired():
    """The old "postgres://" spelling must be rewritten for our driver."""
    s = Settings(_env_file=None, database_url="postgres://u:pw@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://u:pw@host:5432/db"


def test_plain_postgresql_scheme_is_repaired():
    """The driverless "postgresql://" spelling must also be rewritten."""
    s = Settings(_env_file=None, database_url="postgresql://u:pw@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://u:pw@host:5432/db"


def test_correct_address_is_left_untouched():
    """An address that is already correct must pass through unchanged."""
    url = "postgresql+asyncpg://u:pw@host:5432/db"
    s = Settings(_env_file=None, database_url=url)
    assert s.database_url == url
