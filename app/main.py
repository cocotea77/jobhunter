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

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy import text as sql

from app.agents.orchestrator import handle_chat
from app.agents.tailor import generate_tailored_content
from app.auth import (
    create_login_token,
    create_session,
    current_user,
    end_session,
    get_owned_candidate,
    require_admin,
    send_login_email,
    set_session_cookie,
    verify_login_token,
)
from app.config import settings
from app.db import database_status, session_factory
from app.embeddings import embed_texts
from app.ingestion.boards import GREENHOUSE_BOARDS, LEVER_COMPANIES
from app.ingestion.pipeline import IngestReport, IngestRequest, ingest
from app.jobs import create_match_job, execute_match_job, fail_interrupted_jobs
from app.models import Candidate, Job, Match, MatchJob, TailoredResume, User
from app.resume import (
    CandidateProfile,
    ResumeExtractionError,
    extract_text,
    parse_resume,
    profile_card,
)
from app.safety import (
    BudgetExhausted,
    QuotaExceeded,
    budget_report,
    enforce_quota,
)

app = FastAPI(title=settings.app_name, version=settings.version)

# Defense in depth: the frontend talks through its own same-origin proxy
# and never needs CORS — this exists for direct API consumers and local
# development against the raw backend.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def sweep_interrupted_jobs() -> None:
    """A restart must never leave a zombie 'running' job (see app/jobs.py)."""
    try:
        swept = await fail_interrupted_jobs()
        if swept:
            print(f"startup sweep: marked {swept} interrupted match job(s) as failed")
    except Exception as error:  # noqa: BLE001 — boot must not die on a sweep
        print(f"startup sweep skipped: {error}")


@app.exception_handler(QuotaExceeded)
async def quota_handler(request: Request, error: QuotaExceeded) -> JSONResponse:
    """429 "Too Many Requests" — the standard code for "slow down." The
    body is the kind sentence with the reset time; the frontend shows it
    as written."""
    return JSONResponse(status_code=429, content={"detail": str(error)})


@app.exception_handler(BudgetExhausted)
async def budget_handler(request: Request, error: BudgetExhausted) -> JSONResponse:
    """503 "Service Unavailable" — honest: the AI half of the service IS
    unavailable, by our own choice, until midnight UTC. Browsing works."""
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.get("/health")
async def health() -> JSONResponse:
    """Report whether the service — and everything it depends on — works."""
    database = await database_status()
    healthy = database == "ok"

    # Step 8: the operator's one-glance budget answer. If the database is
    # down we cannot know the spend — report that honestly, not zero.
    try:
        budget = await budget_report()
        async with session_factory() as session:
            jobs_indexed = (
                await session.execute(select(sa_func.count(Job.id)))
            ).scalar_one()
    except Exception:
        budget = {"error": "unknown (database unreachable)"}
        jobs_indexed = None

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "app": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "database": database,
            "jobs_indexed": jobs_indexed,
            "budget": budget,
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
# Step 3: ingestion — filling the jobs table with real postings.
# (Operator endpoints: they require the x-admin-token header. Restored in
# Step 7 after a shipped regression: the Step 4 cleanup that removed the
# temporary demo endpoint accidentally truncated this section too, and no
# test called these routes over HTTP — so the loss was silent for three
# deliveries until Step 7's admin-token test refused to pass. The
# route-inventory test in tests/test_step7_auth.py now makes any silently
# vanished endpoint a loud test failure forever.)
# ---------------------------------------------------------------------------


@app.post("/ingest")
async def ingest_jobs(
    request: IngestRequest, _: None = Depends(require_admin)
) -> IngestReport:
    """Fetch postings from the requested sources and store them.

    Duplicate-safe by construction (the Step 1 constraint); one dead
    source lands in source_errors instead of killing the run; finishes by
    embedding every job that lacks a meaning vector.
    """
    return await ingest(request)


@app.post("/ingest/curated")
async def ingest_curated(_: None = Depends(require_admin)) -> IngestReport:
    """Fetch the entire curated company-board list — the button the
    nightly refresh will press in Step 10, hand-testable since Step 3."""
    return await ingest(
        IngestRequest(greenhouse=GREENHOUSE_BOARDS, lever=LEVER_COMPANIES)
    )


# ---------------------------------------------------------------------------
# Step 7: accounts — sign in by email link; sessions are database rows.
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str


