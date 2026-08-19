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
    version: str = "0.7.0"

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


    # --- Step 2: the AI gateway ---

    # Fake mode. True (the default) means: never call the real AI service;
    # return realistic canned answers instead. A fresh checkout therefore
    # runs for a student with no key and costs nothing — the same
    # "works instantly, spends nothing" principle as the database default.
    # Continuous Integration keeps this True forever, so the automatic
    # checks can never spend money. You switch it off deliberately, in your
    # local ".env" file, when you want real intelligence:
    #
    #   FAKE_AI=false
    #   ANTHROPIC_API_KEY=sk-ant-...
    fake_ai: bool = True

    # The secret key for the AI service. Empty by default on purpose:
    # the key lives in ".env" (which Git ignores) or in the live server's
    # environment variables — never in code, never in the repository.
    anthropic_api_key: str = ""

    # Which model to use. One knob, changed in one place. Later steps add
    # a second, cheaper model for high-volume simple work; the gateway
    # already records the model per call, so the split will be measurable.
    ai_model: str = "claude-sonnet-4-6"

    # A safety ceiling on answer length, in tokens (roughly: pieces of
    # words; 1000 tokens is about 750 English words). Callers may ask for
    # less, never for more. Output tokens are the expensive kind, so this
    # is the first, crude cost control — Step 8 adds the real one.
    ai_max_output_tokens: int = 2048


    # --- Step 3: ingestion ---

    # How long to wait for one job source before giving up on it, in
    # seconds. A slow source must never be able to hang the whole
    # ingestion run — the same fail-fast principle as the health
    # endpoint's 2-second database limit.
    ingestion_timeout_seconds: float = 20.0

    # How many sources to fetch at the same time. Polite concurrency:
    # fast for us, gentle on the boards' servers.
    ingestion_concurrency: int = 5

    # --- Step 4: resumes, embeddings, matching ---

    # The embedding service key (OpenAI). Empty by default: in fake mode
    # embeddings are computed locally for free, so no key is needed until
    # you deliberately switch to real mode.
    openai_api_key: str = ""

    # Which embedding model, and the width of its vectors. The width is
    # part of the database schema (the vector columns), so changing the
    # model later means a migration — a real cost, chosen consciously.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Matching, stage one: how many postings the cheap vector search
    # keeps. Stage two: how many of those the AI scorer explains, and how
    # many scorer calls run at once. Cost control where quality is not
    # the product; explanation where it is.
    match_top_k_vector: int = 25
    match_top_n_llm: int = 8
    match_concurrency: int = 4

    # --- Step 5: the agent layer ---

    # The coach may make at most this many model round trips per user
    # message. An agent loop without a cap is an unbounded bill and an
    # unbounded wait — the cap is the difference between "agentic" and
    # "runaway".
    coach_max_iterations: int = 5

    # The whole chat turn — model calls, tool executions, everything —
    # must finish inside this wall-clock budget. Generous on purpose:
    # a turn that triggers run_matching legitimately takes ~30-60s in
    # real mode. On timeout the user gets an honest fallback, never a
    # hang.
    chat_timeout_seconds: float = 120.0

    # Input guardrail: the longest user message we accept.
    chat_max_message_chars: int = 4000

    # --- Step 6: the evaluation harness ---

    # Which model judges the agents in real-mode eval runs. A judge may be
    # a different (often stronger) model than the agent it audits.
    judge_model: str = "claude-sonnet-4-6"

# One shared instance, imported everywhere else as:  from app.config import settings
settings = Settings()
