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

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text as sql

from app.config import settings
from app.db import database_status, session_factory
from app.llm import generate_structured

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
# Step 2: a TEMPORARY demonstration endpoint.
#
# It exists so you can watch the gateway work end to end — call it, then
# see the recorded round trip appear in /metrics — before any real agent
# exists. It will be REMOVED in Step 4, when the first real agent (the
# resume parser) replaces it. Scaffolding, clearly labeled as scaffolding.
# ---------------------------------------------------------------------------


class DemoRequest(BaseModel):
    text: str


class DemoAnalysis(BaseModel):
    """The exact shape the demo answer must have — enforced, not hoped for."""

    summary: str
    tone: str
    word_count: int


@app.post("/demo/ai")
async def demo_ai(request: DemoRequest) -> DemoAnalysis:
    """Analyze a snippet of text through the gateway.

    In fake mode (the default) this answers instantly and costs nothing;
    with FAKE_AI=false and a real key in .env it exercises the real model.
    Either way, the round trip is recorded in agent_runs — check /metrics.
    """
    return await generate_structured(
        agent="demo",
        prompt=f"Analyze this text:\n\n{request.text}",
        schema=DemoAnalysis,
        fake_response={
            "summary": "A short note about testing the AI gateway.",
            "tone": "neutral",
            "word_count": 9,
        },
    )