@app.post("/auth/request-link")
async def request_link(request_body: LoginRequest, request: Request) -> dict:
    """Send a one-time sign-in link (valid 15 minutes, works once).

    In development the link is ALSO returned in the response ("dev_link")
    so students and tests need no email service. That field does not
    exist in production — there, the link travels only by email.
    """
    email = request_body.email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise HTTPException(status_code=400, detail="a valid email is required")
    raw = await create_login_token(email)
    # The link must open where the BROWSER lives (the frontend), so the
    # session cookie lands on the right origin. PUBLIC_BASE_URL is that
    # address in production; empty means development, where the backend's
    # own address works for curl and for the same-machine dev proxy.
    base = (settings.public_base_url or str(request.base_url)).rstrip("/")
    link = f"{base}/auth/verify?token={raw}"
    await send_login_email(email, link)
    body: dict = {"sent": True}
    if settings.environment != "production":
        body["dev_link"] = link
    return body


@app.get("/auth/verify")
async def verify(token: str, response: Response) -> dict:
    """Redeem the link: single-use, then a 30-day session cookie."""
    user = await verify_login_token(token)
    raw_session = await create_session(user)
    set_session_cookie(response, raw_session)
    return {"signed_in": True, "email": user.email}


@app.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    raw = request.cookies.get(settings.session_cookie_name)
    if raw:
        await end_session(raw)  # delete the row: revocation is real
    response.delete_cookie(settings.session_cookie_name)
    return {"signed_out": True}


@app.get("/me")
async def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email}


# ---------------------------------------------------------------------------
# Step 4: candidates and matching — the product's core loop.
# ---------------------------------------------------------------------------


