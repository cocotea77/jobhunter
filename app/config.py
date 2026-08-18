"""Application configuration.

Every value the application needs to know about its surroundings lives in
this one file — nowhere else. That is a deliberate rule with two reasons:

1. When something must change between your laptop and the live server
   (a database address, a secret key, a spending limit), you change an
   environment variable, never the code.
2. When a reader asks "what can be configured here?", the complete answer
   is this single file.

How values are found, in order of priority:
  1. A real environment variable (this is how the live server is configured)
  2. A line in the local ".env" file (this is how your laptop is configured)
  3. The default written below (this is how a fresh checkout works instantly)
"""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The application's own name and version, reported by the health endpoint
    # so you can always ask a running server "who and what are you?".
    app_name: str = "JobHunter"
    version: str = "0.2.0"

    # Which environment this copy believes it is in. Later steps will use
    # this to refuse dangerous actions in production (for example, a
    # "delete everything" helper that only works in development).
    environment: Literal["development", "test", "production"] = "development"

    # --- Step 1: the database ---

    # Where the database lives. The default matches docker-compose.yml
    # exactly, so a fresh checkout connects with zero configuration.
    # The live server will override this with its real, secret address.
    #
    # Anatomy of the address:
    #   postgresql+asyncpg :// user : password @ host : port / database-name
    database_url: str = "postgresql+asyncpg://jobhunter:jobhunter@localhost:5432/jobhunter"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Repair the database address automatically if a hosting company
        hands us the short form.

        Why this exists: hosting platforms (Railway, Heroku, and others)
        provide addresses that start with "postgres://" — an old spelling.
        Our driver needs "postgresql+asyncpg://". This is the single most
        common reason a first deployment fails, so instead of documenting
        the trap, we remove it: any spelling is corrected here, at the one
        place the address enters the application.
        """
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value


# One shared instance, imported everywhere else as:  from app.config import settings
settings = Settings()
