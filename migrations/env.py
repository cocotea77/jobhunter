"""Alembic's runtime environment.

This file answers two questions for the migration tool:
  1. WHERE is the database?  — taken from the application's own settings,
     so migrations can never target a different database than the app.
  2. WHAT should the schema look like?  — Base.metadata from app/models.py,
     the single source of truth, which powers both --autogenerate and
     "alembic check" (drift detection).
"""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models import Base

# The complete table catalog Alembic compares the real database against.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline mode: print the SQL instead of running it.

    Used for review ("what exactly would this migration do?") via:
        alembic upgrade head --sql
    """
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Online mode: connect to the real database and apply migrations."""
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
