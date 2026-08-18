"""The database connection layer.

One rule, parallel to "all configuration lives in config.py":
all database *plumbing* lives here. Other modules never create their own
connections — they import from this file. When we later need to change how
connections are pooled, timed out, or monitored, there is exactly one
place to do it.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# The engine is the connection manager: it opens connections to Postgres,
# keeps a small pool of them ready for reuse (opening one is expensive),
# and hands them out on request.
#
# pool_pre_ping=True: before lending out a pooled connection, quietly check
# it is still alive. Costs almost nothing; prevents the classic error where
# the database restarted overnight and the application keeps trying to use
# dead connections from before the restart.
engine = create_async_engine(settings.database_url, pool_pre_ping=True)

# A factory that produces database sessions. A session is one short
# conversation with the database: read some rows, write some rows, commit.
# Endpoints will receive one session per request in later steps.
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def database_status() -> str:
    """Answer one question for the health endpoint: can the application,
    right now, actually talk to its database?

    Returns "ok", or "unreachable (<reason>)" — it never raises. The health
    endpoint must always be able to answer, especially when things are
    broken; that is precisely when it is needed most.

    The 2-second limit matters: without it, a hanging database would make
    the health endpoint hang too, and the monitoring tools calling it would
    time out with no information. Failing fast with a clear answer beats
    hanging with none.
    """
    try:
        async with asyncio.timeout(2):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return "ok"
    except Exception as error:  # noqa: BLE001 — must never raise, by design
        return f"unreachable ({type(error).__name__})"
