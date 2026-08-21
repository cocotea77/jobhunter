"""Safety: the two mechanisms that make a public launch survivable.

QUOTAS answer "one user must not drain the service." The counter is a
database row per (user, action, day), incremented with one atomic
statement: INSERT ... ON CONFLICT ... count = count + 1 RETURNING count.
Atomic matters: two simultaneous requests both increment correctly —
there is no check-then-update gap for a double-clicker (or a script) to
slip through. The same lesson as Step 1's unique constraint: rules the
database enforces have no race conditions.

THE BUDGET STOP answers "the service must not bankrupt its owner." The
Step 2 decision — every AI call through one gateway, every cost
recorded — pays its full dividend here: today's spend is one SQL sum
over agent_runs, and the stop is ONE check at the gateway's entrance,
automatically governing every agent that exists and every agent not yet
written. When the cap is reached the service degrades to read-only:
browsing works, AI politely refuses until midnight UTC.
"""

from datetime import datetime, timezone

from sqlalchemy import func as sa_func
from sqlalchemy import select, text

from app.config import settings
from app.db import session_factory


class QuotaExceeded(Exception):
    """A user reached today's allowance for one action."""

    def __init__(self, action: str, limit: int):
        self.action = action
        self.limit = limit
        super().__init__(
            f"You have used today's {limit} {action.replace('_', ' ')}. "
            "Your allowance resets at midnight UTC."
        )


class BudgetExhausted(Exception):
    """The whole service reached today's spending cap."""

    def __init__(self, spent: float, cap: float):
        self.spent = spent
        self.cap = cap
        super().__init__(
            "Today's AI budget is used up, so AI features are paused until "
            "midnight UTC. Everything already computed is still browsable."
        )


async def enforce_quota(user_id: int, action: str, limit: int) -> int:
    """Count this use and refuse if it exceeds the allowance — atomically.

    Returns the count so callers can show "2 of 3 used" if they wish.
    Note the shape: we increment FIRST, then compare. Two concurrent
    requests at count 2 become 3 and 4; exactly one passes a limit of 3.
    A check-then-increment version would let both through.
    """
    async with session_factory() as db:
        count = (
            await db.execute(
                text(
                    "INSERT INTO usage_counters (user_id, action, day, count) "
                    "VALUES (:user_id, :action, CURRENT_DATE, 1) "
                    "ON CONFLICT ON CONSTRAINT uq_usage_user_action_day "
                    "DO UPDATE SET count = usage_counters.count + 1 "
                    "RETURNING count"
                ),
                {"user_id": user_id, "action": action},
            )
        ).scalar_one()
        await db.commit()
    if count > limit:
        raise QuotaExceeded(action, limit)
    return count


async def spent_today_usd() -> float:
    """Today's recorded AI spend — summed from the flight recorder."""
    from app.models import AgentRun

    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    async with session_factory() as db:
        total = (
            await db.execute(
                select(sa_func.coalesce(sa_func.sum(AgentRun.cost_usd), 0.0)).where(
                    AgentRun.created_at >= midnight
                )
            )
        ).scalar_one()
    return float(total)


async def ensure_budget_available() -> None:
    """The stop itself: called at the gateway's entrance, before any AI
    call, in every mode. (Fake calls cost nothing, but read-only is a
    STATE, not a price check — behavior stays identical across modes, so
    what you test in fake mode is what protects you in real mode.)"""
    spent = await spent_today_usd()
    if spent >= settings.max_daily_spend_usd:
        raise BudgetExhausted(spent, settings.max_daily_spend_usd)


async def budget_report() -> dict:
    """For the health endpoint: the operator's one-glance answer."""
    spent = await spent_today_usd()
    return {
        "spent_today_usd": round(spent, 4),
        "cap_usd": settings.max_daily_spend_usd,
        "exhausted": spent >= settings.max_daily_spend_usd,
    }
