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

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The application's own name and version, reported by the health endpoint
    # so you can always ask a running server "who and what are you?".
    app_name: str = "JobPilot"
    version: str = "0.1.0"

    # Which environment this copy believes it is in. Later steps will use
    # this to refuse dangerous actions in production (for example, a
    # "delete everything" helper that only works in development).
    environment: Literal["development", "test", "production"] = "development"


# One shared instance, imported everywhere else as:  from app.config import settings
settings = Settings()
