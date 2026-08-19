"""The web application.

Step 1 change: the health endpoint now also reports whether the database
is reachable, and its HTTP status code becomes meaningful:

  200 — the application AND its database are working
  503 — the application is alive, but a dependency (the database) is not
        ("503 Service Unavailable" is the standard code for exactly this)

Why the status code matters and not just the text: monitoring tools and
hosting platforms do not read sentences — they read status codes. Railway
decides "did this deployment start correctly?" from the code alone, and an
uptime monitor alerts on any non-200. A health endpoint that answers 200
while its database is down would be lying to every tool that protects us.
"""

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy import text as sql

from app.agents.orchestrator import handle_chat
from app.agents.tailor import generate_tailored_content
from app.config import settings
from app.db import database_status, session_factory
from app.embeddings import embed_texts
from app.matching import run_matching
from app.models import Candidate, Job, Match, TailoredResume
from app.resume import (
    CandidateProfile,
    ResumeExtractionError,
    extract_text,
    parse_resume,
    profile_card,
)

app = FastAPI(title=settings.app_name, version=settings.version)


@app.get("/health")
async def health() -> JSONResponse:
    """Report whether the service — and everything it depends on — works."""
    database = await database_status()
    healthy = database == "ok"

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "app": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "database": database,
        },
    )


# ---------------------------------------------------------------------------
# Step 2: metrics — answering "which agent, how many calls, how slow, how
# much money" from stored data alone, with no guesswork.
# ---------------------------------------------------------------------------


