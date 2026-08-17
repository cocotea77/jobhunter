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
    assert s.app_name == "JobPilot"
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