@app.post("/candidates")
async def create_candidate(
    file: UploadFile = File(...),
    consent: bool = Form(False),
    user: User = Depends(current_user),
) -> dict:
    """Upload a resume; receive an understood candidate.

    The chain: extract text (mechanical) → parse into a profile (the
    resume_parser agent, honesty-constrained) → embed the profile card
    (stage one of matching will search with it) → store all three: raw
    text, profile, vector. The raw text is kept forever unmodified — it
    is the ground truth every AI claim about this person must trace to.
    """
    if not consent:
        # 400, before the file is even read: a resume is personal data,
        # and processing it without agreement is not a default we ever
        # fall into by accident.
        raise HTTPException(
            status_code=400,
            detail="consent is required: tick the box agreeing that this "
            "resume will be processed and stored as described in /privacy",
        )
    content = await file.read()
    try:
        text = extract_text(file.filename or "resume", content)
    except ResumeExtractionError as error:
        # The file's fault, said kindly: 400 (bad request), with the reason.
        raise HTTPException(status_code=400, detail=str(error)) from error

    profile = await parse_resume(text)
    [vector] = await embed_texts([profile_card(profile)])

    async with session_factory() as session:
        from datetime import datetime, timezone

        candidate = Candidate(
            user_id=user.id,
            consent_at=datetime.now(timezone.utc),
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
async def list_candidates(user: User = Depends(current_user)) -> list[dict]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Candidate.id, Candidate.name, Candidate.created_at)
                .where(Candidate.user_id == user.id)  # yours, only ever yours
                .order_by(Candidate.created_at.desc())
            )
        ).all()
    return [
        {"id": r.id, "name": r.name, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@app.get("/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: int, user: User = Depends(current_user)
) -> dict:
    candidate = await get_owned_candidate(candidate_id, user)
    return {
        "id": candidate.id,
        "name": candidate.name,
        "profile": candidate.profile,
        "created_at": candidate.created_at.isoformat(),
    }


@app.post("/candidates/{candidate_id}/match")
async def match_candidate(
    candidate_id: int,
    background: BackgroundTasks,
    user: User = Depends(current_user),
) -> dict:
    """ENQUEUE a matching run and return at once. The page polls the
    match-job endpoint below and draws an honest progress bar; the run
    itself takes ~30-60 seconds in real mode, instantly in fake mode."""
    candidate = await get_owned_candidate(candidate_id, user)
    await enforce_quota(user.id, "matching_runs", settings.quota_matching_runs_per_day)
    from app.safety import ensure_budget_available

    # Checked at enqueue so the user hears "budget exhausted" NOW, not
    # inside a background job they would have to poll to discover it.
    await ensure_budget_available()
    if candidate.embedding is None:
        raise HTTPException(status_code=409, detail="candidate has no embedding")

    job_id = await create_match_job(candidate_id)
    background.add_task(execute_match_job, job_id)
    return {"match_job_id": job_id, "status": "queued"}


@app.get("/candidates/{candidate_id}/match-jobs/{job_id}")
async def match_job_status(
    candidate_id: int, job_id: int, user: User = Depends(current_user)
) -> dict:
    """The progress the frontend polls: status, scored-of-total, error."""
    await get_owned_candidate(candidate_id, user)
    async with session_factory() as session:
        job = await session.get(MatchJob, job_id)
    if job is None or job.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="match job not found")
    return {
        "match_job_id": job.id,
        "status": job.status,
        "scored": job.scored,
        "total_to_score": job.total_to_score,
        "error": job.error,
    }


@app.get("/candidates/{candidate_id}/matches")
async def list_matches(
    candidate_id: int, user: User = Depends(current_user)
) -> list[dict]:
    """The ranked results: AI-explained matches first (by score), then
    vector-only ones. NULLs sort last on purpose — an unexplained match
    is a real result, ranked below explained ones."""
    await get_owned_candidate(candidate_id, user)
    async with session_factory() as session:
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
async def tailor(
    candidate_id: int, job_id: int, user: User = Depends(current_user)
) -> dict:
    """Tailor this candidate's resume toward this job, and save it.
    ~15-45 seconds in real mode; instant in fake mode."""
    candidate = await get_owned_candidate(candidate_id, user)
    await enforce_quota(user.id, "tailorings", settings.quota_tailorings_per_day)
    async with session_factory() as session:
        job = await session.get(Job, job_id)
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
async def list_tailored(
    candidate_id: int, user: User = Depends(current_user)
) -> list[dict]:
    await get_owned_candidate(candidate_id, user)
    async with session_factory() as session:
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
async def chat(
    candidate_id: int, request: ChatRequest, user: User = Depends(current_user)
) -> dict:
    """One supervised coach turn. The orchestrator owns validation,
    session identity, the timeout, and the transcript."""
    await get_owned_candidate(candidate_id, user)
    await enforce_quota(
        user.id, "coach_messages", settings.quota_coach_messages_per_day
    )
    try:
        return await handle_chat(candidate_id, request.message, request.session_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/candidates/{candidate_id}/sessions/{session_id}/messages")
async def session_messages(
    candidate_id: int, session_id: int, user: User = Depends(current_user)
) -> list[dict]:
    """The stored transcript — the observable trace of every turn."""
    from app.models import ChatMessage, ChatSession

    await get_owned_candidate(candidate_id, user)
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


# ---------------------------------------------------------------------------
# Step 8: privacy — the promises, and the delete that keeps them.
# ---------------------------------------------------------------------------

PRIVACY_TEXT = """JobHunter privacy, in plain language.

What we store when you use the product: your email address (to sign you
in), your resume text and the structured profile our AI reads from it,
your job matches and their explanations, resumes tailored for you, and
your conversations with the coach. We also record, for every AI call,
how long it took and what it cost — those records contain no resume
content.

What we do with it: exactly what you see in the product — matching,
tailoring, coaching — and nothing else. We do not sell it, share it, or
use it to train models.

What we never store: your resume never appears in our logs, and we keep
no password because none exists.

Deleting everything: DELETE /me (the "Delete my account" button in the
product) removes your account and every record listed above, immediately
and permanently. This is enforced by database cascade rules and proven
by an automated test that counts every table afterward.
"""


@app.get("/privacy")
async def privacy() -> Response:
    return Response(content=PRIVACY_TEXT, media_type="text/plain")


@app.delete("/me")
async def delete_me(
    request: Request, response: Response, user: User = Depends(current_user)
) -> dict:
    """Delete the account and EVERYTHING it owns. The cascade rules
    declared in the migrations do the sweeping: user -> candidates ->
    matches, chat sessions, messages, tailored resumes; plus sign-in
    tokens, sessions, and quota counters. The Step 8 test proves the
    sweep with SQL counts — the privacy page's promise, enforced."""
    raw = request.cookies.get(settings.session_cookie_name)
    async with session_factory() as db:
        db_user = await db.get(User, user.id)
        await db.delete(db_user)
        await db.commit()
    if raw:
        response.delete_cookie(settings.session_cookie_name)
    return {"deleted": True}