@app.get("/metrics")
async def metrics() -> list[dict]:
    """One summary row per agent, aggregated from agent_runs by the
    database itself.

    Reading tip for the SQL below: AVG(CASE WHEN success THEN 1.0 ELSE 0.0
    END) turns true/false into 1/0 and averages them — which IS the success
    rate. Databases are extremely good at this kind of arithmetic; shipping
    thousands of rows to Python to add them up would be slower and wordier.
    """
    query = sql(
        """
        SELECT
            agent,
            COUNT(*)                                        AS calls,
            AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END)    AS success_rate,
            AVG(latency_ms)                                 AS avg_latency_ms,
            SUM(input_tokens)                               AS total_input_tokens,
            SUM(output_tokens)                              AS total_output_tokens,
            SUM(cost_usd)                                   AS total_cost_usd
        FROM agent_runs
        GROUP BY agent
        ORDER BY agent
        """
    )
    async with session_factory() as session:
        rows = (await session.execute(query)).mappings().all()
    return [
        {
            "agent": r["agent"],
            "calls": r["calls"],
            "success_rate": round(float(r["success_rate"]), 3),
            "avg_latency_ms": round(float(r["avg_latency_ms"]), 1),
            "total_input_tokens": int(r["total_input_tokens"]),
            "total_output_tokens": int(r["total_output_tokens"]),
            "total_cost_usd": round(float(r["total_cost_usd"]), 6),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Step 4: candidates and matching — the product's core loop.
# ---------------------------------------------------------------------------


@app.post("/candidates")
async def create_candidate(file: UploadFile = File(...)) -> dict:
    """Upload a resume; receive an understood candidate.

    The chain: extract text (mechanical) → parse into a profile (the
    resume_parser agent, honesty-constrained) → embed the profile card
    (stage one of matching will search with it) → store all three: raw
    text, profile, vector. The raw text is kept forever unmodified — it
    is the ground truth every AI claim about this person must trace to.
    """
    content = await file.read()
    try:
        text = extract_text(file.filename or "resume", content)
    except ResumeExtractionError as error:
        # The file's fault, said kindly: 400 (bad request), with the reason.
        raise HTTPException(status_code=400, detail=str(error)) from error

    profile = await parse_resume(text)
    [vector] = await embed_texts([profile_card(profile)])

    async with session_factory() as session:
        candidate = Candidate(
            name=profile.name,
            raw_text=text,
            profile=profile.model_dump(),
            embedding=vector,
        )
        session.add(candidate)
        await session.commit()
        await session.refresh(candidate)

    return {"id": candidate.id, "name": candidate.name, "profile": candidate.profile}


@app.get("/candidates")
async def list_candidates() -> list[dict]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Candidate.id, Candidate.name, Candidate.created_at)
                .order_by(Candidate.created_at.desc())
            )
        ).all()
    return [
        {"id": r.id, "name": r.name, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@app.get("/candidates/{candidate_id}")
async def get_candidate(candidate_id: int) -> dict:
    async with session_factory() as session:
        candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return {
        "id": candidate.id,
        "name": candidate.name,
        "profile": candidate.profile,
        "created_at": candidate.created_at.isoformat(),
    }


@app.post("/candidates/{candidate_id}/match")
async def match_candidate(candidate_id: int) -> dict:
    """Run the two-stage matching. Expect ~30-60 seconds in real mode
    (8 parallel AI readings); instant in fake mode."""
    try:
        return await run_matching(candidate_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/candidates/{candidate_id}/matches")
async def list_matches(candidate_id: int) -> list[dict]:
    """The ranked results: AI-explained matches first (by score), then
    vector-only ones. NULLs sort last on purpose — an unexplained match
    is a real result, ranked below explained ones."""
    async with session_factory() as session:
        if await session.get(Candidate, candidate_id) is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        rows = (
            await session.execute(
                select(Match, Job.title, Job.company, Job.url, Job.location)
                .join(Job, Job.id == Match.job_id)
                .where(Match.candidate_id == candidate_id)
                .order_by(
                    Match.llm_score.desc().nulls_last(),
                    Match.vector_score.desc(),
                )
            )
        ).all()
    return [
        {
            "job_id": match.job_id,
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "vector_score": match.vector_score,
            "llm_score": match.llm_score,
            "analysis": match.analysis,
        }
        for match, title, company, url, location in rows
    ]


# ---------------------------------------------------------------------------
# Step 5: the agent layer — tailoring and coaching.
# ---------------------------------------------------------------------------


@app.post("/candidates/{candidate_id}/jobs/{job_id}/tailor")
async def tailor(candidate_id: int, job_id: int) -> dict:
    """Tailor this candidate's resume toward this job, and save it.
    ~15-45 seconds in real mode; instant in fake mode."""
    async with session_factory() as session:
        candidate = await session.get(Candidate, candidate_id)
        job = await session.get(Job, job_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    content = await generate_tailored_content(
        CandidateProfile.model_validate(candidate.profile),
        candidate.raw_text,
        job.title,
        job.company,
        job.description,
    )
    async with session_factory() as session:
        row = TailoredResume(
            candidate_id=candidate_id, job_id=job_id, content=content.model_dump()
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return {"id": row.id, "job_id": job_id, "content": row.content}


@app.get("/candidates/{candidate_id}/tailored")
async def list_tailored(candidate_id: int) -> list[dict]:
    async with session_factory() as session:
        if await session.get(Candidate, candidate_id) is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        rows = (
            await session.execute(
                select(TailoredResume, Job.title, Job.company)
                .join(Job, Job.id == TailoredResume.job_id)
                .where(TailoredResume.candidate_id == candidate_id)
                .order_by(TailoredResume.created_at.desc())
            )
        ).all()
    return [
        {
            "id": row.id,
            "job_id": row.job_id,
            "title": title,
            "company": company,
            "content": row.content,
            "created_at": row.created_at.isoformat(),
        }
        for row, title, company in rows
    ]


class ChatRequest(BaseModel):
    message: str
    session_id: int | None = None


@app.post("/candidates/{candidate_id}/chat")
async def chat(candidate_id: int, request: ChatRequest) -> dict:
    """One supervised coach turn. The orchestrator owns validation,
    session identity, the timeout, and the transcript."""
    try:
        return await handle_chat(candidate_id, request.message, request.session_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/candidates/{candidate_id}/sessions/{session_id}/messages")
async def session_messages(candidate_id: int, session_id: int) -> list[dict]:
    """The stored transcript — the observable trace of every turn."""
    from app.models import ChatMessage, ChatSession

    async with session_factory() as session:
        chat_session = await session.get(ChatSession, session_id)
        if chat_session is None or chat_session.candidate_id != candidate_id:
            raise HTTPException(status_code=404, detail="session not found")
        rows = (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id)
            )
        ).scalars().all()
    return [
        {
            "role": row.role,
            "content": row.content,
            "meta": row.meta,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Step 6: the quality ledger.
# ---------------------------------------------------------------------------


@app.get("/evals/runs")
async def eval_runs() -> list[dict]:
    """Eval run history, newest first — pass rates and per-run cost.
    The dashboard page over this data arrives with the frontend (Step 9)."""
    from app.models import EvalRun

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(EvalRun).order_by(EvalRun.created_at.desc()).limit(50)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "run_id": row.id,
            "suite": row.suite,
            "note": row.note,
            "mode": "fake" if row.fake_mode else "real",
            "passed": row.passed,
            "total": row.total,
            "pass_rate": row.pass_rate,
            "cost_usd": row.cost_usd,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
