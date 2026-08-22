"""Background jobs: matching runs that outlive their HTTP request.

Why: a matching run takes 30-60 seconds in real mode. A browser waiting
that long on one request sees a frozen page, and hosting platforms cut
long requests off. So POST /match now ENQUEUES: it creates a match_jobs
row, schedules the work, and returns immediately; the page polls the
row and draws an honest progress bar from real numbers.

Why FastAPI's built-in background tasks and not a real queue system
(Celery, RQ, arq): at this scale there is no queue-depth problem, and a
queue adds a broker to deploy, monitor, and explain. The threshold at
which that answer changes, stated for the record: multiple server
replicas (two servers would both run their own tasks with no shared
queue), or work that must survive a restart mid-run rather than being
honestly marked failed. Until then, the simple thing — plus the sweep
below — is the professional thing.

THE STARTUP SWEEP: if the server restarts mid-run (deployments do this
routinely), the task dies with the process and its row would say
'running' forever — a zombie the frontend would poll eternally. On every
boot, any row still 'running' or 'queued' is marked failed with an
honest reason. A crash is an incident; a lie about a crash is a bug.
"""

from datetime import datetime, timezone

from sqlalchemy import select, update

from app.db import session_factory
from app.matching import run_matching
from app.models import MatchJob


async def create_match_job(candidate_id: int) -> int:
    async with session_factory() as db:
        job = MatchJob(candidate_id=candidate_id, status="queued")
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def execute_match_job(job_id: int) -> None:
    """The background worker for one job. Every outcome — success,
    failure, even the budget stop — ends with the row telling the truth."""

    async def set_progress(scored: int, total: int) -> None:
        async with session_factory() as db:
            await db.execute(
                update(MatchJob)
                .where(MatchJob.id == job_id)
                .values(scored=scored, total_to_score=total)
            )
            await db.commit()

    async with session_factory() as db:
        await db.execute(
            update(MatchJob).where(MatchJob.id == job_id).values(status="running")
        )
        await db.commit()
        job = await db.get(MatchJob, job_id)

    try:
        await run_matching(job.candidate_id, progress=set_progress)
        final = {"status": "done", "finished_at": datetime.now(timezone.utc)}
    except Exception as error:  # noqa: BLE001 — the row must always tell the truth
        final = {
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
            "finished_at": datetime.now(timezone.utc),
        }

    async with session_factory() as db:
        await db.execute(update(MatchJob).where(MatchJob.id == job_id).values(**final))
        await db.commit()


async def fail_interrupted_jobs() -> int:
    """The startup sweep. Returns how many zombies were put to rest —
    printed at boot so an interrupted deployment is visible in the log."""
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(MatchJob.id).where(MatchJob.status.in_(["queued", "running"]))
                )
            )
            .scalars()
            .all()
        )
        if rows:
            await db.execute(
                update(MatchJob)
                .where(MatchJob.id.in_(rows))
                .values(
                    status="failed",
                    error="interrupted by a server restart — run matching again",
                    finished_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
    return len(rows)
